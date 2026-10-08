"""FastAPI 入口：CORS、路由挂载、统一异常处理（TECH_DESIGN §1 的应用层）。

启动：`npm run dev:server` 或 `uvicorn server.main:app --reload --port 3001`。
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .routers import collate, health
from .utils.errors import INTERNAL_ERROR, INVALID_REQUEST, ApiError, error_body

logger = logging.getLogger("guji.server")

API_PREFIX = "/api/v1"

# 本地开发来源：Vite dev（5173）与 vite preview（4173）。用显式清单而非通配，
# 避免任意网页都能打这个本地 BFF。
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
]

app = FastAPI(
    title="古籍智能校勘系统 API",
    version="1.0.0",
    description="薄 BFF：校验、Prompt 组装、限流、密钥托管。契约见 docs/API.md。",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix=API_PREFIX, tags=["health"])
app.include_router(collate.router, prefix=API_PREFIX, tags=["collate"])


@app.exception_handler(ApiError)
async def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
    """业务错误：统一 {error:{code,message}} 格式（API.md 首部约定）。"""
    return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, exc.message))


@app.exception_handler(RequestValidationError)
async def handle_request_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
    """请求体 schema 校验失败。

    FastAPI 默认回 422 + 另一套结构，这里按 API.md 统一成 400 / INVALID_REQUEST。
    """
    details = []
    for error in exc.errors()[:3]:
        location = ".".join(str(part) for part in error.get("loc", ())) or "请求体"
        details.append(f"{location}: {error.get('msg', '校验失败')}")
    return JSONResponse(
        status_code=400,
        content=error_body(INVALID_REQUEST, "请求参数不合法：" + "；".join(details)),
    )


@app.exception_handler(Exception)
async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
    """兜底：任何未预期异常也走统一错误格式，前端不会拿到 HTML 错误页。"""
    logger.exception("未预期的服务端异常", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content=error_body(INTERNAL_ERROR, "服务端内部错误，请查看后端日志"),
    )


if __name__ == "__main__":  # pragma: no cover - 便捷启动入口
    import uvicorn

    uvicorn.run(
        "server.main:app",
        host="127.0.0.1",
        port=get_settings().port,
        reload=True,
    )
