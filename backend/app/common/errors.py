"""领域错误与统一错误码。

错误码集合是封闭的（见 docs/03 第 2 节），新增错误码必须同步更新文档与测试。
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """所有可预期业务错误的基类。"""

    status_code: int = 500
    code: str = "INTERNAL_ERROR"
    message: str = "未预期服务端错误"

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or self.message)
        if message:
            self.message = message
        self.details: dict[str, Any] = details or {}

    def to_payload(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }


class InvalidRequestError(AppError):
    status_code = 400
    code = "INVALID_REQUEST"
    message = "请求参数无效"


class UnauthenticatedError(AppError):
    status_code = 401
    code = "UNAUTHENTICATED"
    message = "未登录或会话失效"


class ForbiddenError(AppError):
    status_code = 403
    code = "FORBIDDEN"
    message = "无权访问资源"


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"
    message = "资源不存在"


class RoundProgressConflictError(AppError):
    status_code = 409
    code = "ROUND_PROGRESS_CONFLICT"
    message = "轮次进度已被其他设备更新"


class ImportPreviewExpiredError(AppError):
    status_code = 409
    code = "IMPORT_PREVIEW_EXPIRED"
    message = "导入预览已过期"


class ImportConfirmationRequiredError(AppError):
    status_code = 409
    code = "IMPORT_CONFIRMATION_REQUIRED"
    message = "存在未处理的歧义项"


class FileTooLargeError(AppError):
    status_code = 413
    code = "FILE_TOO_LARGE"
    message = "文件超过大小限制"


class UnsupportedFileTypeError(AppError):
    status_code = 415
    code = "UNSUPPORTED_FILE_TYPE"
    message = "暂不支持该文件类型"


class MarkdownParseFailedError(AppError):
    status_code = 422
    code = "MARKDOWN_PARSE_FAILED"
    message = "Markdown 无法解析"


class InternalError(AppError):
    status_code = 500
    code = "INTERNAL_ERROR"
    message = "未预期服务端错误"
