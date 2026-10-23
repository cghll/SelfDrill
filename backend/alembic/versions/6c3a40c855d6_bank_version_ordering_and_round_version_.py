"""bank version ordering and round version cascade

Revision ID: 6c3a40c855d6
Revises: 8399331fc22b
Create Date: 2026-10-10 02:13:44.271994

变更内容：
1. `question_revisions.order_index`：题目在源文档中的次序，题目列表和稳定分页需要
   一个与时间戳无关的确定性排序键。
2. `rounds.bank_version_id` 外键加上 ON DELETE CASCADE：删除题库时版本会被级联删除，
   若轮次仍引用这些版本，SQLite 会因外键约束拒绝整库删除。

SQLite 不支持 ALTER CONSTRAINT，且初版迁移创建的外键没有名字，
因此 batch 模式需要传入命名约定，让反射出来的外键有稳定名字后才能 drop。
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "6c3a40c855d6"
down_revision: str | None = "8399331fc22b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK_ROUNDS_BANK_VERSION = "fk_rounds_bank_version_id_bank_versions"

_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def upgrade() -> None:
    with op.batch_alter_table("question_revisions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("order_index", sa.Integer(), nullable=False, server_default="0")
        )

    with op.batch_alter_table(
        "rounds", schema=None, naming_convention=_NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(_FK_ROUNDS_BANK_VERSION, type_="foreignkey")
        batch_op.create_foreign_key(
            _FK_ROUNDS_BANK_VERSION,
            "bank_versions",
            ["bank_version_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    with op.batch_alter_table(
        "rounds", schema=None, naming_convention=_NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(_FK_ROUNDS_BANK_VERSION, type_="foreignkey")
        batch_op.create_foreign_key(
            _FK_ROUNDS_BANK_VERSION,
            "bank_versions",
            ["bank_version_id"],
            ["id"],
        )

    with op.batch_alter_table("question_revisions", schema=None) as batch_op:
        batch_op.drop_column("order_index")
