"""SQLAlchemy 数据模型。

对应 docs/02 第 6 节的 8 张表，外加一张用于 advance 幂等的辅助表。

约定：
- 主键统一 UUID 字符串（String(36)）。
- 时间统一 naive UTC（见 app.common.timeutil）。
- `question_banks.current_version_id` 不建外键：SQLite 不支持 ALTER TABLE ADD
  CONSTRAINT，而 bank ↔ version 互为引用会形成循环依赖。归属校验由 service 保证。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.common.timeutil import utcnow


class Base(DeclarativeBase):
    pass


def new_uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class QuestionBank(Base):
    __tablename__ = "question_banks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class BankVersion(Base):
    __tablename__ = "bank_versions"
    __table_args__ = (
        UniqueConstraint("bank_id", "version_number", name="uq_bank_version_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    bank_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("question_banks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class Question(Base):
    """稳定题目身份：跨版本不变，标题改名不会新建身份。"""

    __tablename__ = "questions"
    __table_args__ = (Index("ix_questions_bank_stable_key", "bank_id", "stable_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    bank_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("question_banks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stable_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class QuestionRevision(Base):
    """某题在某一次导入中的内容快照。"""

    __tablename__ = "question_revisions"
    __table_args__ = (
        UniqueConstraint(
            "bank_version_id", "question_id", name="uq_revision_version_question"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    question_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bank_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("bank_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    answer_markdown: Mapped[str] = mapped_column(Text, default="", nullable=False)
    heading_level: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    section_path: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_anchor: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    # 该题在源文档中的出现次序。docs/02 未列出，但题目列表与稳定分页都需要一个
    # 与时间戳无关的确定性排序键，因此显式保存。
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class ImportPreview(Base):
    __tablename__ = "import_previews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bank_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("question_banks.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parsed_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    diff_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class Round(Base):
    __tablename__ = "rounds"
    __table_args__ = (UniqueConstraint("bank_id", "round_number", name="uq_round_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    bank_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("question_banks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bank_version_id: Mapped[str] = mapped_column(
        String(36),
        # 版本通常只被标记为 superseded 而不会删除；一旦删除（例如整库删除的级联），
        # 引用它的轮次必须一并清理，否则会留下外键悬空。
        ForeignKey("bank_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="in_progress", nullable=False, index=True
    )
    current_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    progress_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    items: Mapped[list["RoundItem"]] = relationship(
        back_populates="round",
        cascade="all, delete-orphan",
        order_by="RoundItem.position",
    )


class RoundItem(Base):
    __tablename__ = "round_items"
    __table_args__ = (
        UniqueConstraint("round_id", "position", name="uq_round_item_position"),
        UniqueConstraint(
            "round_id", "question_revision_id", name="uq_round_item_revision"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    round_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_revision_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("question_revisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    answer_revealed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    revealed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    presented_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    round: Mapped[Round] = relationship(back_populates="items")
    revision: Mapped[QuestionRevision] = relationship(lazy="joined")


class RoundAdvanceRequest(Base):
    """`advance` 幂等记录：同一个 idempotency_key 重放不会多推进一次。"""

    __tablename__ = "round_advance_requests"
    __table_args__ = (
        UniqueConstraint(
            "round_id", "idempotency_key", name="uq_advance_request_key"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    round_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    result_progress_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
