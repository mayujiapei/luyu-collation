"""本地假模型端点 —— **仅用于离线联调与自动化测试，主链路绝不引用本文件。**

为什么需要它：在拿不到真实大模型密钥（或不想消耗额度）时，验证
「请求 → Prompt 组装 → 上游调用 → JSON 提取 → schema 校验 → 原文定位/去重丢弃 →
置信度规则修正 → 响应」这条**真实**代码路径是否通畅。它只伪装上游 HTTP 响应，
不含任何业务逻辑，也不产生任何会进入 UI 的数据。

按 AGENTS.md 的质量红线，本文件属于允许存在的「测试与开发降级路径」，
因此必须保留本标记，并且不得被 `server/main.py`、`server/routers/`、`server/services/`
下的生产代码导入（可用 `grep -r fake_llm_provider server --include=*.py` 自查）。

启动：
    ./.venv/Scripts/python.exe -m server.tests.fake_llm_provider --port 3010

把后端指过来（**只在本地联调时这样设**）：
    LLM_PROVIDER=qwen LLM_API_KEY=fake-key \
    LLM_BASE_URL=http://127.0.0.1:3010/v1 LLM_MODEL=fake \
        uvicorn server.main:app --port 3001

用 `LLM_MODEL` 选择要模拟的故障分支（见 `_MODE_BY_MODEL_KEYWORD`）：
    fake                 正常返回（含刻意的坏条目，用来验证丢弃计数）
    fake-badjson         返回非 JSON 文本            -> 期望 LLM_BAD_JSON (502)
    fake-schemafail      返回 JSON 但信封结构不对     -> 期望 LLM_BAD_JSON (502)
    fake-timeout         拖过超时阈值                -> 期望 LLM_TIMEOUT (504)
    fake-error500        上游 500                    -> 期望 PROVIDER_MISCONFIGURED (500)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="本地假模型端点（联调/测试专用）")

_MODE_BY_MODEL_KEYWORD = ("badjson", "schemafail", "timeout", "error500")

# 联调样例文本：人工拼凑的测试串（**不是真实文献**），只为让下面的固定条目有落点。
# 用它喂 POST /collate 时，期望结果为 kept=4 / dropped=3，且置信度经规则修正：
#   「代 / 伐」命中形近表 -> 0.95 提到 1.0
#   「说 / 悦」命中通假表 -> 0.90 提到 1.0
#   「未 / 末」命中形近表 -> 百分数 88 先归一为 0.88，再提到 0.98
#   「肉食者鄙」置信度 0.55 未命中任何字表 -> 保持低置信，前端折叠进「低置信建议」
# 换用 server/prompts/regression/collation_cases_v1.json 里 reg-005 的真实选段时，
# 期望 kept=2（讹字「代」、低置信异文「肉食者鄙」）/ dropped=5，见 tests/README.md。
FIXTURE_SAMPLE_TEXT = "齐师代我。公将战，不亦说乎。肉食者鄙，末能远谋。"

# 固定回应里的 items 刻意混合了「可用」与「必然被丢弃」的条目，
# 用来一次性验证 _to_collation_items 的四条过滤路径与 confidence 规则修正。
_FIXTURE_ITEMS = [
    {
        # 可用：original 是样例文本子串，且命中形近字表（代/伐）
        "type": "讹字",
        "original": "代",
        "suggested": "伐",
        "reason": "联调固定样本：「伐」误作「代」，形近而讹",
        "confidence": 0.95,
        "offset": 2,
    },
    {
        # 可用：通假类，且命中通假字表（说/悦）
        "type": "通假",
        "original": "说",
        "suggested": "悦",
        "reason": "联调固定样本：「说」通「悦」，只标注不替换",
        "confidence": 0.9,
        "offset": 11,
    },
    {
        # 可用：低置信，用于前端「低置信建议」折叠分组（API.md §2）
        "type": "异文",
        "original": "肉食者鄙",
        "suggested": "肉食者陋",
        "reason": "联调固定样本：低置信异文，不参与一键采纳",
        "confidence": 0.55,
    },
    {
        # 可用：置信度写成百分数 88，应被归一为 0.88 后再经形近表提到 0.98
        "type": "讹字",
        "original": "末能远谋",
        "suggested": "未能远谋",
        "reason": "联调固定样本：「未」误作「末」，形近而讹",
        "confidence": 88,
    },
    {
        # 丢弃：type 不在五类之内（original 故意放在样例文本里，
        # 保证它是**仅**因类型不合法而被丢弃）
        "type": "错字",
        "original": "公将战",
        "suggested": "公将战",
        "reason": "联调固定样本：类型不合法，应被 schema 校验淘汰",
        "confidence": 0.9,
    },
    {
        # 丢弃：original 不在样例文本中（模拟模型幻觉出的片段）
        "type": "异文",
        "original": "有朋自远方来",
        "suggested": "有朋自远方来哉",
        "reason": "联调固定样本：原文不含此片段，应被原文定位淘汰",
        "confidence": 0.9,
    },
    {
        # 丢弃：与第 1 条完全重复
        "type": "讹字",
        "original": "代",
        "suggested": "伐",
        "reason": "联调固定样本：重复条目应被去重",
        "confidence": 0.95,
    },
]

_FIXTURE_BODY = json.dumps(
    {"items": _FIXTURE_ITEMS, "translation": "联调固定译文：十年春天，齐国军队攻打我国。"},
    ensure_ascii=False,
)

FIXTURE_EXPECTED = {
    "sampleText": FIXTURE_SAMPLE_TEXT,
    "keptIds": [1, 2, 3, 4],
    "keptOffsets": [2, 11, 14, 19],
    "keptConfidence": [1.0, 1.0, 0.55, 0.98],
    "dropped": 3,
    "droppedReason": "1 条类型不合法 + 1 条原文定位失败 + 1 条重复",
}


def _mode_for(model: str) -> str:
    for keyword in _MODE_BY_MODEL_KEYWORD:
        if keyword in model:
            return keyword
    return "ok"


def _envelope(content: str, model: str) -> dict:
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    model = str(body.get("model", "fake"))
    mode = _mode_for(model)

    if mode == "timeout":
        await asyncio.sleep(120)
    if mode == "error500":
        return JSONResponse(status_code=500, content={"error": {"message": "假模型：模拟上游 500"}})
    if mode == "badjson":
        return JSONResponse(_envelope("这不是 JSON，只是一段散文。", model))
    if mode == "schemafail":
        # 信封结构不对：items 应是数组，这里给了字符串
        return JSONResponse(
            _envelope(json.dumps({"items": "不是数组", "translation": ""}, ensure_ascii=False), model)
        )
    return JSONResponse(_envelope(_FIXTURE_BODY, model))


@app.get("/v1/health")
async def fake_health():
    return {"status": "ok", "fixture": FIXTURE_EXPECTED}


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="本地假模型端点（联调/测试专用）")
    parser.add_argument("--port", type=int, default=3010)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
