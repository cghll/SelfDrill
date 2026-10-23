"""导入事务编排：上传校验、预览生成、预览修正。

事务边界：预览只写 `import_previews`，绝不触碰题库数据。
真正写入题库版本发生在确认阶段（`app.imports.confirm`）。
"""

from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.banks import repository as bank_repository
from app.banks import service as bank_service
from app.common.errors import (
    FileTooLargeError,
    ImportPreviewExpiredError,
    InvalidRequestError,
    MarkdownParseFailedError,
    NotFoundError,
    UnsupportedFileTypeError,
)
from app.common.text import summarize_markdown
from app.common.timeutil import utcnow
from app.config import get_settings
from app.db.models import BankVersion, ImportPreview, QuestionRevision, User
from app.imports import matcher, parser
from app.imports.matcher import ExistingQuestion, IncomingQuestion
from app.imports.normalizer import (
    compute_content_hash,
    compute_stable_key,
    normalize_title,
    sha256_hex,
)
from app.imports.schemas import (
    DeletedItemOut,
    DiffSummary,
    MatchCandidate,
    PreviewItemOut,
    PreviewItemPatch,
    PreviewItemPatchResponse,
    PreviewResponse,
    PreviewSummary,
)

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = (".md", ".markdown")
ALLOWED_CONTENT_TYPES = {
    "text/markdown",
    "text/x-markdown",
    "text/plain",
    "application/markdown",
    "application/octet-stream",
    "binary/octet-stream",
}
_CHUNK_SIZE = 64 * 1024


def create_preview(
    session: Session,
    user: User,
    bank_id: str,
    upload: UploadFile,
) -> PreviewResponse:
    """解析上传文件并生成导入预览。"""
    bank = bank_service.get_owned_bank(session, user, bank_id)
    settings = get_settings()

    filename = _validate_filename(upload.filename)
    _validate_content_type(upload.content_type)

    raw = _read_upload(upload, settings.max_upload_size)
    text = _decode_utf8(raw)

    line_count = text.count("\n") + 1
    if line_count > settings.max_upload_lines:
        raise MarkdownParseFailedError(
            f"文件行数 {line_count} 超过限制 {settings.max_upload_lines}"
        )

    source_hash = sha256_hex(raw)
    _store_source_file(raw, source_hash, settings.upload_path)

    parsed = parser.parse_document(
        text,
        source_filename=filename,
        source_hash=source_hash,
        max_seconds=settings.max_parse_seconds,
    )

    items = [
        parser.to_preview_item_payload(heading, f"node-{index + 1:03d}")
        for index, heading in enumerate(parsed.headings)
    ]

    current_version = (
        bank_repository.get_version(session, bank.current_version_id)
        if bank.current_version_id
        else None
    )
    diff_payload = build_diff(session, bank.id, current_version, items)

    preview = ImportPreview(
        user_id=user.id,
        bank_id=bank.id,
        source_filename=filename,
        source_hash=source_hash,
        parsed_payload={
            "document": {
                "source_filename": filename,
                "source_hash": source_hash,
                "line_count": parsed.line_count,
            },
            # 保留原文，让 patch 阶段能在分类改变后重算答案边界（FR-005）。
            # 预览确认或过期后即被删除，不会长期占用空间。
            "source_text": text,
            "items": items,
            "warnings": list(parsed.warnings),
        },
        diff_payload=diff_payload,
        expires_at=utcnow() + timedelta(seconds=settings.preview_ttl_seconds),
    )
    session.add(preview)
    session.commit()
    return to_preview_response(session, preview)


def build_diff(
    session: Session,
    bank_id: str,
    current_version: BankVersion | None,
    items: list[dict],
) -> dict:
    """计算新文档与当前版本的差异。"""
    if current_version is None:
        actions = {item["local_id"]: _create_mode_action(item) for item in items}
        return {
            "mode": "create",
            "base_version_id": None,
            "actions": actions,
            "deleted": [],
            "summary": _summarize_actions(actions),
        }

    existing = load_existing_questions(session, current_version.id)
    incoming = [
        IncomingQuestion(
            local_id=item["local_id"],
            title=item["title"],
            section_path=list(item["section_path"]),
            answer_markdown=item["answer_markdown"],
        )
        for item in items
        if item["classification"] in ("question", "needs_review")
    ]

    results, unmatched = matcher.match_questions(incoming, existing)
    hints = matcher.detect_structural_ambiguity(incoming, unmatched)

    actions: dict[str, dict] = {}
    for item in items:
        local_id = item["local_id"]
        if item["classification"] not in ("question", "needs_review"):
            actions[local_id] = {"action": "ignored", "matched_question_id": None, "candidates": []}
            continue
        result = results[local_id]
        candidates = list(result.candidates)
        if result.action == "added" and hints.get(local_id):
            candidates = hints[local_id]
            if candidates:
                result = matcher.MatchResult(
                    action="ambiguous",
                    candidates=candidates,
                    detail="新题与某个已移除的旧题高度相似，请确认是改名还是新增",
                )
        actions[local_id] = {
            "action": result.action,
            "matched_question_id": result.matched_question_id,
            "matched_revision_id": result.matched_revision_id,
            "candidates": candidates,
            "detail": result.detail,
        }

    deleted = _build_removed_items(unmatched, actions)

    return {
        "mode": "update",
        "base_version_id": current_version.id,
        "actions": actions,
        "deleted": deleted,
        "summary": _summarize_actions(actions, removed=deleted),
    }


def _build_removed_items(unmatched: list[ExistingQuestion], actions: dict[str, dict]) -> list[dict]:
    """把「旧版本有、新文档没有」的题整理成删除候选。

    如果某道旧题同时出现在某个新题的改名候选里，它就不能直接标成删除，
    否则用户会看到「新增 + 删除」而不是「可能改名」。
    """
    rename_candidates: dict[str, list[str]] = {}
    for local_id, entry in actions.items():
        for candidate in entry.get("candidates", []):
            rename_candidates.setdefault(candidate["question_id"], []).append(local_id)

    removed: list[dict] = []
    for item in unmatched:
        possible = rename_candidates.get(item.question_id, [])
        removed.append(
            {
                "question_id": item.question_id,
                "title": item.title,
                "section_path": list(item.section_path),
                "action": "ambiguous" if possible else "deleted",
                "possible_local_ids": possible,
            }
        )
    return removed


def _create_mode_action(item: dict) -> dict:
    if item["classification"] not in ("question", "needs_review"):
        return {"action": "ignored", "matched_question_id": None, "candidates": []}
    return {
        "action": "added",
        "matched_question_id": None,
        "matched_revision_id": None,
        "candidates": [],
        "detail": None,
    }


def _summarize_actions(actions: dict[str, dict], removed: list[dict] | None = None) -> dict:
    summary = DiffSummary()
    for entry in actions.values():
        action = entry["action"]
        if action == "added":
            summary.added += 1
        elif action == "modified":
            summary.modified += 1
        elif action == "unchanged":
            summary.unchanged += 1
        elif action == "ambiguous":
            summary.ambiguous += 1

    for item in removed or []:
        if item["action"] == "deleted":
            summary.deleted += 1
        else:
            summary.ambiguous += 1

    return summary.model_dump()


def load_existing_questions(session: Session, bank_version_id: str) -> list[ExistingQuestion]:
    rows = session.execute(
        select(QuestionRevision)
        .where(QuestionRevision.bank_version_id == bank_version_id)
        .order_by(QuestionRevision.order_index, QuestionRevision.id)
    ).scalars()

    existing: list[ExistingQuestion] = []
    for revision in rows:
        section_path = list(revision.section_path or [])
        existing.append(
            ExistingQuestion(
                question_id=revision.question_id,
                revision_id=revision.id,
                title=revision.title,
                section_path=section_path,
                answer_markdown=revision.answer_markdown,
                content_hash=compute_content_hash(revision.title, revision.answer_markdown),
                stable_key=compute_stable_key(revision.title, section_path),
            )
        )
    return existing


def get_preview(session: Session, user: User, preview_id: str) -> ImportPreview:
    preview = session.get(ImportPreview, preview_id)
    if preview is None or preview.user_id != user.id:
        raise NotFoundError("导入预览不存在")
    if preview.expires_at <= utcnow():
        raise ImportPreviewExpiredError()
    return preview


def patch_item(
    session: Session,
    user: User,
    preview_id: str,
    preview_item_id: str,
    patch: PreviewItemPatch,
) -> PreviewItemPatchResponse:
    """修改预览项的标题、答案、分类或关联关系（FR-005）。"""
    preview = get_preview(session, user, preview_id)
    payload = dict(preview.parsed_payload)
    items = [dict(item) for item in payload.get("items", [])]

    target = next((item for item in items if item["local_id"] == preview_item_id), None)
    if target is None:
        raise NotFoundError("预览项不存在")

    if patch.title is not None:
        title = patch.title.strip()
        if not title:
            raise InvalidRequestError("题目标题不能为空")
        target["title"] = title
        target["normalized_title"] = _normalize(title)
        target["patched"] = True

    if patch.answer_markdown is not None:
        target["answer_markdown"] = patch.answer_markdown
        target["patched"] = True
        # 手工改过的答案不能被后续的边界重算覆盖
        target["answer_edited"] = True

    if patch.classification is not None:
        target["classification"] = patch.classification
        target["needs_review"] = patch.classification == "needs_review"
        target["patched"] = True

    actions = dict(preview.diff_payload.get("actions", {}))
    entry = dict(actions.get(preview_item_id, {}))

    if patch.clear_match:
        entry["matched_question_id"] = None
        entry["matched_revision_id"] = None
        entry["candidates"] = []
        entry["detail"] = None
        if target["classification"] in ("question", "needs_review"):
            entry["action"] = "added"
    elif patch.match_question_id is not None:
        entry["matched_question_id"] = patch.match_question_id
        entry["matched_revision_id"] = None
        entry["candidates"] = []
        entry["detail"] = None
        entry["action"] = "modified"

    if target["classification"] == "section":
        entry = {"action": "ignored", "matched_question_id": None, "candidates": []}
    elif entry.get("action") == "ignored" and target["classification"] == "question":
        entry = {
            "action": "added",
            "matched_question_id": None,
            "matched_revision_id": None,
            "candidates": [],
            "detail": None,
        }

    actions[preview_item_id] = entry

    # 分类改变会移动答案边界（子标题并回父题 / 从父题拆出），
    # 必须按新分类重算，否则预览显示的答案和确认后落库的答案不一致。
    affected: list[dict] = []
    if patch.classification is not None:
        affected = _recompute_boundaries(payload, items)

    diff_payload = dict(preview.diff_payload)
    diff_payload["actions"] = actions
    diff_payload["summary"] = _summarize_actions(actions, removed=diff_payload.get("deleted", []))

    preview.parsed_payload = {**payload, "items": items}
    preview.diff_payload = diff_payload
    session.commit()

    return _to_patch_response(preview, items, preview_item_id, affected)


def _recompute_boundaries(payload: dict, items: list[dict]) -> list[dict]:
    """按当前分类重算答案边界，并保住用户手工改过的答案。"""
    lines = str(payload.get("source_text", "")).splitlines()
    if not lines:
        return []

    edited = {
        item["local_id"]: item["answer_markdown"]
        for item in items
        if item.get("answer_edited")
    }

    affected = parser.recompute_answer_ranges(items, lines)
    affected_ids = {item["local_id"] for item in affected}

    # 手工编辑优先：重算只负责「边界」，不能覆盖用户写下的内容
    for item in items:
        if item["local_id"] not in edited:
            continue
        item["answer_markdown"] = edited[item["local_id"]]
        item["content_flags"] = parser.detect_content_flags(item["answer_markdown"])
        affected_ids.add(item["local_id"])

    # 被改成分类的手工编辑内容，按语义应并入上一道题
    _merge_demoted_edits(items, edited, affected_ids)

    return [item for item in items if item["local_id"] in affected_ids]


def _merge_demoted_edits(
    items: list[dict], edited: dict[str, str], affected_ids: set[str]
) -> None:
    """把「手工改过答案、随后被标为分类」的内容并回上一道题。"""
    for index, item in enumerate(items):
        if item["local_id"] not in edited or item.get("classification") != "section":
            continue
        parent = next(
            (
                candidate
                for candidate in reversed(items[:index])
                if candidate.get("classification") in ("question", "needs_review")
            ),
            None,
        )
        if parent is None:
            continue
        block = f"{item.get('raw_title', '')}\n\n{item['answer_markdown']}".strip()
        if not block:
            continue
        parent["answer_markdown"] = (
            f"{parent.get('answer_markdown', '')}\n\n{block}".strip()
        )
        parent["content_flags"] = parser.detect_content_flags(parent["answer_markdown"])
        affected_ids.add(parent["local_id"])


def _to_patch_response(
    preview: ImportPreview,
    items: list[dict],
    preview_item_id: str,
    affected: list[dict],
) -> PreviewItemPatchResponse:
    out_items = [to_preview_item_out(preview, item) for item in items]
    patched = next(item for item in out_items if item.preview_item_id == preview_item_id)
    affected_ids = {item["local_id"] for item in affected} - {preview_item_id}

    diff_payload = preview.diff_payload
    summary = dict(diff_payload.get("summary", {}))

    return PreviewItemPatchResponse(
        **patched.model_dump(),
        affected_items=[item for item in out_items if item.preview_item_id in affected_ids],
        summary=_build_summary(out_items, list(preview.parsed_payload.get("warnings", []))),
        diff=DiffSummary(**{key: summary.get(key, 0) for key in DiffSummary.model_fields}),
    )


def to_preview_response(session: Session, preview: ImportPreview) -> PreviewResponse:
    payload = preview.parsed_payload
    items = payload.get("items", [])
    warnings = list(payload.get("warnings", []))

    out_items = [to_preview_item_out(preview, item) for item in items]
    deleted = [
        DeletedItemOut(**entry) for entry in preview.diff_payload.get("deleted", [])
    ]

    diff_payload = preview.diff_payload
    summary = dict(diff_payload.get("summary", {}))

    return PreviewResponse(
        preview_id=preview.id,
        bank_id=preview.bank_id or "",
        mode=diff_payload.get("mode", "create"),
        source_filename=preview.source_filename,
        source_hash=preview.source_hash,
        expires_at=preview.expires_at.isoformat() + "Z",
        summary=_build_summary(out_items, warnings),
        diff=DiffSummary(**{key: summary.get(key, 0) for key in DiffSummary.model_fields}),
        items=out_items,
        deleted_items=deleted,
        warnings=warnings,
    )


def _build_summary(out_items: list[PreviewItemOut], warnings: list[str]) -> PreviewSummary:
    candidates = [item for item in out_items if item.classification != "section"]
    high_confidence = sum(
        1 for item in candidates if item.classification == "question" and not item.needs_review
    )
    needs_review = sum(1 for item in candidates if item.needs_review)
    warning_count = len(warnings) + sum(len(item.warnings) for item in candidates)
    return PreviewSummary(
        total_candidates=len(candidates),
        high_confidence=high_confidence,
        needs_review=needs_review,
        warnings=warning_count,
    )


def to_preview_item_out(preview: ImportPreview, item: dict) -> PreviewItemOut:
    entry = preview.diff_payload.get("actions", {}).get(item["local_id"], {})
    return PreviewItemOut(
        preview_item_id=item["local_id"],
        action=entry.get("action", "added"),
        title=item["title"],
        raw_title=item.get("raw_title", ""),
        heading_level=item.get("heading_level", 2),
        section_path=list(item.get("section_path", [])),
        answer_markdown=item.get("answer_markdown", ""),
        answer_summary=summarize_markdown(item.get("answer_markdown", "")),
        classification=item["classification"],
        confidence=item.get("confidence", 0.0),
        needs_review=item.get("needs_review", False),
        matched_question_id=entry.get("matched_question_id"),
        source_anchor=item.get("source_anchor", {"start_line": 0, "end_line": 0}),
        content_flags=item.get("content_flags", {}),
        warnings=list(item.get("warnings", [])),
        candidates=[MatchCandidate(**candidate) for candidate in entry.get("candidates", [])],
        diff_detail=entry.get("detail"),
    )


# --- 上传校验 ---


def _validate_filename(filename: str | None) -> str:
    if not filename:
        raise UnsupportedFileTypeError("缺少文件名")
    lowered = filename.lower()
    if not lowered.endswith(ALLOWED_EXTENSIONS):
        raise UnsupportedFileTypeError("只支持 .md 文件")
    # 只保留文件名本身，避免把客户端传来的路径写进数据库或日志
    return filename.replace("\\", "/").rsplit("/", 1)[-1]


def _validate_content_type(content_type: str | None) -> None:
    if not content_type:
        return
    normalized = content_type.split(";", 1)[0].strip().lower()
    if normalized in ALLOWED_CONTENT_TYPES:
        return
    raise UnsupportedFileTypeError(f"不支持的内容类型：{normalized}")


def _read_upload(upload: UploadFile, max_size: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = upload.file.read(_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_size:
            raise FileTooLargeError(f"文件超过大小限制 {max_size} 字节")
        chunks.append(chunk)
    return b"".join(chunks)


def _decode_utf8(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise MarkdownParseFailedError("文件不是有效的 UTF-8 编码") from exc


def _store_source_file(raw: bytes, source_hash: str, upload_dir) -> None:
    """按内容哈希保存原文件，重复导入不会产生副本。"""
    try:
        upload_dir.mkdir(parents=True, exist_ok=True)
        target = upload_dir / f"{source_hash}.md"
        if not target.exists():
            target.write_bytes(raw)
    except OSError as exc:  # pragma: no cover - 磁盘问题不应阻断导入预览
        logger.warning("保存上传文件失败：%s", type(exc).__name__)


def _normalize(title: str) -> str:
    return normalize_title(title)
