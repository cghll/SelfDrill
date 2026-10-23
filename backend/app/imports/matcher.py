"""更新匹配与差异计算。

匹配优先级（FR-006，严格按序）：

1. 人工确认过的稳定关联（`questions.stable_key` 命中）
2. 规范化标题完全相同
3. 同一章节路径下的高相似度标题 —— **只作为候选，绝不自动确认**

歧义规则：1 旧 → 1 新但标题显著变化 = 改名候选；1 旧 → 多 新 = 拆题候选；
多 旧 → 1 新 = 合题候选。这三类都必须由用户确认，禁止静默处理。

原文序号（`1.` `2.`）只用于展示，不参与匹配。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.imports.normalizer import compute_content_hash, compute_stable_key, similarity

# 同章节标题相似度高于此值才进入「改名候选」
RENAME_SIMILARITY_THRESHOLD = 0.55
# 高于此值视为「标题只是排版变化」，可以直接自动匹配
AUTO_MATCH_SIMILARITY_THRESHOLD = 0.92


@dataclass
class ExistingQuestion:
    """当前版本中的一道题，供匹配使用。"""

    question_id: str
    revision_id: str
    title: str
    section_path: list[str]
    answer_markdown: str
    content_hash: str
    stable_key: str


@dataclass
class IncomingQuestion:
    """新文档中的一道题。"""

    local_id: str
    title: str
    section_path: list[str]
    answer_markdown: str
    content_hash: str = ""
    stable_key: str = ""

    def __post_init__(self) -> None:
        if not self.stable_key:
            self.stable_key = compute_stable_key(self.title, self.section_path)
        if not self.content_hash:
            self.content_hash = compute_content_hash(self.title, self.answer_markdown)


@dataclass
class MatchResult:
    """一道新题与旧版本的比较结果。"""

    action: str  # added / modified / unchanged / ambiguous
    matched_question_id: str | None = None
    matched_revision_id: str | None = None
    candidates: list[dict] = field(default_factory=list)
    detail: str | None = None
    # 人工确认的关联（不是自动推断），确认导入时优先使用
    confirmed: bool = False


def build_indexes(existing: list[ExistingQuestion]) -> tuple[dict[str, ExistingQuestion], dict[str, list[ExistingQuestion]]]:
    by_stable_key: dict[str, ExistingQuestion] = {}
    by_normalized_title: dict[str, list[ExistingQuestion]] = {}
    for question in existing:
        by_stable_key.setdefault(question.stable_key, question)
        normalized = compute_stable_key(question.title, question.section_path).split("|", 1)[0]
        by_normalized_title.setdefault(normalized, []).append(question)
    return by_stable_key, by_normalized_title


def match_questions(
    incoming: list[IncomingQuestion],
    existing: list[ExistingQuestion],
) -> tuple[dict[str, MatchResult], list[ExistingQuestion]]:
    """把新文档的题目与当前版本对齐。

    返回 (每个新题的匹配结果, 未被任何新题匹配的旧题列表)。
    """
    by_stable_key, by_title = build_indexes(existing)
    results: dict[str, MatchResult] = {}
    consumed: set[str] = set()

    for question in incoming:
        result = _match_one(question, existing, by_stable_key, by_title, consumed)
        results[question.local_id] = result
        if result.matched_question_id:
            consumed.add(result.matched_question_id)

    unmatched = [item for item in existing if item.question_id not in consumed]
    return results, unmatched


def _match_one(
    question: IncomingQuestion,
    existing: list[ExistingQuestion],
    by_stable_key: dict[str, ExistingQuestion],
    by_title: dict[str, list[ExistingQuestion]],
    consumed: set[str],
) -> MatchResult:
    # 优先级 1：规范化标题 + 章节路径完全一致（人工确认过的关联也落在同一个键上）
    exact_key = by_stable_key.get(question.stable_key)
    if exact_key is not None and exact_key.question_id not in consumed:
        return _classify_content_change(question, exact_key)

    # 优先级 2：规范化标题完全相同（允许章节路径变化）
    normalized_title = question.stable_key.split("|", 1)[0]
    same_title = [
        item
        for item in by_title.get(normalized_title, [])
        if item.question_id not in consumed
    ]
    if len(same_title) == 1:
        return _classify_content_change(question, same_title[0])

    # 优先级 3：同章节下的高相似度标题，只作为候选
    # 候选池必须是全部未消费的旧题：标题改名后按标题建的索引已经查不到了。
    candidates = _find_candidates(question, existing, consumed)
    if candidates:
        return MatchResult(
            action="ambiguous",
            candidates=candidates,
            detail="标题发生变化，可能是改名，需要确认是同一道题还是新题",
        )

    return MatchResult(action="added")


def _classify_content_change(
    question: IncomingQuestion, existing: ExistingQuestion
) -> MatchResult:
    if question.content_hash == existing.content_hash:
        return MatchResult(
            action="unchanged",
            matched_question_id=existing.question_id,
            matched_revision_id=existing.revision_id,
        )
    return MatchResult(
        action="modified",
        matched_question_id=existing.question_id,
        matched_revision_id=existing.revision_id,
    )


def _find_candidates(
    question: IncomingQuestion,
    existing: list[ExistingQuestion],
    consumed: set[str],
) -> list[dict]:
    """在同一章节路径下寻找高相似度标题作为改名候选。"""
    scored: list[tuple[float, ExistingQuestion]] = []
    for candidate in existing:
        if candidate.question_id in consumed:
            continue
        if _normalized_path(candidate.section_path) != _normalized_path(question.section_path):
            continue
        score = similarity(question.title, candidate.title)
        if score >= RENAME_SIMILARITY_THRESHOLD:
            scored.append((score, candidate))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "question_id": candidate.question_id,
            "title": candidate.title,
            "section_path": list(candidate.section_path),
            "similarity": round(score, 3),
            "reason": "同一章节路径下标题高度相似",
        }
        for score, candidate in scored[:5]
    ]


def detect_structural_ambiguity(
    incoming: list[IncomingQuestion],
    unmatched: list[ExistingQuestion],
) -> dict[str, list[dict]]:
    """识别「一道旧题对应多道新题」（拆题）与「多道旧题对应一道新题」（合题）。

    返回 {local_id: [候选说明]}，这些候选会被合并进对应题目的匹配结果里。
    """
    hints: dict[str, list[dict]] = {}
    if not unmatched:
        return hints

    for question in incoming:
        matches = []
        for old in unmatched:
            score = similarity(question.title, old.title)
            if score >= RENAME_SIMILARITY_THRESHOLD:
                matches.append(
                    {
                        "question_id": old.question_id,
                        "title": old.title,
                        "section_path": list(old.section_path),
                        "similarity": round(score, 3),
                        "reason": "可能与已删除的旧题相关",
                    }
                )
        if matches:
            matches.sort(key=lambda item: item["similarity"], reverse=True)
            hints[question.local_id] = matches[:5]
    return hints


def _normalized_path(section_path: list[str]) -> str:
    from app.imports.normalizer import normalize_section_path

    return normalize_section_path(section_path)
