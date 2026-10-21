"""统一错误：所有 API 错误都是 JSON，前端按 `code` 做分支。"""
from __future__ import annotations

from typing import Any


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str,
                 details: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details

    def payload(self) -> dict[str, Any]:
        body: dict[str, Any] = {"error": {"code": self.code, "message": self.message}}
        if self.details is not None:
            body["error"]["details"] = self.details
        return body


def bad_request(code: str, message: str, details: Any = None) -> ApiError:
    return ApiError(400, code, message, details)


def unauthorized(code: str = "UNAUTHORIZED", message: str = "未登录或会话已过期") -> ApiError:
    return ApiError(401, code, message)


def forbidden(code: str = "FORBIDDEN", message: str = "权限不足") -> ApiError:
    return ApiError(403, code, message)


def not_found(code: str = "NOT_FOUND", message: str = "资源不存在") -> ApiError:
    return ApiError(404, code, message)


def conflict(code: str, message: str, details: Any = None) -> ApiError:
    return ApiError(409, code, message, details)
