"""题库接口（docs/03 第 4 节）。"""

from __future__ import annotations

from fastapi import APIRouter, Query, Response

from app.auth.dependencies import CurrentUser, DbSession
from app.banks import service as bank_service
from app.banks.schemas import (
    BankCreate,
    BankSummary,
    BankVersionOut,
    QuestionListPage,
)

router = APIRouter(prefix="/banks", tags=["banks"])


@router.get("", response_model=list[BankSummary])
def list_banks(current_user: CurrentUser, session: DbSession) -> list[BankSummary]:
    return bank_service.list_bank_summaries(session, current_user)


@router.post("", response_model=BankSummary, status_code=201)
def create_bank(
    payload: BankCreate, current_user: CurrentUser, session: DbSession
) -> BankSummary:
    bank = bank_service.create_bank(session, current_user, payload)
    return bank_service.to_bank_summary(session, bank)


@router.get("/{bank_id}", response_model=BankSummary)
def get_bank(bank_id: str, current_user: CurrentUser, session: DbSession) -> BankSummary:
    return bank_service.get_bank_summary(session, current_user, bank_id)


@router.delete("/{bank_id}", status_code=204)
def delete_bank(bank_id: str, current_user: CurrentUser, session: DbSession) -> Response:
    bank_service.delete_bank(session, current_user, bank_id)
    return Response(status_code=204)


@router.get("/{bank_id}/versions", response_model=list[BankVersionOut])
def list_versions(
    bank_id: str, current_user: CurrentUser, session: DbSession
) -> list[BankVersionOut]:
    return bank_service.list_versions(session, current_user, bank_id)


@router.get("/{bank_id}/questions", response_model=QuestionListPage)
def list_questions(
    bank_id: str,
    current_user: CurrentUser,
    session: DbSession,
    version_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    keyword: str | None = Query(default=None, max_length=200),
) -> QuestionListPage:
    return bank_service.list_questions(
        session,
        current_user,
        bank_id,
        version_id=version_id,
        page=page,
        page_size=page_size,
        keyword=keyword,
    )
