"""轮次接口（docs/03 第 6 节）。"""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.auth.dependencies import CurrentUser, DbSession
from app.rounds import service as round_service
from app.rounds.schemas import (
    AbandonResponse,
    AdvanceRequest,
    RoundDetail,
    RoundItemOut,
    RoundStartRequest,
    RoundSummary,
)

router = APIRouter(tags=["rounds"])


@router.post("/banks/{bank_id}/rounds", response_model=RoundDetail)
def start_round(
    bank_id: str,
    payload: RoundStartRequest,
    current_user: CurrentUser,
    session: DbSession,
    response: Response,
) -> RoundDetail:
    detail, created = round_service.start_round(
        session, current_user, bank_id, restart=payload.restart
    )
    response.status_code = 201 if created else 200
    return detail


@router.get("/banks/{bank_id}/rounds", response_model=list[RoundSummary])
def list_rounds(
    bank_id: str, current_user: CurrentUser, session: DbSession
) -> list[RoundSummary]:
    return round_service.list_rounds(session, current_user, bank_id)


@router.get("/rounds/{round_id}", response_model=RoundDetail)
def get_round(round_id: str, current_user: CurrentUser, session: DbSession) -> RoundDetail:
    return round_service.get_round_detail(session, current_user, round_id)


@router.post("/rounds/{round_id}/reveal", response_model=RoundItemOut)
def reveal_answer(
    round_id: str, current_user: CurrentUser, session: DbSession
) -> RoundItemOut:
    return round_service.reveal_answer(session, current_user, round_id)


@router.post("/rounds/{round_id}/advance", response_model=RoundDetail)
def advance_round(
    round_id: str,
    payload: AdvanceRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> RoundDetail:
    return round_service.advance_round(session, current_user, round_id, payload)


@router.post("/rounds/{round_id}/abandon", response_model=AbandonResponse)
def abandon_round(
    round_id: str, current_user: CurrentUser, session: DbSession
) -> AbandonResponse:
    round_obj = round_service.abandon_round(session, current_user, round_id)
    return AbandonResponse(
        id=round_obj.id,
        status=round_obj.status,  # type: ignore[arg-type]
        round_number=round_obj.round_number,
    )
