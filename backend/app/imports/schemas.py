"""导入预览与确认的请求/响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ItemAction = Literal["added", "modified", "deleted", "unchanged", "ambiguous", "ignored"]
ItemClassification = Literal["question", "section", "needs_review"]


class PreviewSummary(BaseModel):
    total_candidates: int
    high_confidence: int
    needs_review: int
    warnings: int


class PreviewItemOut(BaseModel):
    preview_item_id: str
    action: ItemAction
    title: str
    raw_title: str
    heading_level: int
    section_path: list[str]
    answer_markdown: str
    answer_summary: str
    classification: ItemClassification
    confidence: float
    needs_review: bool
    matched_question_id: str | None
    source_anchor: dict[str, int]
    content_flags: dict[str, bool]
    warnings: list[str]
    candidates: list["MatchCandidate"] = []
    diff_detail: str | None = None


class MatchCandidate(BaseModel):
    question_id: str
    title: str
    section_path: list[str]
    similarity: float
    reason: str


class DeletedItemOut(BaseModel):
    question_id: str
    title: str
    section_path: list[str]
    # deleted：确认要被移除；ambiguous：可能是被改名，必须先确认
    action: Literal["deleted", "ambiguous"] = "deleted"
    possible_local_ids: list[str] = []


class DiffSummary(BaseModel):
    added: int = 0
    modified: int = 0
    deleted: int = 0
    unchanged: int = 0
    ambiguous: int = 0


class PreviewResponse(BaseModel):
    preview_id: str
    bank_id: str
    mode: Literal["create", "update"]
    source_filename: str
    source_hash: str
    expires_at: str
    summary: PreviewSummary
    diff: DiffSummary
    items: list[PreviewItemOut]
    deleted_items: list[DeletedItemOut]
    warnings: list[str]


class PreviewItemPatch(BaseModel):
    classification: ItemClassification | None = None
    title: str | None = Field(default=None, max_length=1000)
    answer_markdown: str | None = None
    match_question_id: str | None = None
    # 明确表示「这是新题，不要关联到任何旧题」
    clear_match: bool = False


class PreviewItemPatchResponse(PreviewItemOut):
    """PATCH 的响应：被改的条目本身 + 被连带影响的兄弟条目。

    改判分类会改变**父题**的答案边界，所以只返回被 patch 的那一条是不够的：
    前端如果不同步这些兄弟条目，预览里显示的答案就会和确认后写进题库的答案不一致。
    这里用继承保留原有的顶层字段，避免破坏既有调用方。
    """

    affected_items: list[PreviewItemOut] = []
    summary: PreviewSummary | None = None
    diff: DiffSummary | None = None


class AmbiguityDecision(BaseModel):
    """歧义项的处理决定（docs/04 第 6.3 节给出的四个选项）。

    - `match_existing`：关联旧题（改名）
    - `create_new`：作为新题
    - `keep_existing`：保留旧题并忽略新内容
    - `ignore`：忽略这道新题（旧题按删除候选处理）
    """

    preview_item_id: str
    decision: Literal["match_existing", "create_new", "keep_existing", "ignore"]
    question_id: str | None = None


class ConfirmRequest(BaseModel):
    accepted_preview_item_ids: list[str] = []
    resolved_ambiguities: list[AmbiguityDecision] = []
    # 被确认要删除的旧题（删除必须显式确认，见 FR-006）
    confirmed_deleted_question_ids: list[str] = []


class ConfirmResponse(BaseModel):
    bank_id: str
    version_id: str
    version_number: int
    changes: DiffSummary


PreviewItemOut.model_rebuild()
