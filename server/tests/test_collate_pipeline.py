"""后端接口测试：schema 校验、原文定位、降级分支、置信度规则（TECH_DESIGN §2）。

不依赖真实大模型密钥：上游一律指向 `fake_llm_provider`（本地假模型），
因此断言的是**生产代码路径**的行为，而不是模型的内容质量。

运行：./.venv/Scripts/python.exe -m pytest server/tests -q
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient

from server.config import Settings
from server.main import app
from server.services.llm import complete_json, extract_json_object
from server.services.prompt_loader import PromptError, load_prompt, render
from server.tests.fake_llm_provider import FIXTURE_SAMPLE_TEXT
from server.tests.fake_llm_provider import app as fake_app
from server.utils import rate_limit
from server.utils.errors import ApiError
from server.utils.schemas import MAX_TEXT_LEN

FAKE_PORT = 3099
FAKE_BASE_URL = f"http://127.0.0.1:{FAKE_PORT}/v1"


def _wait_for_port(port: int, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise RuntimeError(f"假模型端点未在 {timeout}s 内就绪（端口 {port}）")


@pytest.fixture(scope="session")
def fake_provider() -> str:
    """在后台线程里跑一个本地假模型，返回其 base_url。"""
    config = uvicorn.Config(fake_app, host="127.0.0.1", port=FAKE_PORT, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    _wait_for_port(FAKE_PORT)
    yield FAKE_BASE_URL
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture()
def client(fake_provider: str, monkeypatch: pytest.MonkeyPatch):
    """已配置好密钥与上游的测试客户端；每个用例前后清空限流计数。"""
    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    monkeypatch.setenv("LLM_API_KEY", "fake-key")
    monkeypatch.setenv("LLM_BASE_URL", fake_provider)
    monkeypatch.setenv("LLM_MODEL", "fake")
    rate_limit.reset()
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    rate_limit.reset()


def _collate(client: TestClient, text: str, **options):
    """未传选项时整体省略 options（与 API.md「options 可省略」一致）。"""
    payload: dict = {"text": text}
    if options:
        payload["options"] = options
    return client.post("/api/v1/collate", json=payload)


# ---------------------------------------------------------------------------
# 冒烟
# ---------------------------------------------------------------------------
def test_health_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "llmProvider": "qwen", "ocrConfigured": False}


def test_health_reports_ocr_configured_when_keys_present(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCR_API_KEY", "k")
    monkeypatch.setenv("OCR_SECRET_KEY", "s")
    assert client.get("/api/v1/health").json()["ocrConfigured"] is True


# ---------------------------------------------------------------------------
# 主链路：模型输出 -> 契约校验 -> 原文定位 -> 置信度修正 -> 响应
# ---------------------------------------------------------------------------
def test_collate_filters_and_normalizes_model_output(client: TestClient) -> None:
    response = _collate(client, FIXTURE_SAMPLE_TEXT, produceTranslation=True)
    assert response.status_code == 200
    body = response.json()

    # 假模型给了 7 条，其中 1 条类型不合法、1 条原文定位失败、1 条重复 -> 丢弃 3 条
    assert body["droppedCount"] == 3
    assert [item["id"] for item in body["items"]] == [1, 2, 3, 4]
    assert [item["type"] for item in body["items"]] == ["讹字", "通假", "异文", "讹字"]
    # offset 由后端按原文重新定位并按升序排列，不采信模型自报值
    assert [item["offset"] for item in body["items"]] == [2, 11, 14, 19]
    # 置信度经字表命中修正：代/伐、说/悦 各 +0.1 封顶 1.0；88 -> 0.88 再 +0.1；
    # 未命中字表的异文保持 0.55（前端据此折叠为低置信建议）
    assert [item["confidence"] for item in body["items"]] == [1.0, 1.0, 0.55, 0.98]
    assert body["model"] == "fake"
    assert body["translation"].startswith("联调固定译文")
    assert body["requestId"].startswith("req_")
    assert body["elapsedMs"] >= 0

    # 每条 original 都必须是原文子串（API.md §2 硬约束）
    for item in body["items"]:
        assert item["original"] in FIXTURE_SAMPLE_TEXT
        assert FIXTURE_SAMPLE_TEXT[item["offset"] : item["offset"] + len(item["original"])] == item["original"]


def test_collate_without_translation_returns_empty_string(client: TestClient) -> None:
    body = _collate(client, FIXTURE_SAMPLE_TEXT, produceTranslation=False).json()
    assert body["translation"] == ""


def test_collate_accepts_no_options_at_all(client: TestClient) -> None:
    response = client.post("/api/v1/collate", json={"text": FIXTURE_SAMPLE_TEXT})
    assert response.status_code == 200
    assert response.json()["translation"] != ""


def test_collate_accepts_explicit_null_options(client: TestClient) -> None:
    """显式 null 与省略等价，不应被打成 400。"""
    response = client.post(
        "/api/v1/collate", json={"text": FIXTURE_SAMPLE_TEXT, "options": None}
    )
    assert response.status_code == 200
    assert response.json()["translation"] != ""


def test_collate_with_text_matching_nothing_drops_everything(client: TestClient) -> None:
    body = _collate(client, "abc").json()
    assert body["items"] == []
    assert body["droppedCount"] == 7


# ---------------------------------------------------------------------------
# 入参校验与限流
# ---------------------------------------------------------------------------
def test_text_too_long_returns_413(client: TestClient) -> None:
    response = _collate(client, "字" * (MAX_TEXT_LEN + 1))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "TEXT_TOO_LONG"


def test_text_at_limit_is_accepted(client: TestClient) -> None:
    assert _collate(client, "字" * MAX_TEXT_LEN).status_code == 200


def test_empty_text_returns_invalid_request(client: TestClient) -> None:
    response = _collate(client, "   ")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_missing_text_field_uses_unified_error_format(client: TestClient) -> None:
    """FastAPI 默认的 422 详情结构必须被统一成 API.md 的 {error:{code,message}}。"""
    response = client.post("/api/v1/collate", json={})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_invalid_check_type_is_rejected(client: TestClient) -> None:
    response = _collate(client, FIXTURE_SAMPLE_TEXT, checkTypes=["错别字"])
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_rate_limit_returns_429(client: TestClient) -> None:
    for _ in range(rate_limit.MAX_REQUESTS):
        assert _collate(client, FIXTURE_SAMPLE_TEXT).status_code == 200
    response = _collate(client, FIXTURE_SAMPLE_TEXT)
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"


# ---------------------------------------------------------------------------
# 降级分支：密钥缺失 / 上游异常 / 模型脏输出
# ---------------------------------------------------------------------------
def test_missing_api_key_returns_provider_misconfigured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    response = _collate(client, FIXTURE_SAMPLE_TEXT)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "PROVIDER_MISCONFIGURED"
    assert "LLM_API_KEY" in response.json()["error"]["message"]


def test_unreachable_upstream_returns_provider_misconfigured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:1/v1")
    response = _collate(client, FIXTURE_SAMPLE_TEXT)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "PROVIDER_MISCONFIGURED"


def test_upstream_500_returns_provider_misconfigured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_MODEL", "fake-error500")
    response = _collate(client, FIXTURE_SAMPLE_TEXT)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "PROVIDER_MISCONFIGURED"
    assert "500" in response.json()["error"]["message"]


def test_non_json_model_output_returns_llm_bad_json(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_MODEL", "fake-badjson")
    response = _collate(client, FIXTURE_SAMPLE_TEXT)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "LLM_BAD_JSON"


def test_bad_envelope_returns_llm_bad_json(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_MODEL", "fake-schemafail")
    response = _collate(client, FIXTURE_SAMPLE_TEXT)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "LLM_BAD_JSON"


def test_upstream_timeout_maps_to_llm_timeout(fake_provider: str) -> None:
    """直接测 llm.py 的超时映射，用小超时避免让测试等满 30 秒。"""
    settings = Settings(
        llm_provider="qwen",
        llm_api_key="fake-key",
        llm_base_url=fake_provider,
        llm_model="fake-timeout",
        ocr_api_key="",
        ocr_secret_key="",
        port=3001,
        request_timeout_s=0.4,
    )
    with pytest.raises(ApiError) as excinfo:
        asyncio.run(complete_json(settings=settings, system_prompt="s", user_prompt="u"))
    assert excinfo.value.code == "LLM_TIMEOUT"


# ---------------------------------------------------------------------------
# Prompt 资产
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["collate_v1", "translate_text_v1", "explain_v1"])
def test_prompt_assets_load(name: str) -> None:
    assert load_prompt(name)


def test_collate_prompt_renders_and_keeps_json_braces() -> None:
    """Prompt 里有 JSON 示例，渲染必须只替换 {{KEY}}，不能碰单个 `{}`。"""
    collate = load_prompt("collate_v1")
    fragment = load_prompt("translate_text_v1")["FRAGMENT"]
    user = render(
        collate["USER"],
        TEXT="北冥有鱼，其名鲲。",
        CHECK_TYPES="讹字、脱文",
        REFERENCE_EDITION="通行本",
        TRANSLATION_INSTRUCTION=fragment,
    )
    assert "北冥有鱼，其名鲲。" in user
    assert "讹字、脱文" in user
    assert '"items": [' in user  # 未提供占位符的模板必须原样保留 JSON 示例
    assert "{{" not in user


def test_render_rejects_unknown_placeholder() -> None:
    with pytest.raises(PromptError):
        render("正文 {{MISSING}}", TEXT="x")


def test_render_preserves_user_text_containing_braces() -> None:
    """用户粘贴的文本里含 {{...}} 时应原样保留，不被当成模板缺参。"""
    assert render("文：{{TEXT}}", TEXT="含 {{ABC}} 的原文") == "文：含 {{ABC}} 的原文"


# ---------------------------------------------------------------------------
# 模型原始文本 -> JSON 提取
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw",
    [
        '{"items": []}',
        '```json\n{"items": []}\n```',
        '好的，结果如下：\n{"items": []}\n以上。',
    ],
)
def test_extract_json_object(raw: str) -> None:
    assert extract_json_object(raw) == '{"items": []}'


def test_extract_json_object_rejects_prose() -> None:
    with pytest.raises(ApiError) as excinfo:
        extract_json_object("这里完全没有 JSON。")
    assert excinfo.value.code == "LLM_BAD_JSON"
