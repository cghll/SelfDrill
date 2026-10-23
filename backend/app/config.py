"""应用配置。

所有可调参数集中在这里，通过环境变量或 `.env` 覆盖。
生产环境缺失密钥会直接启动失败，避免用临时密钥跑线上。
"""

from __future__ import annotations

import secrets
import warnings
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 目录，用于把默认路径固定下来，避免依赖启动时的工作目录
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- 运行环境 ---
    app_env: str = "development"
    app_secret_key: str | None = None

    # --- 数据库与文件 ---
    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'app.db').as_posix()}"
    upload_dir: str = str(BASE_DIR / "data" / "uploads")
    backup_dir: str = str(BASE_DIR / "data" / "backups")

    # --- 上传限制（FR-003）---
    max_upload_size: int = 10 * 1024 * 1024
    max_upload_lines: int = 200_000
    max_parse_seconds: float = 20.0

    # --- 会话 ---
    session_cookie_name: str = "selfdrill_session"
    session_cookie_secure: bool = False
    session_max_age: int = 60 * 60 * 24 * 30  # 30 天

    # --- 导入预览 ---
    preview_ttl_seconds: int = 60 * 60 * 6  # 6 小时

    # --- 初始化账号（FR-001：不开放注册）---
    initial_username: str = "owner"
    initial_password: str | None = None

    # --- 前端跨域（开发环境）---
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def upload_path(self) -> Path:
        return Path(self.upload_dir)

    @property
    def backup_path(self) -> Path:
        return Path(self.backup_dir)

    def resolved_secret_key(self) -> str:
        """返回可用于签名的密钥。

        生产环境必须显式配置；开发环境缺失时生成临时密钥并告警，
        这样本地启动不需要额外准备文件，但重启会让旧会话失效。
        """
        if self.app_secret_key:
            return self.app_secret_key
        if self.is_production:
            raise RuntimeError(
                "生产环境必须配置 APP_SECRET_KEY，拒绝使用临时密钥启动"
            )
        warnings.warn(
            "APP_SECRET_KEY 未配置，已生成临时密钥；重启后现有会话将失效。",
            RuntimeWarning,
            stacklevel=2,
        )
        self.app_secret_key = secrets.token_urlsafe(48)
        return self.app_secret_key

    def ensure_directories(self) -> None:
        self.upload_path.mkdir(parents=True, exist_ok=True)
        self.backup_path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """测试在修改环境变量后调用，强制重新读取配置。"""
    get_settings.cache_clear()
