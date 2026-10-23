"""认证相关请求/响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.common.timeutil import UtcDateTime


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    id: str
    username: str
    created_at: UtcDateTime


class LoginResponse(BaseModel):
    user: UserOut
