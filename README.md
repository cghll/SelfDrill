<div align="center">

# SelfDrill

**把整理好的 Markdown 面试文档，变成一个会考你的题库**

按轮次随机且不重复地抽题，答案默认隐藏、想好了再手动查看；
进度存在服务端，手机上刷一半，换电脑接着刷。

[![License][badge-license]](LICENSE)
[![Python][badge-python]](https://www.python.org/)
[![FastAPI][badge-fastapi]](https://fastapi.tiangolo.com/)
[![Vue][badge-vue]](https://vuejs.org/)
[![TypeScript][badge-ts]](https://www.typescriptlang.org/)
[![SQLite][badge-sqlite]](https://www.sqlite.org/)
[![Docker][badge-docker]](deploy/docker-compose.yml)

[![Tests][badge-tests]](#测试)
[![Style][badge-style]](backend/pyproject.toml)
[![Status][badge-status]](#开发阶段)

[它解决什么](#它解决什么) · [功能](#功能) · [技术栈](#技术栈) · [本地开发](#本地开发) · [部署](#部署) · [配置项](#配置项) · [设计约束](#设计约束)

</div>

> **定位**：这是**单人自用**的工具，不是面向多用户的产品。
> 没有注册入口、没有多租户、没有分享与协作——整个实例只服务一个人，用来反复抽查自己
> 「到底记没记住」。所有取舍都围绕这个前提：够用、好维护、数据在自己手里。

---

## 它解决什么

面试复习的痛点不是「没有资料」，而是**资料看过了，但不知道自己会不会**。把整理好的
Markdown 文档丢进来，它负责三件事：

| | 它做什么 | 为什么这么做 |
| :--: | --- | --- |
| 1 | **洗牌出题** | 一轮里把整个题库随机打乱，每题恰好出现一次，不重复、不遗漏。顺序由服务端生成并落库，刷新页面、换设备都不会变。 |
| 2 | **先想后看** | 答案默认不返回给前端（不是靠 CSS 藏起来），回忆完再点「查看答案」，看完可以收起，继续想。 |
| 3 | **记录进度** | 当前第几题、哪道题看过答案都存在服务端，中断了随时回来接着刷。 |

## 功能

- **Markdown 题库导入**：上传 `.md` 文档，自动识别标题层级、切分题目、按章节归类。
- **导入预览与确认**：解析结果先预览再落库，新增 / 修改 / 删除逐条可见；
  改名、拆题、合题这类有歧义的判断**一律不自动处理**，必须人工确认。
- **题库版本**：每次确认导入生成一个新版本，旧版本保留；进行中的轮次固定使用创建时的版本，
  新版本从下一轮开始生效。
- **随机轮次**：无放回随机排列，支持继续当前轮次 / 放弃后重开 / 一轮结束后直接开下一轮。
- **答案查看**：Markdown 渲染，支持代码块、列表、表格、图片链接；渲染结果经过 HTML 白名单清洗。
- **并发安全**：多个设备同时推进时以 `progress_version` 做乐观锁，冲突时提示并同步到最新位置，
  不静默跳题。
- **每日备份**：容器内定时用 SQLite 在线备份 API 做一致性快照，保留最近 7 份。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 后端 | Python 3.12+ / FastAPI / SQLAlchemy 2 / Alembic |
| 数据库 | SQLite（WAL 模式） |
| Markdown 解析 | markdown-it-py |
| 密码与会话 | Argon2id + 签名 Cookie |
| 前端 | Vue 3 + TypeScript + Vite + Pinia + Vue Router |
| 答案渲染 | markdown-it + DOMPurify 白名单清洗 |
| 测试 | pytest + HTTPX / Vitest + @vue/test-utils |
| 部署 | Docker Compose + Caddy |

## 目录结构

```
backend/     FastAPI 应用
  app/       auth / banks / imports / rounds / common / db 分模块组织
  tests/     领域逻辑 + 接口 + 端到端测试
  alembic/   数据库迁移
  scripts/   备份、健康检查、真实 HTTP 端到端验证
frontend/    Vue 3 单页应用（src/views 页面、src/stores 状态、src/api 客户端）
deploy/      Docker Compose、Caddy 配置、部署与运维说明
docs/        需求、架构、接口、导入规则文档（仅本地保留，未纳入版本控制）
```

## 本地开发

### 后端

```bash
cd backend
python -m venv ../.venv
../.venv/Scripts/activate          # Windows
# source ../.venv/bin/activate     # macOS / Linux
pip install -r requirements-dev.txt

cp .env.example .env               # 填 INITIAL_PASSWORD，APP_SECRET_KEY 开发环境可留空
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

接口文档：<http://127.0.0.1:8000/api/docs>

首次启动时如果库里没有任何用户，会用 `INITIAL_USERNAME` / `INITIAL_PASSWORD` 创建一个账号。
**没有注册接口**，之后改环境变量也不会覆盖已有密码。

### 前端

```bash
cd frontend
pnpm install
pnpm dev                           # http://127.0.0.1:5173，/api 自动代理到 8000
```

### 测试

```bash
cd backend
python -m pytest                   # 领域逻辑 + 接口 + 端到端
python scripts/live_e2e.py http://127.0.0.1:8000   # 真实 HTTP 端到端（需先启动服务）

cd frontend
pnpm test                          # Vitest
pnpm typecheck                     # vue-tsc
pnpm build                         # 类型检查 + 生产构建
```

## 部署

完整说明见 [deploy/README.md](deploy/README.md)，下面是主流程。

### 架构

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

backup (复用 api 镜像)  每日一致性快照，保留最近 7 份
```

API 容器**不映射到公网端口**，只在内网可达；唯一入口是 Caddy。

### 快速开始

```bash
cd deploy
cp .env.example .env
# 填 APP_SECRET_KEY 与 INITIAL_PASSWORD，密钥生成方式：
python -c "import secrets; print(secrets.token_urlsafe(48))"

sudo docker compose up -d --build
sudo docker compose ps
```

访问 `http://<服务器地址>/`，用 `INITIAL_USERNAME` / `INITIAL_PASSWORD` 登录。
`api` 容器启动时会自动执行 `alembic upgrade head`，迁移失败会阻止容器启动。

### 启用 HTTPS

1. 把域名解析到服务器。
2. 在 `deploy/.env` 里设置：

   ```
   SITE_ADDRESS=selfdrill.example.com
   SESSION_COOKIE_SECURE=true
   ```

3. `sudo docker compose up -d`。Caddy 会自动申请并续期 Let's Encrypt 证书。

80 端口需要保持可达，用于 ACME 的 HTTP-01 校验。

### 数据与备份

持久化内容全部在 `selfdrill-data` 卷：

| 路径 | 内容 |
| --- | --- |
| `/data/app.db` | SQLite 数据库（WAL 模式） |
| `/data/uploads/` | 按 SHA-256 命名的原始 Markdown 文件 |
| `/data/backups/` | 备份快照，每份含 `app.db` 与 `uploads.tar.gz` |

手动备份 / 恢复：

```bash
# 立刻备份一份（默认保留 7 份，可加 --keep 14）
sudo docker compose exec backup python scripts/backup.py

# 从快照恢复
sudo docker compose down
sudo docker run --rm -v selfdrill-data:/data -v "$PWD/backups:/in" alpine \
  sh -c "cp /in/<快照目录>/app.db /data/app.db && rm -f /data/app.db-wal /data/app.db-shm"
sudo docker compose up -d
```

**为什么不能 `cp app.db`**：数据库跑在 WAL 模式下，已提交但尚未 checkpoint 的事务还在
`-wal` 文件里，直接复制 `.db` 会丢这部分数据。`scripts/backup.py` 用的是 SQLite 在线备份
API，由数据库自己保证快照一致。

### 升级

```bash
# 1. 先备份
sudo docker compose exec backup python scripts/backup.py

# 2. 更新代码后重建（前端是构建期产物，必须 --build，restart 不生效）
sudo docker compose up -d --build

# 3. 确认迁移与健康状态
sudo docker compose exec api alembic current
sudo docker compose ps
```

> **注意**：前端在镜像构建阶段由 `pnpm run build` 打成静态文件塞进 Caddy 镜像，
> 所以改了 `frontend/` 下的代码**只重启容器不会生效**，一定要带 `--build`。

### 不用 Docker

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env               # 填 APP_SECRET_KEY / INITIAL_PASSWORD

alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
cd frontend
pnpm install
pnpm build                         # 产物在 dist/，交给 Nginx / Caddy 托管
```

用反向代理把 `/api` 转发到 `127.0.0.1:8000`，静态文件指向 `frontend/dist`，
其余路径回退到 `index.html`。

## 配置项

### `backend/.env`

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_ENV` | `development` | `production` 时 `APP_SECRET_KEY` 必填，缺失直接启动失败 |
| `APP_SECRET_KEY` | 空 | 会话签名密钥；开发环境留空会生成临时密钥，重启即失效 |
| `DATABASE_URL` | `sqlite:///./data/app.db` | 相对路径基于 `backend/` 解析 |
| `UPLOAD_DIR` | `./data/uploads` | 原始 Markdown 存放目录 |
| `BACKUP_DIR` | `./data/backups` | 备份快照目录 |
| `MAX_UPLOAD_SIZE` | `10485760` | 单文件上传上限（10 MiB） |
| `MAX_UPLOAD_LINES` | `200000` | 单文件行数上限 |
| `MAX_PARSE_SECONDS` | `20` | 单文件解析耗时上限 |
| `SESSION_COOKIE_NAME` | `selfdrill_session` | 会话 Cookie 名 |
| `SESSION_COOKIE_SECURE` | `false` | 用 HTTPS 时必须设为 `true` |
| `SESSION_MAX_AGE` | `2592000` | 会话有效期（秒，默认 30 天） |
| `PREVIEW_TTL_SECONDS` | `21600` | 导入预览有效期（秒） |
| `INITIAL_USERNAME` | `owner` | 初始账号，仅在库中无用户时创建 |
| `INITIAL_PASSWORD` | 空 | 初始密码 |
| `CORS_ORIGINS` | `http://localhost:5173,...` | 开发环境前端来源；生产同源部署留空 |

### `deploy/.env`

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_SECRET_KEY` | 必填 | 同后端 |
| `INITIAL_USERNAME` / `INITIAL_PASSWORD` | 必填 | 首次启动创建的账号 |
| `SITE_ADDRESS` | `:80` | 填域名则自动申请 HTTPS 证书 |
| `HTTP_PORT` / `HTTPS_PORT` | `80` / `443` | 宿主机映射端口 |
| `SESSION_COOKIE_SECURE` | `false` | 用 HTTPS 时设为 `true` |
| `SESSION_MAX_AGE` | `2592000` | 会话有效期（秒） |
| `MAX_UPLOAD_SIZE` | `10485760` | 单文件上传上限 |
| `PREVIEW_TTL_SECONDS` | `21600` | 导入预览有效期（秒） |
| `BACKUP_KEEP` | `7` | 备份保留份数 |
| `BACKUP_INTERVAL_SECONDS` | `86400` | 备份间隔（秒） |

## 设计约束

这些是刻意的取舍，改代码时不要绕过：

- 一轮中每道题**恰好出现一次**，顺序由服务端生成并落库，前端不能自行排序。
- 进行中的轮次**固定使用创建时的题库版本**；题库更新从下一轮开始生效。
- 答案在 `reveal` 之前**不会出现在接口响应里**，不能只靠前端隐藏。
  前端收起答案只是本地显示状态，不回退服务端的「已查看」记录。
- 进度推进携带 `expected_progress_version`，冲突返回 `409 ROUND_PROGRESS_CONFLICT`，
  前端重新拉取最新状态，不静默跳题。
- 导入采用「解析预览 → 用户确认 → 事务提交」，失败不影响当前生效版本。
- 改名 / 拆题 / 合题一律不自动处理，必须由用户在预览中确认。
- 答案 Markdown 渲染必须经过 HTML 白名单清洗，脚本注入不能穿透。
- 所有题库和轮次查询都校验资源属于当前用户，不接受客户端传入的 `user_id`。

## 数据模型

| 表 | 作用 |
| --- | --- |
| `users` | 唯一账号 |
| `question_banks` | 题库 |
| `bank_versions` | 每次导入确认生成的版本快照 |
| `questions` | 稳定题目身份（跨版本不变） |
| `question_revisions` | 某题在某版本中的内容 |
| `import_previews` | 未确认的导入结果，带过期时间 |
| `rounds` | 轮次与进度版本号 |
| `round_items` | 轮次内的固定题目顺序与答案查看状态 |
| `round_advance_requests` | `advance` 幂等记录 |

## 已知行为

- 低置信标题（例如带引言的文档标题）每次导入都会重新进入「待确认」列表。
  无法高置信判断的标题必须由人确认，而不是被静默归类。
- 「分类」标题的判定结果不会跨导入记忆；只有被确认为「题目」的标题会通过
  `questions.stable_key` 在后续导入中自动关联。
- 被删除的题目保留 `questions` 行与历史修订：它仍被历史 `round_items` 引用，
  物理删除会级联破坏已完成的轮次。
- 上传目录按内容哈希命名，删除题库不会连带删除原始文件：同一个文件可能被多个题库引用，
  做引用计数得不偿失。它们是纯文本，体积很小。

## 开发阶段

- [x] 项目初始化、配置、数据库与鉴权
- [x] 题库与题库版本模型
- [x] Markdown 解析器、题目分类与导入预览
- [x] 差异比较、更新确认与版本切换
- [x] 轮次生成、推进与并发校验
- [x] Vue 页面、状态管理与移动端布局
- [x] 答案 Markdown 安全渲染与 XSS 白名单清洗
- [x] 真实样例文件的端到端测试与验证脚本
- [x] Docker Compose、备份与部署说明

## 许可证

本项目基于 [MIT License](LICENSE) 开源，Copyright (c) 2026 [cghr](https://github.com/cghll)。

---

<div align="center">
<sub>为自己做的工具，够用就好。</sub>
</div>

<!-- badges -->

[badge-license]: https://img.shields.io/badge/license-MIT-3DA639?style=flat-square
[badge-python]: https://img.shields.io/badge/python-3.12%2B-3776AB?style=flat-square&logo=python&logoColor=white
[badge-fastapi]: https://img.shields.io/badge/FastAPI-0.143-009688?style=flat-square&logo=fastapi&logoColor=white
[badge-vue]: https://img.shields.io/badge/Vue-3.5-42B883?style=flat-square&logo=vuedotjs&logoColor=white
[badge-ts]: https://img.shields.io/badge/TypeScript-5.6-3178C6?style=flat-square&logo=typescript&logoColor=white
[badge-sqlite]: https://img.shields.io/badge/SQLite-WAL-003B57?style=flat-square&logo=sqlite&logoColor=white
[badge-docker]: https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white
[badge-tests]: https://img.shields.io/badge/tests-pytest%20%2B%20vitest-0A9EDC?style=flat-square
[badge-style]: https://img.shields.io/badge/style-ruff%20%2B%20vue--tsc-46A2F1?style=flat-square
[badge-status]: https://img.shields.io/badge/status-self--hosted%20ready-brightgreen?style=flat-square
