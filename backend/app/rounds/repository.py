"""轮次数据访问层。"""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, joinedload

from app.db.models import QuestionBank, QuestionRevision, Round, RoundAdvanceRequest, RoundItem


def get_round(session: Session, round_id: str) -> Round | None:
    return session.execute(
        select(Round)
        .options(joinedload(Round.items))
        .where(Round.id == round_id)
        .limit(1)
    ).unique().scalar_one_or_none()


def get_round_with_bank(session: Session, round_id: str) -> tuple[Round, QuestionBank] | None:
    row = session.execute(
        select(Round, QuestionBank)
        .join(QuestionBank, QuestionBank.id == Round.bank_id)
        .options(joinedload(Round.items))
        .where(Round.id == round_id)
        .limit(1)
    ).unique().one_or_none()
    if row is None:
        return None
    return row[0], row[1]


def get_active_round(session: Session, bank_id: str) -> Round | None:
    return session.execute(
        select(Round)
        .where(Round.bank_id == bank_id, Round.status == "in_progress")
        .order_by(Round.round_number.desc())
        .limit(1)
    ).scalar_one_or_none()


def list_rounds(session: Session, bank_id: str) -> list[Round]:
    return list(
        session.execute(
            select(Round)
            .where(Round.bank_id == bank_id)
            .order_by(Round.round_number.desc())
        ).scalars()
    )


def next_round_number(session: Session, bank_id: str) -> int:
    current = session.execute(
        select(func.max(Round.round_number)).where(Round.bank_id == bank_id)
    ).scalar_one_or_none()
    return int(current or 0) + 1


def count_round_items(session: Session, round_id: str) -> int:
    return int(
        session.execute(
            select(func.count()).select_from(RoundItem).where(RoundItem.round_id == round_id)
        ).scalar_one()
    )


def get_item_at(session: Session, round_id: str, position: int) -> RoundItem | None:
    return session.execute(
        select(RoundItem)
        .options(joinedload(RoundItem.revision))
        .where(RoundItem.round_id == round_id, RoundItem.position == position)
        .limit(1)
    ).unique().scalar_one_or_none()


def list_revisions_for_version(session: Session, bank_version_id: str) -> list[QuestionRevision]:
    return list(
        session.execute(
            select(QuestionRevision)
            .where(QuestionRevision.bank_version_id == bank_version_id)
            .order_by(QuestionRevision.order_index, QuestionRevision.id)
        ).scalars()
    )


def find_advance_request(
    session: Session, round_id: str, idempotency_key: str
) -> RoundAdvanceRequest | None:
    return session.execute(
        select(RoundAdvanceRequest)
        .where(
            RoundAdvanceRequest.round_id == round_id,
            RoundAdvanceRequest.idempotency_key == idempotency_key,
        )
        .limit(1)
    ).scalar_one_or_none()


def claim_progress(
    session: Session,
    *,
    round_id: str,
    expected_progress_version: int,
    values: dict[str, object],
) -> bool:
    """乐观锁推进：只有当 `progress_version` 仍是期望值时才写入。

    先读后写会让两个并发请求都通过「版本相等」检查、然后互相覆盖
    （丢失更新：两台设备各点一次「下一题」，服务端只前进一格）。
    把检查与写入合并成一条带条件的 UPDATE，由数据库保证只有一个请求能改到行。
    """
    result = session.execute(
        update(Round)
        .where(
            Round.id == round_id,
            Round.progress_version == expected_progress_version,
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1
