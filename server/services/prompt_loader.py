"""Prompt 资产加载：server/prompts/<name>.md，按 `## SECTION` 分段。

文件按版本命名（collate_v1.md）。改 Prompt 要新建 _v2 文件并改调用方引用，
以便「Prompt 资产带版本号」与回归对比（TECH_DESIGN §4、§5）。
故意不做缓存：一次请求读一个几 KB 的文件，相比动辄数秒的模型调用可以忽略，
换来的是改完 .md 立刻生效（.md 改动不会触发 uvicorn --reload）。
"""

from __future__ import annotations

import re
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

_SECTION_RE = re.compile(r"^##\s+([A-Z_]+)\s*$", re.MULTILINE)

# 未替换的占位符一旦发进 Prompt，模型会把它当正文，属于必须暴露的实现错误
_PLACEHOLDER_RE = re.compile(r"\{\{[A-Z_]+\}\}")


class PromptError(RuntimeError):
    """Prompt 资产缺失或格式不合法 —— 属于部署问题，按 500 处理。"""


def load_prompt(name: str) -> dict[str, str]:
    """读取 Prompt 资产，返回 {段名: 正文}。

    段名按文件里的 `## SYSTEM` / `## USER` / `## FRAGMENT` 原样返回，
    由调用方决定取哪几段（译文子 Prompt 用的是 FRAGMENT）。
    """
    path = PROMPTS_DIR / f"{name}.md"
    if not path.is_file():
        raise PromptError(f"Prompt 资产不存在：{path}")

    text = path.read_text(encoding="utf-8")
    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        raise PromptError(f"Prompt 资产缺少 `## SECTION` 分段：{path}")

    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group(1)] = text[start:end].strip()
    return sections


def render(template: str, **values: str) -> str:
    """替换 {{KEY}} 占位符。

    用 str.replace 而非 str.format：Prompt 里带 JSON 示例的 `{}`，format 会直接抛错。
    替换前先检查模板是否引用了未提供的占位符 —— 检查对象是模板而不是替换结果，
    这样用户粘贴的文本里即使含 `{{...}}` 也会原样保留，不会被误判为模板缺参。
    """
    provided = {"{{" + key + "}}" for key in values}
    missing = {match.group(0) for match in _PLACEHOLDER_RE.finditer(template)} - provided
    if missing:
        raise PromptError(f"Prompt 模板引用了未提供的占位符：{'、'.join(sorted(missing))}")

    result = template
    for key, value in values.items():
        result = result.replace("{{" + key + "}}", value)
    return result
