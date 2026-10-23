"""时间与序列化工具。

SQLite 不保留时区信息，因此统一以「naive UTC」落库，出参时补回 `Z` 后缀，
保证前后端看到的都是标准 ISO 8601 UTC 时间。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from pydantic import PlainSerializer


def utcnow() -> datetime:
    """当前 UTC 时间（naive，用于落库）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_iso_z(value: datetime | None) -> str | None:
    """把库中的 naive UTC 时间序列化成 `...Z`。"""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


UtcDateTime = Annotated[datetime, PlainSerializer(to_iso_z, return_type=str)]
