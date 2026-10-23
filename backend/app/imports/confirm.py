"""导入确认与版本切换。

确认阶段是整个导入流程唯一会写题库数据的地方，必须在**单个事务**内完成：

1. 校验预览未过期、归属正确。
2. 校验所有必需确认项都已处理（否则 409 IMPORT_CONFIRMATION_REQUIRED）。
3. 创建新 `bank_version` 和对应的 `question_revisions`。
4. 旧 active 版本标记为 `superseded`，题库 `current_version_id` 指向新版本。

任何一步失败都回滚，旧版本继续可用（NFR-002）。

版本与轮次的关系：轮次一旦创建就固定 `bank_version_id`，永远不会被改写，
因此历史轮次读取的 `question_revisions` 不会因为新版本而失效。

被移除的题目**不会删除 `questions` 行**：它仍然被历史 `question_revisions` 和
`round_items` 引用，物理删除会级联破坏已完成的轮次。移除的语义是
「新版本里没有它的 revision」，因此它不会再被抽取。
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.banks import repository as bank_repository
from app.banks import service as bank_service
from app.common.errors import (
    ImportConfirmationRequiredError,
    ImportPreviewExpiredError,
    InvalidRequestError,
    NotFoundError,
)
from app.common.timeutil import utcnow
from app.db.models import BankVersion, ImportPreview, Question, QuestionRevision, User
from app.imports import service as import_service
from app.imports.normalizer import compute_content_hash, compute_stable_key
from app.imports.schemas import AmbiguityDecision, ConfirmRequest, ConfirmResponse, DiffSummary

logger = logging.getLogger(__name__)


def confirm_import(
    session: Session,
    user: User,
    preview_id: str,
    payload: ConfirmRequest,
) -> ConfirmResponse:
    preview = _load_preview(session, user, preview_id)
    bank = bank_service.get_owned_bank(session, user, preview.bank_id or "")

    # 预览是基于「当时的 current_version」算出来的差异。若期间又导入过一次，
    # 这份 diff 已经对不上题库现状：直接确认会把中间那次新增的题目静默丢掉。
    if preview.diff_payload.get("base_version_id") != bank.current_version_id:
        raise ImportPreviewExpiredError(
            "题库版本已更新，这份预览已过期。请重新导入以获取最新差异。"
        )

    items = list(preview.parsed_payload.get("items", []))
    actions: dict[str, dict] = dict(preview.diff_payload.get("actions", {}))
    removed: list[dict] = list(preview.diff_payload.get("deleted", []))

    accepted_ids = set(payload.accepted_preview_item_ids)
    if not accepted_ids:
        # 未显式指定时，接受所有已判定为「题目」的项
        accepted_ids = {
            item["local_id"] for item in items if item.get("classification") == "question"
        }

    decisions = {entry.preview_item_id: entry for entry in payload.resolved_ambiguities}
    confirmed_deleted = set(payload.confirmed_deleted_question_ids)

    base_version = (
        bank_repository.get_version(session, bank.current_version_id)
        if bank.current_version_id
        else None
    )
    existing_revisions = (
        _load_revisions_by_question(session, base_version.id) if base_version else {}
    )

    _assert_no_pending_decisions(
        items,
        actions,
        removed,
        accepted_ids,
        decisions,
        confirmed_deleted,
        existing_revisions,
    )

    new_version = BankVersion(
        bank_id=bank.id,
        version_number=bank_repository.next_version_number(session, bank.id),
        source_filename=preview.source_filename,
        source_hash=preview.source_hash,
        question_count=0,
        status="active",
    )
    session.add(new_version)
    session.flush()

    changes = DiffSummary()
    order_index = 0

    for item in items:
        local_id = item["local_id"]
        if local_id not in accepted_ids or item.get("classification") != "question":
            continue

        entry = actions.get(local_id, {})
        decision = decisions.get(local_id)

        if decision is not None and decision.decision in ("ignore", "keep_existing"):
            # keep_existing 的新内容不导入，旧修订在循环结束后原样带入新版本
            continue

        question_id, source_revision = _resolve_identity(
            session=session,
            bank_id=bank.id,
            item=item,
            entry=entry,
            decision=decision,
            existing_revisions=existing_revisions,
        )

        new_hash = compute_content_hash(item["title"], item.get("answer_markdown", ""))
        unchanged = (
            source_revision is not None and source_revision.content_hash == new_hash
        )

        revision = _build_revision(
            item=item,
            question_id=question_id,
            bank_version_id=new_version.id,
            order_index=order_index,
            reuse=source_revision if unchanged else None,
        )
        session.add(revision)
        order_index += 1

        if source_revision is None:
            changes.added += 1
        elif unchanged:
            changes.unchanged += 1
        else:
            changes.modified += 1

    # 「保留旧题并忽略新内容」：把旧修订原样带入新版本
    carried_question_ids = {
        decision.question_id
        for decision in decisions.values()
        if decision.decision == "keep_existing" and decision.question_id
    }
    for question_id in carried_question_ids:
        source_revision = existing_revisions.get(question_id)
        if source_revision is None:
            raise InvalidRequestError("要保留的题目不在当前版本中")
        session.add(
            _copy_revision(
                source_revision,
                bank_version_id=new_version.id,
                order_index=order_index,
            )
        )
        order_index += 1
        changes.unchanged += 1

    changes.deleted = sum(
        1 for entry in removed if entry["question_id"] in confirmed_deleted
    )
    changes.ambiguous = 0

    new_version.question_count = order_index

    if base_version is not None:
        base_version.status = "superseded"

    bank.current_version_id = new_version.id
    bank.updated_at = utcnow()

    session.delete(preview)
    session.commit()

    logger.info(
        "导入确认完成：bank=%s version=%s 新增=%d 修改=%d 未变化=%d 删除=%d",
        bank.id,
        new_version.version_number,
        changes.added,
        changes.modified,
        changes.unchanged,
        changes.deleted,
    )

    return ConfirmResponse(
        bank_id=bank.id,
        version_id=new_version.id,
        version_number=new_version.version_number,
        changes=changes,
    )


def _resolve_identity(
    *,
    session: Session,
    bank_id: str,
    item: dict,
    entry: dict,
    decision: AmbiguityDecision | None,
    existing_revisions: dict[str, QuestionRevision],
) -> tuple[str, QuestionRevision | None]:
    """决定这道题在新版本里挂到哪个稳定题目身份上。

    返回 (question_id, 旧修订或 None)。旧修订非空表示这是一道已存在的题。
    """
    if decision is not None and decision.decision == "match_existing":
        question_id = decision.question_id
        source_revision = existing_revisions.get(question_id or "")
        if source_revision is None:
            raise InvalidRequestError("指定的关联题目不在当前版本中")
        _refresh_stable_key(session, question_id, item)
        return question_id, source_revision

    matched_question_id = entry.get("matched_question_id")
    if matched_question_id:
        source_revision = existing_revisions.get(matched_question_id)
        if source_revision is None:
            raise InvalidRequestError("关联的题目已不在当前版本中，请重新生成预览")
        _refresh_stable_key(session, matched_question_id, item)
        return matched_question_id, source_revision

    question = Question(
        bank_id=bank_id,
        stable_key=compute_stable_key(item["title"], item.get("section_path", [])),
    )
    session.add(question)
    session.flush()
    return question.id, None


def _assert_no_pending_decisions(
    items: list[dict],
    actions: dict[str, dict],
    removed: list[dict],
    accepted_ids: set[str],
    decisions: dict[str, AmbiguityDecision],
    confirmed_deleted: set[str],
    existing_revisions: dict[str, QuestionRevision],
) -> None:
    """所有歧义项必须处理完，否则拒绝确认（IMPORT_CONFIRMATION_REQUIRED）。"""
    pending: list[dict] = []

    for item in items:
        local_id = item["local_id"]
        if local_id not in accepted_ids:
            continue
        if item.get("classification") == "needs_review":
            pending.append(
                {
                    "preview_item_id": local_id,
                    "title": item["title"],
                    "reason": "低置信标题需要确认是题目还是分类",
                }
            )
            continue
        entry = actions.get(local_id, {})
        if entry.get("action") == "ambiguous" and local_id not in decisions:
            pending.append(
                {
                    "preview_item_id": local_id,
                    "title": item["title"],
                    "reason": entry.get("detail") or "存在改名/拆题/合题歧义",
                }
            )

    matched_question_ids = {
        decision.question_id
        for decision in decisions.values()
        if decision.decision in ("match_existing", "keep_existing")
    }
    # 被接受、且明确关联到某道旧题的项，等于把这道旧题带进新版本
    for local_id in accepted_ids:
        entry = actions.get(local_id, {})
        if entry.get("matched_question_id"):
            matched_question_ids.add(entry["matched_question_id"])

    reported_removed = {entry["question_id"] for entry in removed}

    for entry in removed:
        question_id = entry["question_id"]
        if entry.get("action") == "ambiguous":
            if question_id in confirmed_deleted or question_id in matched_question_ids:
                continue
            pending.append(
                {
                    "preview_item_id": None,
                    "question_id": question_id,
                    "title": entry["title"],
                    "reason": "该题在新文档中找不到，可能是被改名，请确认是删除还是改名",
                }
            )
        elif question_id not in confirmed_deleted:
            pending.append(
                {
                    "preview_item_id": None,
                    "question_id": question_id,
                    "title": entry["title"],
                    "reason": "该题在新文档中已不存在，请确认删除",
                }
            )

    # 旧题还在新文档里，但用户没有勾选它——这同样是一次删除，
    # 必须像「文档里消失的题」一样显式确认，不能因为没勾选就静默删掉。
    for question_id, revision in existing_revisions.items():
        if question_id in reported_removed or question_id in confirmed_deleted:
            continue
        if question_id in matched_question_ids:
            continue
        pending.append(
            {
                "preview_item_id": None,
                "question_id": question_id,
                "title": revision.title,
                "reason": "该题未包含在本次导入的题目列表中，请确认是否删除",
            }
        )

    if pending:
        raise ImportConfirmationRequiredError(details={"pending": pending})


def _load_preview(session: Session, user: User, preview_id: str) -> ImportPreview:
    preview = import_service.get_preview(session, user, preview_id)
    if preview.bank_id is None:
        raise NotFoundError("导入预览不存在")
    return preview


def _load_revisions_by_question(
    session: Session, bank_version_id: str
) -> dict[str, QuestionRevision]:
    rows = session.execute(
        select(QuestionRevision).where(QuestionRevision.bank_version_id == bank_version_id)
    ).scalars()
    return {revision.question_id: revision for revision in rows}


def _refresh_stable_key(session: Session, question_id: str, item: dict) -> None:
    """人工确认过的改名要落到 `stable_key` 上，下次导入才能自动关联。"""
    question = session.get(Question, question_id)
    if question is None:
        return
    new_key = compute_stable_key(item["title"], item.get("section_path", []))
    if question.stable_key != new_key:
        question.stable_key = new_key


def _build_revision(
    *,
    item: dict,
    question_id: str,
    bank_version_id: str,
    order_index: int,
    reuse: QuestionRevision | None,
) -> QuestionRevision:
    """生成新版本中的题目修订。

    `reuse` 非空表示这道题内容未变化：直接复制旧修订的原文，
    避免规范化后的内容覆盖用户原始排版。
    """
    if reuse is not None:
        return _copy_revision(reuse, bank_version_id=bank_version_id, order_index=order_index)

    return QuestionRevision(
        question_id=question_id,
        bank_version_id=bank_version_id,
        title=item["title"],
        answer_markdown=item.get("answer_markdown", ""),
        heading_level=item.get("heading_level", 2),
        section_path=list(item.get("section_path", [])),
        content_hash=compute_content_hash(item["title"], item.get("answer_markdown", "")),
        source_anchor=dict(item.get("source_anchor", {})),
        order_index=order_index,
    )


def _copy_revision(
    source: QuestionRevision, *, bank_version_id: str, order_index: int
) -> QuestionRevision:
    return QuestionRevision(
        question_id=source.question_id,
        bank_version_id=bank_version_id,
        title=source.title,
        answer_markdown=source.answer_markdown,
        heading_level=source.heading_level,
        section_path=list(source.section_path or []),
        content_hash=source.content_hash,
        source_anchor=dict(source.source_anchor or {}),
        order_index=order_index,
    )
