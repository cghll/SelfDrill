# SelfDrill 后端镜像
# 依赖先复制再复制代码，保证只改代码时不会重复安装依赖。

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 编译 argon2-cffi 的依赖；安装完运行期依赖后即可移除，减小镜像体积
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts

# 以非 root 运行；数据目录在 compose 里挂载为持久化卷
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/uploads /data/backups \
    && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 8000

# /auth/me 未登录会返回 401，对健康检查来说同样是「服务已就绪」
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "scripts/healthcheck.py"]

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
