"""应用入口：路由注册、异常处理、启动初始化。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth.router import router as auth_router
from app.banks.router import router as banks_router
from app.imports.router import router as imports_router
from app.rounds.router import router as rounds_router
from app.common.errors import AppError, InvalidRequestError
from app.config import get_settings
from app.db.session import get_session_factory, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

# HTTP 状态码 → 契约错误码，保证所有错误响应结构一致
_STATUS_TO_CODE = {
    400: "INVALID_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "INVALID_REQUEST",
    413: "FILE_TOO_LARGE",
    415: "UNSUPPORTED_FILE_TYPE",
    422: "INVALID_REQUEST",
    500: "INTERNAL_ERROR",
}


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.ensure_directories()
    # 生产环境缺密钥时在这里直接失败，避免用临时密钥启动
    settings.resolved_secret_key()
    init_db()
    from app.auth.service import ensure_initial_user

    with get_session_factory()() as session:
        ensure_initial_user(session, settings)
    logger.info("SelfDrill API 已启动（env=%s）", settings.app_env)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    # 生产环境关闭交互式文档与 OpenAPI 描述，减少对外暴露的接口信息（NFR-001）
    expose_docs = not settings.is_production
    app = FastAPI(
        title="SelfDrill API",
        version="1.0.0",
        docs_url="/api/docs" if expose_docs else None,
        redoc_url="/api/redoc" if expose_docs else None,
        openapi_url="/api/openapi.json" if expose_docs else None,
        lifespan=lifespan,
    )

    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    _register_error_handlers(app)

    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(banks_router, prefix="/api/v1")
    app.include_router(imports_router, prefix="/api/v1")
    app.include_router(rounds_router, prefix="/api/v1")

    return app


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        error = InvalidRequestError(
            "请求参数无效",
            details={"errors": _safe_validation_errors(exc)},
        )
        return JSONResponse(status_code=error.status_code, content=error.to_payload())

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = _STATUS_TO_CODE.get(exc.status_code, "INTERNAL_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else "请求失败"
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": code, "message": message, "details": {}}},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        # 只记录异常类型与消息，不记录请求体，避免密码进入日志
        logger.exception("未预期服务端错误: %s", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "未预期服务端错误",
                    "details": {},
                }
            },
        )


def _safe_validation_errors(exc: RequestValidationError) -> list[dict[str, object]]:
    """裁掉 Pydantic 错误里的输入值，避免回显敏感字段。"""
    return [
        {
            "loc": [str(part) for part in err.get("loc", ())],
            "type": err.get("type", "unknown"),
            "msg": err.get("msg", ""),
        }
        for err in exc.errors()
    ]


app = create_app()
