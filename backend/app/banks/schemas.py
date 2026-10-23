"""题库相关请求/响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.common.timeutil import UtcDateTime

RoundStatus = Literal["in_progress", "completed", "abandoned"]


class BankCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class ActiveRoundSummary(BaseModel):
    id: str
    round_number: int
    current_index: int
    total_count: int
    status: RoundStatus
    progress_version: int
    bank_version_id: str


class BankSummary(BaseModel):
    id: str
    name: str
    description: str | None
    question_count: int
    current_version: int | None
    current_version_id: str | None
    active_round: ActiveRoundSummary | None
    # 已走完全部题目的轮数。列表页用它回答「这个题库我刷过几轮了」，
    # 放弃的轮次不计入。
    completed_round_count: int
    created_at: UtcDateTime
    updated_at: UtcDateTime


class BankVersionOut(BaseModel):
    id: str
    version_number: int
    question_count: int
    source_filename: str
    source_hash: str
    status: Literal["active", "superseded"]
    created_at: UtcDateTime


class QuestionListItem(BaseModel):
    """列表页只返回摘要，避免把完整答案全部下发（docs/03 第 4 节）。"""

    id: str
    question_id: str
    title: str
    heading_level: int
    section_path: list[str]
    answer_summary: str


class QuestionListPage(BaseModel):
    items: list[QuestionListItem]
    page: int
    page_size: int
    total: int
    total_pages: int
