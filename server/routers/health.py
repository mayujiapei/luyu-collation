"""GET /api/v1/health —— 冒烟检查（API.md §5）。"""

from __future__ import annotations

from fastapi import APIRouter

from ..config import get_settings
from ..utils.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """服务可用性探针。

    这里只报告进程内的配置状态，不主动探测上游 —— 演示前要的是「后端活着吗」，
    真的连通性用一条真实 /collate 验证（TECH_DESIGN §8）。
    """
    settings = get_settings()
    return HealthResponse(
        status="ok",
        llmProvider=settings.llm_provider,
        ocrConfigured=settings.ocr_configured,
    )
