"""密码哈希与会话签名。

- 密码：Argon2id（argon2-cffi 默认即为 Argon2id）。
- 会话：itsdangerous 签名 token 放入 HttpOnly Cookie，服务端不存会话表。
"""

from __future__ import annotations

from datetime import datetime, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import get_settings

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    except Exception:  # pragma: no cover - 防御性兜底，避免异常泄漏到接口层
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return False


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        secret_key=get_settings().resolved_secret_key(),
        salt="selfdrill.session",
    )


def create_session_token(user_id: str, username: str) -> str:
    return _serializer().dumps({"uid": user_id, "usr": username})


def load_session_token(token: str) -> dict[str, str] | None:
    """校验签名与有效期，失败返回 None（不抛异常，由调用方转 401）。"""
    settings = get_settings()
    try:
        payload = _serializer().loads(token, max_age=settings.session_max_age)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(payload, dict) or "uid" not in payload:
        return None
    return {"uid": str(payload["uid"]), "usr": str(payload.get("usr", ""))}


def session_expires_at() -> datetime:
    """会话绝对过期时间，供前端展示或调试。"""
    from datetime import timedelta

    return datetime.now(timezone.utc) + timedelta(seconds=get_settings().session_max_age)
