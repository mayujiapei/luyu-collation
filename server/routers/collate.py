"""POST /api/v1/collate —— 智能校勘（F2）与白话译文（F5），契约见 API.md §2。

调用链：限流 → 入参校验 → Prompt 组装 → 调模型 → 取 JSON →
逐条 schema 校验（不合契约的丢弃计 droppedCount）→ 置信度规则修正 → 排序编号。
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from pydantic import ValidationError

from ..config import get_settings
from ..services import confidence as confidence_rules
from ..services.llm import complete_json, extract_json_object
from ..services.prompt_loader import load_prompt, render
from ..utils.errors import INTERNAL_ERROR, INVALID_REQUEST, LLM_BAD_JSON, TEXT_TOO_LONG, ApiError
from ..utils.rate_limit import check_rate_limit
from ..utils.schemas import (
    MAX_TEXT_LEN,
    CollateRequest,
    CollateResponse,
    CollationItem,
    ModelItem,
    ModelOutputEnvelope,
)

router = APIRouter()

COLLATE_PROMPT = "collate_v2"
TRANSLATE_PROMPT = "translate_text_v1"

# produceTranslation=false 时替换掉译文子 Prompt，保持 JSON 输出形状不变
_NO_TRANSLATION_BLOCK = "本次不需要白话译文：`translation` 字段固定返回空字符串。"


def _new_request_id() -> str:
    """形如 req_20261007_ab12cd（形状见 API.md §2 示例，便于日志检索）。"""
    return f"req_{datetime.now().strftime('%Y%m%d')}_{secrets.token_hex(3)}"


def _client_key(request: Request) -> str:
    """取客户端标识用于限流；部署在反向代理后时认 X-Forwarded-For 的第一跳。"""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _describe_validation_error(exc: ValidationError) -> str:
    """把 pydantic 报错压成一行，便于排查模型输出的哪一项不合契约。"""
    parts = []
    for error in exc.errors()[:3]:
        location = ".".join(str(part) for part in error.get("loc", ())) or "根"
        parts.append(f"{location}: {error.get('msg', '校验失败')}")
    return "；".join(parts)


def _build_prompts(payload: CollateRequest) -> tuple[str, str]:
    """组装 (system, user) 两条 Prompt。

    译文子 Prompt 来自 translate_text_v1.md 的 FRAGMENT 段，按 TECH_DESIGN §4 的
    「无独立翻译端点」约定拼进主调用，与校勘结果一次返回。
    """
    collate = load_prompt(COLLATE_PROMPT)
    system_prompt = collate.get("SYSTEM")
    user_template = collate.get("USER")
    if not system_prompt or not user_template:
        raise ApiError(INTERNAL_ERROR, "校勘 Prompt 资产缺少 SYSTEM 或 USER 段")

    options = payload.options
    shared = {
        "TEXT": payload.text,
        "CHECK_TYPES": "、".join(options.checkTypes),
        "REFERENCE_EDITION": options.referenceEdition,
    }
    if options.produceTranslation:
        # 译文子 Prompt 先按同一组变量渲染，再作为一段注入主 Prompt
        block = render(load_prompt(TRANSLATE_PROMPT).get("FRAGMENT", ""), **shared)
        if not block:
            raise ApiError(INTERNAL_ERROR, "译文 Prompt 资产缺少 FRAGMENT 段")
    else:
        block = _NO_TRANSLATION_BLOCK

    user_prompt = render(user_template, **shared, TRANSLATION_INSTRUCTION=block)
    return system_prompt, user_prompt


def _to_collation_items(envelope: ModelOutputEnvelope, text: str) -> tuple[list[CollationItem], int]:
    """逐条校验模型建议，返回 (可用条目, 被丢弃条数)。

    丢弃的情况与 API.md §2 一致：不合 schema（类型不在五类内、缺理由、置信度越界、
    `suggested` 与 `original` 相同的空操作）、`original` 不是原文子串、
    与已有条目完全重复（同一处同建议只留一条，避免卡片刷屏）。
    """
    dropped = 0
    seen: set[tuple[str, str, str]] = set()
    accepted: list[tuple[int, ModelItem]] = []

    for raw in envelope.items:
        try:
            item = ModelItem.model_validate(raw)
        except ValidationError:
            dropped += 1
            continue

        if item.original not in text:
            dropped += 1
            continue

        key = (item.type, item.original, item.suggested)
        if key in seen:
            dropped += 1
            continue
        seen.add(key)

        # offset 以原文定位为准，不采信模型自报值（模型常从 1 起数或整段偏移）
        accepted.append((text.find(item.original), confidence_rules.correct_confidence(item)))

    accepted.sort(key=lambda pair: pair[0])
    items = [
        CollationItem(
            id=index,
            type=item.type,
            original=item.original,
            suggested=item.suggested,
            reason=item.reason,
            confidence=item.confidence,
            offset=offset,
        )
        for index, (offset, item) in enumerate(accepted, start=1)
    ]
    return items, dropped


@router.post("/collate", response_model=CollateResponse)
async def collate(payload: CollateRequest, request: Request) -> CollateResponse:
    check_rate_limit(_client_key(request))

    text = payload.text
    if not text.strip():
        raise ApiError(INVALID_REQUEST, "待校勘文本不能为空")
    if len(text) > MAX_TEXT_LEN:
        raise ApiError(TEXT_TOO_LONG, f"文本 {len(text)} 字，超过上限 {MAX_TEXT_LEN} 字")

    system_prompt, user_prompt = _build_prompts(payload)
    result = await complete_json(
        settings=get_settings(), system_prompt=system_prompt, user_prompt=user_prompt
    )

    raw_json = extract_json_object(result.content)
    try:
        raw: Any = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ApiError(LLM_BAD_JSON, f"模型输出不是合法 JSON：{exc.msg}") from exc

    try:
        envelope = ModelOutputEnvelope.model_validate(raw)
    except ValidationError as exc:
        raise ApiError(
            LLM_BAD_JSON, f"模型输出未通过 schema 校验：{_describe_validation_error(exc)}"
        ) from exc

    items, dropped = _to_collation_items(envelope, text)
    translation = envelope.translation if payload.options.produceTranslation else ""

    return CollateResponse(
        requestId=_new_request_id(),
        model=result.model,
        elapsedMs=result.elapsed_ms,
        items=items,
        translation=translation,
        droppedCount=dropped,
    )
