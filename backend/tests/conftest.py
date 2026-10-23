"""pytest 公共夹具：每个测试使用独立临时数据库与配置。"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def settings_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """把配置指向临时目录，避免污染开发数据库。"""
    data_dir = tmp_path / "data"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-key-do-not-use-in-production")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(data_dir / 'test.db').as_posix()}")
    monkeypatch.setenv("UPLOAD_DIR", str(data_dir / "uploads"))
    monkeypatch.setenv("BACKUP_DIR", str(data_dir / "backups"))
    monkeypatch.setenv("INITIAL_USERNAME", "owner")
    monkeypatch.setenv("INITIAL_PASSWORD", "test-password")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    data_dir.mkdir(parents=True, exist_ok=True)

    from app.config import reset_settings_cache

    reset_settings_cache()
    yield data_dir
    reset_settings_cache()


@pytest.fixture()
def app_module(settings_env: Path):
    """在隔离配置下重新构建应用与数据库引擎。"""
    from app.db import session as db_session

    db_session.reset_engine()
    from app import main as main_module

    importlib.reload(main_module)
    # 不使用 TestClient 的测试也要有可用表结构
    db_session.init_db()
    yield main_module
    db_session.reset_engine()


@pytest.fixture()
def client(app_module) -> Iterator[TestClient]:
    with TestClient(app_module.app) as test_client:
        yield test_client


@pytest.fixture()
def db_session_factory(app_module):
    from app.db.session import get_session_factory

    return get_session_factory()


@pytest.fixture()
def auth_client(client: TestClient) -> TestClient:
    """已登录的客户端。"""
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "owner", "password": "test-password"},
    )
    assert response.status_code == 200, response.text
    return client
