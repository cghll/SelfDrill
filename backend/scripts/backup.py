"""数据库与上传文件备份。

使用 SQLite 的在线备份 API（`Connection.backup`）而不是直接复制文件：
数据库运行在 WAL 模式下，直接复制 `.db` 可能丢掉还在 `-wal` 里的已提交事务。
在线备份由 SQLite 自己保证一致性，不需要停服。

用法：
    python scripts/backup.py                  # 备份一次
    python scripts/backup.py --loop           # 常驻，按间隔反复备份
    python scripts/backup.py --keep 14        # 保留最近 14 份

环境变量：
    DATABASE_URL        数据库地址（默认取应用配置）
    UPLOAD_DIR          上传目录（默认取应用配置）
    BACKUP_DIR          备份输出目录（默认取应用配置）
    BACKUP_KEEP         保留份数，默认 7
    BACKUP_INTERVAL_SECONDS  常驻模式下的间隔秒数，默认 86400
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sqlite3
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("selfdrill.backup")

BACKUP_PREFIX = "selfdrill-backup-"


def sqlite_path(database_url: str) -> Path:
    """从 SQLAlchemy URL 解析出 SQLite 文件路径。"""
    if not database_url.startswith("sqlite:"):
        raise SystemExit(f"只支持 SQLite 备份，当前 DATABASE_URL={database_url}")
    # sqlite:///relative/path.db  或  sqlite:////absolute/path.db
    raw = database_url.split("sqlite:", 1)[1].lstrip("/")
    if database_url.startswith("sqlite:////"):
        return Path("/" + raw)
    return Path(raw)


def make_backup(
    db_path: Path,
    upload_dir: Path,
    backup_dir: Path,
    *,
    timestamp: str | None = None,
) -> Path:
    stamp = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"{BACKUP_PREFIX}{stamp}"
    target.mkdir(parents=True, exist_ok=True)

    # 1. 数据库：在线备份，保证事务一致
    if db_path.exists():
        destination = target / "app.db"
        source = sqlite3.connect(str(db_path))
        try:
            sink = sqlite3.connect(str(destination))
            try:
                source.backup(sink)
            finally:
                sink.close()
        finally:
            source.close()
        logger.info("已备份数据库 -> %s（%d 字节）", destination, destination.stat().st_size)
    else:
        logger.warning("数据库文件不存在，跳过：%s", db_path)

    # 2. 上传目录：打包压缩
    if upload_dir.exists() and any(upload_dir.iterdir()):
        archive = target / "uploads.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(upload_dir, arcname="uploads")
        logger.info("已备份上传目录 -> %s", archive)
    else:
        logger.info("上传目录为空，跳过打包")

    return target


def prune(backup_dir: Path, keep: int) -> None:
    """只保留最近 keep 份备份。"""
    if keep <= 0:
        return
    entries = sorted(
        (path for path in backup_dir.iterdir() if path.is_dir() and path.name.startswith(BACKUP_PREFIX)),
        key=lambda path: path.name,
        reverse=True,
    )
    for stale in entries[keep:]:
        shutil.rmtree(stale, ignore_errors=True)
        logger.info("已清理旧备份：%s", stale.name)


def run_once(keep: int) -> None:
    from app.config import get_settings

    settings = get_settings()
    db_path = sqlite_path(settings.database_url)
    backup_dir = settings.backup_path
    backup_dir.mkdir(parents=True, exist_ok=True)

    make_backup(db_path, settings.upload_path, backup_dir)
    prune(backup_dir, keep)


def main() -> int:
    parser = argparse.ArgumentParser(description="SelfDrill 备份工具")
    parser.add_argument("--loop", action="store_true", help="常驻模式，按间隔反复备份")
    parser.add_argument(
        "--keep",
        type=int,
        default=int(os.environ.get("BACKUP_KEEP", "7")),
        help="保留最近多少份备份（默认 7）",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.environ.get("BACKUP_INTERVAL_SECONDS", "86400")),
        help="常驻模式的备份间隔秒数（默认 86400）",
    )
    args = parser.parse_args()

    if not args.loop:
        run_once(args.keep)
        return 0

    logger.info("备份服务已启动：每 %d 秒备份一次，保留最近 %d 份", args.interval, args.keep)
    while True:
        try:
            run_once(args.keep)
        except Exception:  # pragma: no cover - 备份失败不能中断常驻进程
            logger.exception("本次备份失败，将在下个周期重试")
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
