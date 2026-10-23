"""认证业务逻辑：账号初始化、登录校验。"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.schemas import UserOut
from app.common.errors import UnauthenticatedError
from app.common.security import hash_password, needs_rehash, verify_password
from app.config import Settings, get_settings
from app.db.models import User

logger = logging.getLogger(__name__)


def get_user_by_username(session: Session, username: str) -> User | None:
    return session.execute(
        select(User).where(func.lower(User.username) == username.strip().lower())
    ).scalar_one_or_none()


def get_user_by_id(session: Session, user_id: str) -> User | None:
    return session.get(User, user_id)


def count_users(session: Session) -> int:
    return int(session.execute(select(func.count()).select_from(User)).scalar_one())


def ensure_initial_user(session: Session, settings: Settings | None = None) -> User | None:
    """按部署配置初始化唯一个人账号（FR-001：不开放注册）。

    只在库中没有任何用户时创建，避免覆盖已有账号。
    """
    settings = settings or get_settings()
    if count_users(session) > 0:
        return None
    password = settings.initial_password
    if not password:
        logger.warning(
            "未配置 INITIAL_PASSWORD，未创建初始账号；可通过 /api/v1/auth/login 无法登录，"
            "请设置 INITIAL_USERNAME / INITIAL_PASSWORD 后重启。"
        )
        return None
    user = User(username=settings.initial_username, password_hash=hash_password(password))
    session.add(user)
    session.commit()
    logger.info("已创建初始账号：%s", settings.initial_username)
    return user


def authenticate(session: Session, username: str, password: str) -> User:
    """校验账号密码。

    用户不存在与密码错误返回同一个错误，避免账号枚举。
    """
    user = get_user_by_username(session, username)
    if user is None or not verify_password(password, user.password_hash):
        raise UnauthenticatedError("用户名或密码不正确")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        session.commit()
    return user


def to_user_out(user: User) -> UserOut:
    return UserOut(id=user.id, username=user.username, created_at=user.created_at)
