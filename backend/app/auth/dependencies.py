"""FastAPI 依赖：从 Cookie 解析当前用户。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.auth import service as auth_service
from app.common.errors import UnauthenticatedError
from app.common.security import load_session_token
from app.config import get_settings
from app.db.models import User
from app.db.session import get_db


def get_current_user(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
) -> User:
    cookie_name = get_settings().session_cookie_name
    token = request.cookies.get(cookie_name)
    if not token:
        raise UnauthenticatedError()
    payload = load_session_token(token)
    if payload is None:
        raise UnauthenticatedError()
    user = auth_service.get_user_by_id(session, payload["uid"])
    if user is None:
        raise UnauthenticatedError()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[Session, Depends(get_db)]
