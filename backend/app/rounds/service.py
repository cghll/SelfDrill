"""轮次生成、推进与并发校验。

核心保证（FR-007 / FR-008 / FR-009）：

- 开始一轮时在**服务端**生成完整随机排列，一轮中每题恰好出现一次。
- 顺序写入 `round_items`，前端不能提供或修改顺序。
- 推进携带 `expected_progress_version`，不匹配返回 409，不允许静默跳题。
- 「下一题」与「上一题」都走 `advance`，方向由 `direction` 指定；
  回退同样经过乐观锁与幂等校验，前端永远不能自行改写当前位置。
- `idempotency_key` 保证网络重试不会多推进一次。
- `reveal` 幂等；未 reveal 前答案不出现在响应里。
- 轮次固定 `bank_version_id`，题库更新不会改变已有轮次。
"""

from __future__ import annotations

import logging
from random import SystemRandom

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.banks import repository as bank_repository
from app.banks import service as bank_service
from app.common.errors import (
    InvalidRequestError,
    NotFoundError,
    RoundProgressConflictError,
)
from app.common.timeutil import utcnow
from app.db.models import Round, RoundAdvanceRequest, RoundItem, User
from app.rounds import repository as repo
from app.rounds.schemas import (
    AdvanceRequest,
    RoundDetail,
    RoundItemOut,
    RoundQuestionOut,
    RoundSummary,
)

logger = logging.getLogger(__name__)

_rng = SystemRandom()


def start_round(
    session: Session,
    user: User,
    bank_id: str,
    *,
    restart: bool = False,
) -> tuple[RoundDetail, bool]:
    """开始新一轮。返回 (轮次详情, 是否新建)。

    已有进行中的轮次时默认复用它，避免重复创建；`restart=true` 会先放弃旧轮次。
    """
    bank = bank_service.get_owned_bank(session, user, bank_id)

    active = repo.get_active_round(session, bank.id)
    if active is not None:
        if not restart:
            return to_round_detail(session, active), False
        active.status = "abandoned"
        session.flush()

    version = (
        bank_repository.get_version(session, bank.current_version_id)
        if bank.current_version_id
        else None
    )
    if version is None:
        raise InvalidRequestError("题库还没有可用的题目版本，请先导入 Markdown 文档")

    revisions = repo.list_revisions_for_version(session, version.id)
    if not revisions:
        raise InvalidRequestError("当前题库版本没有题目，无法开始轮次")

    ordered = _shuffle(revisions)

    round_obj = Round(
        bank_id=bank.id,
        bank_version_id=version.id,
        round_number=repo.next_round_number(session, bank.id),
        status="in_progress",
        current_index=0,
        progress_version=1,
        started_at=utcnow(),
    )
    session.add(round_obj)
    session.flush()

    for position, revision in enumerate(ordered):
        session.add(
            RoundItem(
                round_id=round_obj.id,
                question_revision_id=revision.id,
                position=position,
                presented_at=utcnow() if position == 0 else None,
            )
        )
    session.commit()

    logger.info(
        "开始轮次：bank=%s round=%s 题目数=%d", bank.id, round_obj.round_number, len(ordered)
    )
    return to_round_detail(session, round_obj), True


def _shuffle(revisions: list[QuestionRevision]) -> list[QuestionRevision]:
    """无放回随机排列，使用系统熵源。"""
    ordered = list(revisions)
    _rng.shuffle(ordered)
    return ordered


def get_round_detail(session: Session, user: User, round_id: str) -> RoundDetail:
    round_obj = _get_owned_round(session, user, round_id)
    return to_round_detail(session, round_obj)


def reveal_answer(session: Session, user: User, round_id: str) -> RoundItemOut:
    """展示当前题答案。重复调用幂等，不会推进进度。"""
    round_obj = _get_owned_round(session, user, round_id)
    if round_obj.status != "in_progress":
        raise InvalidRequestError("轮次已结束，无法查看答案")

    item = repo.get_item_at(session, round_obj.id, round_obj.current_index)
    if item is None:
        raise NotFoundError("当前题不存在")

    if not item.answer_revealed:
        item.answer_revealed = True
        item.revealed_at = utcnow()
        session.commit()

    return to_item_out(item, include_answer=True)


def advance_round(
    session: Session, user: User, round_id: str, payload: AdvanceRequest
) -> RoundDetail:
    """按 `direction` 移动当前位置：`next` 推进，`previous` 回退。

    两个方向共用同一套并发保证：都要求 `expected_progress_version` 匹配、
    都让 `progress_version` 自增、都用 `idempotency_key` 去重。
    这样「上一题」不会成为绕过乐观锁的后门。
    """
    round_obj = _get_owned_round(session, user, round_id)

    # 幂等：同一个 key 重放直接返回当前状态，不额外移动
    if payload.idempotency_key:
        existing = repo.find_advance_request(session, round_obj.id, payload.idempotency_key)
        if existing is not None:
            return to_round_detail(session, round_obj)

    if round_obj.status != "in_progress":
        raise InvalidRequestError("轮次已结束，无法继续推进")

    if round_obj.progress_version != payload.expected_progress_version:
        raise _conflict(session, user, round_id, payload.expected_progress_version)

    total = repo.count_round_items(session, round_obj.id)
    if total == 0:
        raise InvalidRequestError("轮次没有题目")

    if payload.direction == "previous":
        if round_obj.current_index <= 0:
            # 已经在第一题：没有可回退的位置。这里做成无副作用的空操作而不是报错，
            # 两台设备同时按「上一题」时不会有一方拿到莫名其妙的失败。
            return to_round_detail(session, round_obj)
        next_index = round_obj.current_index - 1
        is_last = False
    else:
        is_last = round_obj.current_index >= total - 1
        next_index = round_obj.current_index if is_last else round_obj.current_index + 1

    values: dict[str, object] = {
        "current_index": next_index,
        # 用 SQL 表达式自增，避免把「读到的版本号」当成新值写回去
        "progress_version": Round.progress_version + 1,
    }
    if is_last:
        values["status"] = "completed"
        values["completed_at"] = utcnow()

    try:
        claimed = repo.claim_progress(
            session,
            round_id=round_obj.id,
            expected_progress_version=payload.expected_progress_version,
            values=values,
        )
    except OperationalError as exc:
        # SQLite 在「读事务升级为写事务」时不会等待 busy_timeout，而是直接返回
        # SQLITE_BUSY。这同样意味着另一个请求正在写，按冲突处理而不是 500。
        session.rollback()
        raise _conflict(session, user, round_id, payload.expected_progress_version) from exc

    if not claimed:
        # 检查通过之后、写入之前被别人抢先推进了
        session.rollback()
        raise _conflict(session, user, round_id, payload.expected_progress_version)

    if not is_last:
        next_item = repo.get_item_at(session, round_obj.id, next_index)
        if next_item is not None and next_item.presented_at is None:
            next_item.presented_at = utcnow()

    if payload.idempotency_key:
        session.add(
            RoundAdvanceRequest(
                round_id=round_obj.id,
                idempotency_key=payload.idempotency_key,
                result_progress_version=payload.expected_progress_version + 1,
            )
        )

    session.commit()
    # 上面的 UPDATE 走的是 Core 语句，ORM 里的 round_obj 还是旧值，必须重新读
    session.refresh(round_obj)
    return to_round_detail(session, round_obj)


def _conflict(
    session: Session, user: User, round_id: str, expected: int
) -> RoundProgressConflictError:
    """带着「服务端实际状态」构造冲突错误，方便前端提示与排查。"""
    fresh = _get_owned_round(session, user, round_id)
    return RoundProgressConflictError(
        details={
            "expected_progress_version": expected,
            "actual_progress_version": fresh.progress_version,
            "current_index": fresh.current_index,
        }
    )


def abandon_round(session: Session, user: User, round_id: str) -> Round:
    """放弃进行中的轮次。已结束的轮次再次调用是幂等的。"""
    round_obj = _get_owned_round(session, user, round_id)
    if round_obj.status == "in_progress":
        round_obj.status = "abandoned"
        round_obj.progress_version += 1
        session.commit()
    return round_obj


def list_rounds(session: Session, user: User, bank_id: str) -> list[RoundSummary]:
    bank = bank_service.get_owned_bank(session, user, bank_id)
    return [to_round_summary(session, item) for item in repo.list_rounds(session, bank.id)]


# --- 内部 ---


def _get_owned_round(session: Session, user: User, round_id: str) -> Round:
    found = repo.get_round_with_bank(session, round_id)
    if found is None:
        raise NotFoundError("轮次不存在")
    round_obj, bank = found
    if bank.user_id != user.id:
        raise NotFoundError("轮次不存在")
    return round_obj


def to_round_summary(session: Session, round_obj: Round) -> RoundSummary:
    return RoundSummary(
        id=round_obj.id,
        bank_id=round_obj.bank_id,
        bank_version_id=round_obj.bank_version_id,
        round_number=round_obj.round_number,
        status=round_obj.status,  # type: ignore[arg-type]
        current_index=round_obj.current_index,
        total_count=repo.count_round_items(session, round_obj.id),
        progress_version=round_obj.progress_version,
        started_at=round_obj.started_at,
        completed_at=round_obj.completed_at,
    )


def to_round_detail(session: Session, round_obj: Round) -> RoundDetail:
    total = repo.count_round_items(session, round_obj.id)
    current_item: RoundItemOut | None = None

    if round_obj.status == "in_progress":
        item = repo.get_item_at(session, round_obj.id, round_obj.current_index)
        if item is not None:
            current_item = to_item_out(item, include_answer=item.answer_revealed)

    return RoundDetail(
        id=round_obj.id,
        bank_id=round_obj.bank_id,
        bank_version_id=round_obj.bank_version_id,
        round_number=round_obj.round_number,
        status=round_obj.status,  # type: ignore[arg-type]
        current_index=round_obj.current_index,
        total_count=total,
        progress_version=round_obj.progress_version,
        started_at=round_obj.started_at,
        completed_at=round_obj.completed_at,
        current_item=current_item,
    )


def to_item_out(item: RoundItem, *, include_answer: bool) -> RoundItemOut:
    revision = item.revision
    return RoundItemOut(
        id=item.id,
        position=item.position,
        question=RoundQuestionOut(
            id=revision.question_id,
            title=revision.title,
            section_path=list(revision.section_path or []),
        ),
        answer=revision.answer_markdown if include_answer else None,
        answer_revealed=item.answer_revealed,
    )
