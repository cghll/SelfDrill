"""题库数据访问层：只做查询与写入，不包含业务判断。"""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import BankVersion, QuestionBank, QuestionRevision, Round, RoundItem


def list_banks(session: Session, user_id: str) -> list[QuestionBank]:
    return list(
        session.execute(
            select(QuestionBank)
            .where(QuestionBank.user_id == user_id)
            .order_by(QuestionBank.updated_at.desc(), QuestionBank.created_at.desc())
        ).scalars()
    )


def get_bank(session: Session, bank_id: str) -> QuestionBank | None:
    return session.get(QuestionBank, bank_id)


def add_bank(session: Session, bank: QuestionBank) -> QuestionBank:
    session.add(bank)
    session.flush()
    return bank


def delete_bank(session: Session, bank: QuestionBank) -> None:
    session.delete(bank)


def get_version(session: Session, version_id: str) -> BankVersion | None:
    return session.get(BankVersion, version_id)


def list_versions(session: Session, bank_id: str) -> list[BankVersion]:
    return list(
        session.execute(
            select(BankVersion)
            .where(BankVersion.bank_id == bank_id)
            .order_by(BankVersion.version_number.desc())
        ).scalars()
    )


def latest_version(session: Session, bank_id: str) -> BankVersion | None:
    return session.execute(
        select(BankVersion)
        .where(BankVersion.bank_id == bank_id)
        .order_by(BankVersion.version_number.desc())
        .limit(1)
    ).scalar_one_or_none()


def next_version_number(session: Session, bank_id: str) -> int:
    current = session.execute(
        select(func.max(BankVersion.version_number)).where(BankVersion.bank_id == bank_id)
    ).scalar_one_or_none()
    return int(current or 0) + 1


def count_revisions(session: Session, bank_version_id: str) -> int:
    return int(
        session.execute(
            select(func.count())
            .select_from(QuestionRevision)
            .where(QuestionRevision.bank_version_id == bank_version_id)
        ).scalar_one()
    )


def get_active_round(session: Session, bank_id: str) -> Round | None:
    """题库当前进行中的轮次（用于列表页和详情页展示）。"""
    return session.execute(
        select(Round)
        .where(Round.bank_id == bank_id, Round.status == "in_progress")
        .order_by(Round.round_number.desc())
        .limit(1)
    ).scalar_one_or_none()


def count_round_items(session: Session, round_id: str) -> int:
    return int(
        session.execute(
            select(func.count()).select_from(RoundItem).where(RoundItem.round_id == round_id)
        ).scalar_one()
    )


def count_completed_rounds(session: Session, bank_id: str) -> int:
    """已完成（走完全部题目）的轮数。放弃的轮次不计入。"""
    return int(
        session.execute(
            select(func.count())
            .select_from(Round)
            .where(Round.bank_id == bank_id, Round.status == "completed")
        ).scalar_one()
    )


def list_revisions_page(
    session: Session,
    bank_version_id: str,
    *,
    page: int,
    page_size: int,
    keyword: str | None,
) -> tuple[list[QuestionRevision], int]:
    conditions = [QuestionRevision.bank_version_id == bank_version_id]
    if keyword:
        pattern = f"%{keyword.strip()}%"
        conditions.append(
            or_(
                QuestionRevision.title.ilike(pattern),
                QuestionRevision.answer_markdown.ilike(pattern),
            )
        )

    total = int(
        session.execute(
            select(func.count()).select_from(QuestionRevision).where(*conditions)
        ).scalar_one()
    )
    rows = list(
        session.execute(
            select(QuestionRevision)
            .where(*conditions)
            .order_by(QuestionRevision.order_index, QuestionRevision.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).scalars()
    )
    return rows, total
