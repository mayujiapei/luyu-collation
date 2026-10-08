"""运行期配置：环境变量 + 根目录 .env 集中读取。

只用标准库实现 .env 解析（依赖清单不含 python-dotenv，见 TECH_DESIGN §4）。
真实的进程环境变量优先于 .env，便于 CI / 联调时临时覆盖。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT_DIR / ".env"

# provider 默认接入点：两者都是 OpenAI 兼容接口，可用 LLM_BASE_URL / LLM_MODEL 覆盖。
# 覆盖能力同时为阶段三的本地推理（vLLM / Ollama）留口子（ROADMAP §3）。
PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-max",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
}

DEFAULT_PORT = 3001
REQUEST_TIMEOUT_S = 30.0


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def load_env_file(path: Path | None = None) -> None:
    """把 .env 读进 os.environ（不覆盖已存在的真实环境变量）。

    支持的语法：空行、`#` 注释、`export KEY=VALUE`、值两侧的成对引号。
    path 在调用时解析（而非默认参数绑定），方便测试把 ENV_FILE 指到不存在的路径。
    """
    path = path if path is not None else ENV_FILE
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if key:
            os.environ.setdefault(key, _strip_quotes(value.strip()))


@dataclass(frozen=True)
class Settings:
    """一次进程运行内的不可变配置快照。"""

    llm_provider: str
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    ocr_api_key: str
    ocr_secret_key: str
    port: int
    request_timeout_s: float = REQUEST_TIMEOUT_S

    @property
    def llm_configured(self) -> bool:
        """密钥是否就位。缺密钥时 /collate 直接回 PROVIDER_MISCONFIGURED。"""
        return bool(self.llm_api_key and self.llm_base_url and self.llm_model)

    @property
    def ocr_configured(self) -> bool:
        return bool(self.ocr_api_key and self.ocr_secret_key)


def build_settings() -> Settings:
    """从当前环境变量组装配置。未知 provider 允许自带 base_url/model。"""
    provider = os.environ.get("LLM_PROVIDER", "qwen").strip().lower() or "qwen"
    defaults = PROVIDER_DEFAULTS.get(provider, {})
    try:
        port = int(os.environ.get("PORT") or DEFAULT_PORT)
    except ValueError:
        port = DEFAULT_PORT
    return Settings(
        llm_provider=provider,
        llm_api_key=os.environ.get("LLM_API_KEY", "").strip(),
        llm_base_url=(os.environ.get("LLM_BASE_URL", "").strip() or defaults.get("base_url", "")),
        llm_model=(os.environ.get("LLM_MODEL", "").strip() or defaults.get("model", "")),
        ocr_api_key=os.environ.get("OCR_API_KEY", "").strip(),
        ocr_secret_key=os.environ.get("OCR_SECRET_KEY", "").strip(),
        port=port,
    )


def get_settings() -> Settings:
    """读取配置（每次调用都重新读取 .env 与进程环境）。

    .env 只有几百字节，按请求重读的代价可以忽略；换来的是「改 .env 无需重启进程」，
    联调与演示时更省事。需要冻结快照的场景请自行持有返回值。
    """
    load_env_file()
    return build_settings()
