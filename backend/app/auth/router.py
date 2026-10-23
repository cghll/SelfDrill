"""认证接口（docs/03 第 3 节）。"""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.auth import service as auth_service
from app.auth.dependencies import CurrentUser, DbSession
from app.auth.schemas import LoginRequest, LoginResponse, UserOut
from app.common.security import create_session_token
from app.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, response: Response, session: DbSession) -> LoginResponse:
    user = auth_service.authenticate(session, payload.username, payload.password)
    settings = get_settings()
    token = create_session_token(user.id, user.username)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_max_age,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return LoginResponse(user=auth_service.to_user_out(user))


@router.post("/logout", status_code=204)
def logout(response: Response) -> Response:
    settings = get_settings()
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
    )
    response.status_code = 204
    return response


@router.get("/me", response_model=UserOut)
def me(current_user: CurrentUser) -> UserOut:
    return auth_service.to_user_out(current_user)
