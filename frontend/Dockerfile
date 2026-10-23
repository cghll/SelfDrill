# SelfDrill 前端镜像：先构建静态文件，再由 Caddy 直接提供并反代 /api
FROM node:22-alpine AS build

WORKDIR /app

# 锁定 pnpm 版本，避免 CI 与本地解析出不同依赖树
RUN corepack enable && corepack prepare pnpm@11.7.0 --activate

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY index.html vite.config.ts tsconfig.json ./
COPY src ./src

RUN pnpm run build


FROM caddy:2-alpine AS runtime

COPY --from=build /app/dist /srv
# Caddyfile 由 docker-compose 从 deploy/ 挂载，
# 这样 HTTPS 域名等部署参数不需要重新构建镜像。

EXPOSE 80 443