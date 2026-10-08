"""统一错误类型与错误码。

错误码与 HTTP 状态码的映射是 API.md「错误码一览」的唯一副本，改接口先改 API.md。
"""

from __future__ import annotations

# 与 docs/API.md 错误码一览一一对应（不要在这里新增未写进 API.md 的码）
TEXT_TOO_LONG = "TEXT_TOO_LONG"
INVALID_REQUEST = "INVALID_REQUEST"
OCR_FAILED = "OCR_FAILED"
LLM_TIMEOUT = "LLM_TIMEOUT"
LLM_BAD_JSON = "LLM_BAD_JSON"
RATE_LIMITED = "RATE_LIMITED"
PROVIDER_MISCONFIGURED = "PROVIDER_MISCONFIGURED"
INTERNAL_ERROR = "INTERNAL_ERROR"

CODE_STATUS: dict[str, int] = {
    TEXT_TOO_LONG: 413,
    INVALID_REQUEST: 400,
    OCR_FAILED: 502,
    LLM_TIMEOUT: 504,
    LLM_BAD_JSON: 502,
    RATE_LIMITED: 429,
    PROVIDER_MISCONFIGURED: 500,
    INTERNAL_ERROR: 500,
}


class ApiError(Exception):
    """业务错误：由 main.py 的异常处理器统一转成 {error:{code,message}}。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        self.status_code = CODE_STATUS.get(code, 500)
        super().__init__(message)


def error_body(code: str, message: str) -> dict[str, dict[str, str]]:
    """API.md 规定的统一错误格式。"""
    return {"error": {"code": code, "message": message}}
