"""大模型客户端：OpenAI 兼容接口，qwen 主用 / deepseek 备用（HANDOFF §5）。

两个 provider 都走 POST {base_url}/chat/completions，切换只靠环境变量，
演示时单点故障可一键切走。密钥只在此处使用，永不出现在响应里。

上游失败的错误码映射（API.md 的错误码表没有覆盖「上游 5xx」这类情况，
这里统一归到 PROVIDER_MISCONFIGURED，即「模型通道当前不可用」，
消息里带上游状态码与响应摘要，便于现场定位）：
  - 超时                    -> LLM_TIMEOUT (504)
  - 缺密钥/未知 provider    -> PROVIDER_MISCONFIGURED (500)
  - 其它上游/网络失败        -> PROVIDER_MISCONFIGURED (500)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import httpx

from ..config import Settings
from ..utils.errors import LLM_BAD_JSON, LLM_TIMEOUT, PROVIDER_MISCONFIGURED, ApiError

# 上游错误响应回填给开发者的最大长度
_BODY_EXCERPT = 300
# 低温采样：校勘要可复现、少发挥
_TEMPERATURE = 0.2

_STATUS_HINTS = {
    401: "API Key 无效或未授权",
    403: "API Key 无权访问该模型",
    404: "接口地址或模型名不存在",
    429: "上游配额或频率受限",
}


@dataclass(frozen=True)
class LLMResult:
    """一次模型调用的结果。"""

    content: str
    model: str
    elapsed_ms: int


def extract_json_object(content: str) -> str:
    """从模型返回的文本里取出 JSON 对象字面量。

    模型常把 JSON 包在 ```json 围栏里，或在前后加一句客套话。这里只做「取最外层的
    {...}」这一件事 —— 取出来的内容仍要过 pydantic 校验，所以放宽提取不会放过脏数据。
    """
    text = content.strip()
    if text.startswith("```"):
        # 去掉 ```json / ``` 开头的围栏与结尾围栏
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[: -len("```")]
        text = text.strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ApiError(LLM_BAD_JSON, "大模型返回的内容里找不到 JSON 对象")
    return text[start : end + 1]


def _describe_upstream_failure(response: httpx.Response) -> str:
    body = " ".join(response.text.split())
    if len(body) > _BODY_EXCERPT:
        body = body[:_BODY_EXCERPT] + "…"
    hint = _STATUS_HINTS.get(response.status_code, "上游服务异常")
    return f"{hint}（HTTP {response.status_code}）：{body or '无响应体'}"


def _build_payload(settings: Settings, system_prompt: str, user_prompt: str, *, force_json: bool) -> dict:
    payload: dict = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": _TEMPERATURE,
    }
    if force_json:
        payload["response_format"] = {"type": "json_object"}
    return payload


async def complete_json(
    *,
    settings: Settings,
    system_prompt: str,
    user_prompt: str,
) -> LLMResult:
    """调用模型并返回其原始文本（JSON 解析与 schema 校验交给调用方）。"""
    if not settings.llm_configured:
        raise ApiError(
            PROVIDER_MISCONFIGURED,
            "未配置大模型密钥：请在 .env 中填写 LLM_API_KEY（可参考 .env.example）",
        )

    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }

    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=settings.request_timeout_s) as client:
        try:
            response = await client.post(
                url, headers=headers, json=_build_payload(settings, system_prompt, user_prompt, force_json=True)
            )
            # 少数 OpenAI 兼容端点不认 response_format，直接 400；
            # Prompt 本身已强约束 JSON 输出，去掉该参数重试一次即可兼容。
            if response.status_code == 400 and "response_format" in response.text:
                response = await client.post(
                    url,
                    headers=headers,
                    json=_build_payload(settings, system_prompt, user_prompt, force_json=False),
                )
        except httpx.TimeoutException as exc:
            raise ApiError(
                LLM_TIMEOUT, f"大模型响应超时（超过 {int(settings.request_timeout_s)} 秒）"
            ) from exc
        except httpx.HTTPError as exc:
            raise ApiError(PROVIDER_MISCONFIGURED, f"无法连接大模型服务：{exc}") from exc

    elapsed_ms = int((time.perf_counter() - started) * 1000)

    if response.status_code >= 400:
        raise ApiError(PROVIDER_MISCONFIGURED, _describe_upstream_failure(response))

    try:
        data = response.json()
    except ValueError as exc:
        raise ApiError(PROVIDER_MISCONFIGURED, "大模型服务返回的不是 JSON 响应") from exc

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ApiError(
            PROVIDER_MISCONFIGURED, f"大模型响应结构异常：{json.dumps(data, ensure_ascii=False)[:200]}"
        ) from exc

    if not isinstance(content, str) or not content.strip():
        raise ApiError(LLM_BAD_JSON, "大模型返回了空内容")

    model = data.get("model") if isinstance(data.get("model"), str) else settings.llm_model
    return LLMResult(content=content, model=model, elapsed_ms=elapsed_ms)
