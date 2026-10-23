"""轮次相关请求/响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.common.timeutil import UtcDateTime

RoundStatus = Literal["in_progress", "completed", "abandoned"]

# 移动方向。「上一题」不新增路由，而是复用 advance：
# docs/03 第 6 节的轮次路由是固定清单（6 个），扩展现有接口的入参
# 既满足「前端不得自行修改当前位置」，也不破坏路由契约。
RoundDirection = Literal["next", "previous"]


class RoundStartRequest(BaseModel):
    """服务端不接受客户端传来的题目顺序（FR-007）。"""

    restart: bool = False


class RoundQuestionOut(BaseModel):
    id: str
    title: str
    section_path: list[str]


class RoundItemOut(BaseModel):
    id: str
    position: int
    question: RoundQuestionOut
    # 未 reveal 前必须为 null，不能只靠前端隐藏（docs/03 第 6 节）
    answer: str | None = None
    answer_revealed: bool = False


class RoundDetail(BaseModel):
    id: str
    bank_id: str
    bank_version_id: str
    round_number: int
    status: RoundStatus
    current_index: int
    total_count: int
    progress_version: int
    started_at: UtcDateTime
    completed_at: UtcDateTime | None = None
    current_item: RoundItemOut | None = None


class RoundSummary(BaseModel):
    id: str
    bank_id: str
    bank_version_id: str
    round_number: int
    status: RoundStatus
    current_index: int
    total_count: int
    progress_version: int
    started_at: UtcDateTime
    completed_at: UtcDateTime | None = None


class AdvanceRequest(BaseModel):
    expected_progress_version: int = Field(ge=1)
    idempotency_key: str | None = Field(default=None, max_length=128)
    direction: RoundDirection = "next"


class AbandonResponse(BaseModel):
    id: str
    status: RoundStatus
    round_number: int
