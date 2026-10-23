# SelfDrill 部署说明

## 架构

```
浏览器
  │ HTTPS
  ▼
web (Caddy)          静态文件 + /api 反向代理 + 自动 HTTPS
  │ 内部网络
  ▼
api (FastAPI)        业务逻辑、Markdown 解析、轮次生成
  │
  ▼
selfdrill-data 卷    app.db（SQLite，WAL） + uploads/ + backups/

backup (同一镜像)    每日用 SQLite 在线备份 API 做一致性快照，保留最近 7 份
```

API 容器**不映射端口**，只在内网可达；唯一入口是 Caddy（docs/02 第 8 节）。

## 快速开始

```bash
cd deploy
cp .env.example .env
# 填写 APP_SECRET_KEY 与 INITIAL_PASSWORD
python -c "import secrets; print(secrets.token_urlsafe(48))"

docker compose up -d --build
docker compose logs -f api
```

访问 `http://<服务器地址>/`，用 `INITIAL_USERNAME` / `INITIAL_PASSWORD` 登录。

首次启动时 `alembic upgrade head` 会自动执行，随后创建初始账号。
账号只在库中没有任何用户时创建，之后修改环境变量不会覆盖已有密码。

## 启用 HTTPS

1. 把域名解析到服务器。
2. 在 `deploy/.env` 里设置：

```
SITE_ADDRESS=selfdrill.example.com
SESSION_COOKIE_SECURE=true
```

3. `docker compose up -d`。Caddy 会自动申请并续期 Let's Encrypt 证书。

80 端口需要保持可达，用于 ACME 的 HTTP-01 校验。

## 数据与备份

持久化内容全部在 `selfdrill-data` 卷：

| 路径 | 内容 |
| --- | --- |
| `/data/app.db` | SQLite 数据库（WAL 模式） |
| `/data/uploads/` | 按 SHA-256 命名的原始 Markdown 文件 |
| `/data/backups/` | 备份快照，每份含 `app.db` 与 `uploads.tar.gz` |

`backup` 服务默认每 24 小时备份一次，保留最近 7 份（`BACKUP_KEEP` / `BACKUP_INTERVAL_SECONDS` 可调）。

手动备份：

```bash
docker compose exec backup python scripts/backup.py
docker compose exec backup python scripts/backup.py --keep 14
```

为什么不用 `cp app.db`：数据库运行在 WAL 模式下，已提交但尚未 checkpoint
的事务还在 `-wal` 文件里，直接复制 `.db` 会丢掉这部分数据。
`scripts/backup.py` 使用 SQLite 的在线备份 API，由数据库自身保证快照一致。

上传目录按内容哈希命名，重复导入同一个文件不会产生副本。删除题库时不会
连带删除这些原始文件：同一个文件可能被多个题库引用，做引用计数得不偿失。
它们是纯文本 Markdown，体积很小；如果确实需要清理，可以在确认没有任何
`bank_versions.source_hash` 引用后手动删除。

从备份恢复：

```bash
docker compose down
docker run --rm -v selfdrill-data:/data -v "$PWD/backups:/in" alpine \
  sh -c "cp /in/<快照目录>/app.db /data/app.db && rm -f /data/app.db-wal /data/app.db-shm"
docker compose up -d
```

## 升级

```bash
# 1. 先备份
docker compose exec backup python scripts/backup.py

# 2. 更新代码后重建
docker compose up -d --build

# 3. 确认迁移与健康状态
docker compose exec api alembic current
docker compose ps
```

`api` 容器启动时会自动执行 `alembic upgrade head`；迁移失败会阻止容器启动，
旧版本仍可通过回滚镜像恢复（数据库备份在手）。

### 改代码后必须重建镜像

前后端都是**构建期**打进镜像的，`docker compose restart` 不会让代码改动生效：

- `frontend/` 由 `pnpm run build` 产出静态文件，再 `COPY` 进 Caddy 镜像；
- `backend/` 的源码在镜像构建时复制进镜像，容器内没有挂载宿主目录。

所以更新代码后一律用 `docker compose up -d --build`（或先 `docker compose build`）。
判断线上跑的是哪一版，可以对比宿主源码与镜像内容：

```bash
docker compose exec api python -c "import app.main as m; print(m.__file__)"
docker compose images
```

## 运维检查

```bash
# 健康状态
docker compose ps

# 接口日志（不含密码与会话值）
docker compose logs -f api

# 数据库体积与题目数
docker compose exec api python -c "
import sqlite3
c = sqlite3.connect('/data/app.db')
print('questions:', c.execute('select count(*) from questions').fetchone()[0])
print('revisions:', c.execute('select count(*) from question_revisions').fetchone()[0])
"
```

## 安全清单

- [ ] `APP_SECRET_KEY` 是随机长密钥，且没有提交到版本库
- [ ] `INITIAL_PASSWORD` 是强密码，首次登录后即可从 `.env` 中移除
- [ ] 使用 HTTPS 时 `SESSION_COOKIE_SECURE=true`
- [ ] API 容器没有映射到公网端口
- [ ] `deploy/.env` 权限受限（`chmod 600`）
- [ ] 定期验证备份可恢复，而不只是「存在」

## 不使用 Docker 的部署

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # 填 APP_SECRET_KEY / INITIAL_PASSWORD

alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

前端：

```bash
cd frontend
pnpm install
pnpm build                  # 产物在 dist/，交给 Nginx/Caddy 托管
```

用反向代理把 `/api` 转发到 `127.0.0.1:8000`，静态文件指向 `frontend/dist`，
其余路径回退到 `index.html`。