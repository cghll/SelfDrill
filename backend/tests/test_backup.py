"""阶段 9：备份工具测试。

备份是「唯一能救命」的功能，必须验证快照真的完整可读，而不只是文件存在。
"""

from __future__ import annotations

import sqlite3
import tarfile
from pathlib import Path

import pytest

from scripts.backup import BACKUP_PREFIX, make_backup, prune, sqlite_path


def test_relative_sqlite_url() -> None:
    assert sqlite_path("sqlite:///./data/app.db") == Path("./data/app.db")
    assert sqlite_path("sqlite:///app.db") == Path("app.db")


def test_absolute_sqlite_url() -> None:
    assert sqlite_path("sqlite:////data/app.db") == Path("/data/app.db")


def test_non_sqlite_url_is_rejected() -> None:
    with pytest.raises(SystemExit):
        sqlite_path("postgresql://user:pw@host/db")


def _seed_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("create table users (id text primary key, username text)")
        connection.execute("insert into users values ('u1', 'owner')")
        connection.commit()
    finally:
        connection.close()


def test_backup_snapshot_is_readable(tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    _seed_database(db)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "abc.md").write_text("# 题目", encoding="utf-8")
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    target = make_backup(db, uploads, backup_dir, timestamp="20260101T000000Z")

    assert target.name == f"{BACKUP_PREFIX}20260101T000000Z"
    snapshot = target / "app.db"
    assert snapshot.exists()

    connection = sqlite3.connect(snapshot)
    try:
        assert connection.execute("pragma integrity_check").fetchone()[0] == "ok"
        assert connection.execute("select username from users").fetchone()[0] == "owner"
    finally:
        connection.close()

    # 上传目录被打包，且内容完整
    archive = target / "uploads.tar.gz"
    assert archive.exists()
    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()
    assert "uploads/abc.md" in names


def test_backup_includes_committed_wal_data(tmp_path: Path) -> None:
    """WAL 模式下已提交但未 checkpoint 的数据也必须进入快照。"""
    db = tmp_path / "wal.db"
    connection = sqlite3.connect(db)
    try:
        connection.execute("pragma journal_mode=WAL")
        connection.execute("create table t (v text)")
        connection.execute("insert into t values ('committed-in-wal')")
        connection.commit()
        # 故意不做 checkpoint，模拟「刚写完就备份」的常见场景
        assert (tmp_path / "wal.db-wal").exists()

        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        target = make_backup(db, tmp_path / "uploads", backup_dir, timestamp="20260101T000000Z")

        snapshot = sqlite3.connect(target / "app.db")
        try:
            rows = snapshot.execute("select v from t").fetchall()
        finally:
            snapshot.close()
    finally:
        connection.close()

    assert rows == [("committed-in-wal",)]


def test_missing_database_does_not_crash(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    target = make_backup(tmp_path / "nope.db", tmp_path / "uploads", backup_dir)
    assert target.exists()
    assert not (target / "app.db").exists()


def test_prune_keeps_newest(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    for day in range(1, 6):
        (backup_dir / f"{BACKUP_PREFIX}2026010{day}T000000Z").mkdir()

    prune(backup_dir, 2)

    remaining = sorted(path.name for path in backup_dir.iterdir())
    assert remaining == [
        f"{BACKUP_PREFIX}20260104T000000Z",
        f"{BACKUP_PREFIX}20260105T000000Z",
    ]


def test_prune_ignores_unrelated_directories(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    (backup_dir / "手动备份").mkdir()
    (backup_dir / f"{BACKUP_PREFIX}20260101T000000Z").mkdir()

    prune(backup_dir, 1)

    assert (backup_dir / "手动备份").exists()


def test_prune_with_zero_keeps_everything(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    for day in range(1, 4):
        (backup_dir / f"{BACKUP_PREFIX}2026010{day}T000000Z").mkdir()

    prune(backup_dir, 0)

    assert len(list(backup_dir.iterdir())) == 3