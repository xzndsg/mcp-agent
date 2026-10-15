"""统一响应信封与全局错误处理。

响应格式：{"code": 0, "message": "ok", "data": ...}
"""
from __future__ import annotations

from typing import Any

from flask import Flask, jsonify


def ok(data: Any = None, message: str = "ok"):
    return jsonify({"code": 0, "message": message, "data": data})


def fail(message: str, code: int = 1, http_status: int = 400):
    return jsonify({"code": code, "message": message, "data": None}), http_status


class ApiError(Exception):
    def __init__(self, message: str, http_status: int = 400, code: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.http_status = http_status
        self.code = code


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def _handle_api_error(exc: ApiError):
        return fail(exc.message, code=exc.code, http_status=exc.http_status)

    @app.errorhandler(KeyError)
    def _handle_key_error(exc: KeyError):
        return fail(f"资源不存在: {exc.args[0] if exc.args else ''}", http_status=404)

    @app.errorhandler(ValueError)
    def _handle_value_error(exc: ValueError):
        return fail(str(exc), http_status=400)

    @app.errorhandler(Exception)
    def _handle_unknown(exc: Exception):
        app.logger.exception("未处理异常")
        return fail(f"服务器内部错误: {type(exc).__name__}: {exc}", http_status=500)
