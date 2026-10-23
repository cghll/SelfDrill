"""阶段 2：迁移与模型一致性测试。

模型和迁移很容易漂移，这里用 Alembic 自己的比较器把两者对账，
避免出现「测试用 create_all 通过、生产用迁移却缺列」的情况。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect

BACKEND_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture()
def migrated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    db_path = tmp_path / "migrated.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("APP_SECRET_KEY", "migration-test-key")
    monkeypatch.setenv("APP_ENV", "test")

    from app.config import reset_settings_cache

    reset_settings_cache()

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(config, "head")
    yield url
    reset_settings_cache()


def test_migrations_create_all_model_tables(migrated_db: str) -> None:
    from app.db.models import Base

    engine = create_engine(migrated_db)
    try:
        tables = set(inspect(engine).get_table_names())
        assert set(Base.metadata.tables).issubset(tables)
        assert "alembic_version" in tables
    finally:
        engine.dispose()


def test_no_pending_model_changes_after_migrate(migrated_db: str) -> None:
    """迁移后的库结构必须与模型定义完全一致。"""
    from app.db.models import Base

    engine = create_engine(migrated_db)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={"compare_type": True, "compare_server_default": False},
            )
            diff = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()

    # order_index 的 server_default 是迁移专用，不计入模型差异
    meaningful = [
        entry
        for entry in diff
        if "server_default" not in str(entry)
    ]
    assert meaningful == [], f"模型与迁移不一致：{meaningful}"


def test_downgrade_and_upgrade_are_reversible(migrated_db: str) -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = create_engine(migrated_db)
    try:
        tables = set(inspect(engine).get_table_names())
        assert "rounds" in tables and "round_items" in tables
    finally:
        engine.dispose()
