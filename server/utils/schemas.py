"""pydantic 模型：请求校验 + 大模型输出校验（API.md §2 的字段约束在此落地）。

质量红线：模型返回的 JSON 必须先过这里才能进 UI；校验失败走 LLM_BAD_JSON 降级，
单条不合契约则丢弃并计入 droppedCount（API.md §2）。
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# 非功能需求：单次校勘文本 ≤5000 字（PRD §5）
MAX_TEXT_LEN = 5000

CollationType = Literal["讹字", "衍文", "脱文", "通假", "异文"]
COLLATION_TYPES: tuple[str, ...] = ("讹字", "衍文", "脱文", "通假", "异文")


# ---------------------------------------------------------------------------
# 请求
# ---------------------------------------------------------------------------
class CollateOptions(BaseModel):
    """POST /collate 的 options，可整体省略（API.md §2）。"""

    model_config = ConfigDict(extra="ignore")

    checkTypes: list[CollationType] = Field(
        default_factory=lambda: list(COLLATION_TYPES), min_length=1
    )
    produceTranslation: bool = True
    referenceEdition: str = "通行本"


class CollateRequest(BaseModel):
    """POST /collate 请求体。长度上限由路由单独判，以便回 413 而非 400。"""

    model_config = ConfigDict(extra="ignore")

    text: str
    options: CollateOptions = Field(default_factory=CollateOptions)

    @field_validator("options", mode="before")
    @classmethod
    def _treat_null_as_omitted(cls, value: Any) -> Any:
        """显式传 null 与整体省略等价（API.md §2「options 可省略」）。

        前端用 JSON.stringify 时很容易把 undefined 之外的 null 发出来，
        这里按「取默认值」处理，避免一个空选项把整次校勘打成 400。
        """
        return {} if value is None else value


# ---------------------------------------------------------------------------
# 大模型输出（TECH_DESIGN §5 的输出契约；注意契约里没有 id）
# ---------------------------------------------------------------------------
class ModelItem(BaseModel):
    """模型输出契约中的单条校勘建议。"""

    model_config = ConfigDict(extra="ignore")

    type: CollationType
    original: str = Field(min_length=1)
    suggested: str
    # 理由即本作品相对「通用错别字工具」的差异点，缺理由的条目不进入 UI
    reason: str = Field(min_length=1)
    confidence: float
    # 模型给的 offset 只作参考，最终以原文定位为准（见 routers/collate.py）
    offset: int | None = None

    @field_validator("confidence")
    @classmethod
    def _normalize_confidence(cls, value: float) -> float:
        """容忍模型用百分数（95）而非小数（0.95）作答，其余越界一律判为不合契约。"""
        if not math.isfinite(value):
            raise ValueError("confidence 必须是有限数值")
        if 1.0 < value <= 100.0:
            value = value / 100.0
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"confidence 越界：{value}")
        return value

    @model_validator(mode="after")
    def _suggested_must_differ_from_original(self) -> "ModelItem":
        """`suggested` 必须与 `original` 不同（API.md §2 字段约束）。

        相同即「空操作」，有害无益：UI 会显示成「X → X」，校勘记会写出「一作 X」的自指句，
        阶段二要喂给对校引擎的异文清单也无从结构化。实测中真实模型正是这样处理异文类的
        （把别本写法只写进 reason），所以这里做成硬约束：不合契约的条目丢弃并计入 droppedCount。
        """
        if self.suggested == self.original:
            raise ValueError("suggested 与 original 相同，属空操作，不成其为校勘建议")
        return self


class ModelOutputEnvelope(BaseModel):
    """模型原始 JSON 的信封校验。

    items 故意用 list[Any]：条目要逐条单独校验，让不合契约的单条丢弃并计数
    （API.md §2 的 droppedCount），而不是一条坏数据废掉整次校勘。
    """

    model_config = ConfigDict(extra="ignore")

    items: list[Any]
    translation: str = ""


# ---------------------------------------------------------------------------
# 响应
# ---------------------------------------------------------------------------
class CollationItem(BaseModel):
    """对外输出的校勘建议：id 由后端按序分配（API.md §2）。"""

    id: int
    type: CollationType
    original: str
    suggested: str
    reason: str
    confidence: float
    offset: int


class CollateResponse(BaseModel):
    requestId: str
    model: str
    elapsedMs: int
    items: list[CollationItem]
    translation: str
    droppedCount: int


class HealthResponse(BaseModel):
    status: str
    llmProvider: str
    ocrConfigured: bool


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
