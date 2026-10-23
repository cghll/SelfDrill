"""题库生命周期业务逻辑。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.banks import repository as repo
from app.banks.schemas import (
    ActiveRoundSummary,
    BankCreate,
    BankSummary,
    BankVersionOut,
    QuestionListItem,
    QuestionListPage,
)
from app.common.errors import InvalidRequestError, NotFoundError
from app.common.text import summarize_markdown
from app.db.models import BankVersion, QuestionBank, QuestionRevision, User

_ANSWER_SUMMARY_LIMIT = 160


def create_bank(session: Session, user: User, payload: BankCreate) -> QuestionBank:
    name = payload.name.strip()
    if not name:
        raise InvalidRequestError("题库名称不能为空")
    bank = QuestionBank(
        user_id=user.id,
        name=name,
        description=(payload.description or "").strip() or None,
    )
    repo.add_bank(session, bank)
    session.commit()
    return bank


def delete_bank(session: Session, user: User, bank_id: str) -> None:
    """删除题库及其全部版本、题目、轮次和导入记录（依赖数据库级级联）。"""
    bank = get_owned_bank(session, user, bank_id)
    repo.delete_bank(session, bank)
    session.commit()


def get_owned_bank(session: Session, user: User, bank_id: str) -> QuestionBank:
    """取题库并校验归属。不区分「不存在」与「不属于你」，避免探测他人资源。"""
    bank = repo.get_bank(session, bank_id)
    if bank is None or bank.user_id != user.id:
        raise NotFoundError("题库不存在")
    return bank


def list_bank_summaries(session: Session, user: User) -> list[BankSummary]:
    return [to_bank_summary(session, bank) for bank in repo.list_banks(session, user.id)]


def get_bank_summary(session: Session, user: User, bank_id: str) -> BankSummary:
    return to_bank_summary(session, get_owned_bank(session, user, bank_id))


def to_bank_summary(session: Session, bank: QuestionBank) -> BankSummary:
    version = (
        repo.get_version(session, bank.current_version_id) if bank.current_version_id else None
    )
    question_count = version.question_count if version else 0

    active_round = repo.get_active_round(session, bank.id)
    active_summary = None
    if active_round is not None:
        active_summary = ActiveRoundSummary(
            id=active_round.id,
            round_number=active_round.round_number,
            current_index=active_round.current_index,
            total_count=repo.count_round_items(session, active_round.id),
            status=active_round.status,
            progress_version=active_round.progress_version,
            bank_version_id=active_round.bank_version_id,
        )

    return BankSummary(
        id=bank.id,
        name=bank.name,
        description=bank.description,
        question_count=question_count,
        current_version=version.version_number if version else None,
        current_version_id=version.id if version else None,
        active_round=active_summary,
        completed_round_count=repo.count_completed_rounds(session, bank.id),
        created_at=bank.created_at,
        updated_at=bank.updated_at,
    )


def list_versions(session: Session, user: User, bank_id: str) -> list[BankVersionOut]:
    bank = get_owned_bank(session, user, bank_id)
    return [to_version_out(version) for version in repo.list_versions(session, bank.id)]


def to_version_out(version: BankVersion) -> BankVersionOut:
    return BankVersionOut(
        id=version.id,
        version_number=version.version_number,
        question_count=version.question_count,
        source_filename=version.source_filename,
        source_hash=version.source_hash,
        status=version.status,  # type: ignore[arg-type]
        created_at=version.created_at,
    )


def list_questions(
    session: Session,
    user: User,
    bank_id: str,
    *,
    version_id: str | None,
    page: int,
    page_size: int,
    keyword: str | None,
) -> QuestionListPage:
    bank = get_owned_bank(session, user, bank_id)

    version: BankVersion | None
    if version_id:
        version = repo.get_version(session, version_id)
        if version is None or version.bank_id != bank.id:
            raise NotFoundError("题库版本不存在")
    else:
        version = (
            repo.get_version(session, bank.current_version_id)
            if bank.current_version_id
            else None
        )

    if version is None:
        return QuestionListPage(items=[], page=page, page_size=page_size, total=0, total_pages=0)

    if page < 1:
        raise InvalidRequestError("page 必须大于等于 1")
    if page_size < 1 or page_size > 200:
        raise InvalidRequestError("page_size 必须在 1 到 200 之间")

    rows, total = repo.list_revisions_page(
        session,
        version.id,
        page=page,
        page_size=page_size,
        keyword=keyword,
    )
    total_pages = (total + page_size - 1) // page_size if total else 0
    return QuestionListPage(
        items=[to_question_list_item(revision) for revision in rows],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
    )


def to_question_list_item(revision: QuestionRevision) -> QuestionListItem:
    return QuestionListItem(
        id=revision.id,
        question_id=revision.question_id,
        title=revision.title,
        heading_level=revision.heading_level,
        section_path=list(revision.section_path or []),
        answer_summary=summarize_answer(revision.answer_markdown),
    )


def summarize_answer(answer_markdown: str, limit: int = _ANSWER_SUMMARY_LIMIT) -> str:
    return summarize_markdown(answer_markdown, limit=limit)
