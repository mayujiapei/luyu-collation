"""Prompt 回归集执行器 —— 把 `prompts/regression/` 的固定文本跑一遍并核对期望要点。

用途：改了 `collate_v1.md`（或换了模型/供应商）之后，用同一组用例对比是否退化。
不参与生产链路；需要真实密钥（读 .env），会产生真实的模型调用费用。

用法：
    ./.venv/Scripts/python.exe -m server.tests.run_regression
    ./.venv/Scripts/python.exe -m server.tests.run_regression --only reg-005
    ./.venv/Scripts/python.exe -m server.tests.run_regression --verbose   # 打印每条建议

退出码：全部通过 0；有失败 1。这样可以直接挂到 CI 或演示前的冒烟流程里。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from fastapi.testclient import TestClient

from server.main import app
from server.utils.schemas import COLLATION_TYPES

CASES_PATH = (
    Path(__file__).resolve().parent.parent / "prompts" / "regression" / "collation_cases_v1.json"
)


@dataclass
class CaseResult:
    case_id: str
    kind: str
    origin: str
    passed: bool
    problems: list[str] = field(default_factory=list)
    item_count: int = 0
    dropped: int = 0
    types: list[str] = field(default_factory=list)
    elapsed_ms: int = 0
    error: str = ""


def _load_cases() -> tuple[dict, list[dict]]:
    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    return payload, payload["cases"]


def _check_case(case: dict, body: dict) -> list[str]:
    """核对 mustFind / minItems / maxItems，返回问题列表（空即通过）。"""
    problems: list[str] = []
    items = body.get("items", [])
    expected = case.get("expected", {})

    minimum = expected.get("minItems", 0)
    maximum = expected.get("maxItems")
    if len(items) < minimum:
        problems.append(f"条数 {len(items)} < minItems {minimum}（漏报）")
    if maximum is not None and len(items) > maximum:
        problems.append(f"条数 {len(items)} > maxItems {maximum}（误报）")

    for want in expected.get("mustFind", []):
        hit = any(
            item["type"] == want["type"]
            and want.get("originalContains", "") in item["original"]
            and want.get("suggestContains", "") in item["suggested"]
            for item in items
        )
        if not hit:
            problems.append(
                f"未命中必须找到的条目：type={want['type']} "
                f"original 含 {want.get('originalContains', '')!r} / "
                f"suggested 含 {want.get('suggestContains', '')!r}"
            )

    unknown = [item["type"] for item in items if item["type"] not in COLLATION_TYPES]
    if unknown:
        problems.append(f"出现五类之外的校勘类型：{unknown}")

    return problems


def run(only: str | None, verbose: bool) -> int:
    payload, cases = _load_cases()
    if only:
        cases = [case for case in cases if case["id"] == only]
        if not cases:
            print(f"没有找到用例 {only}")
            return 1

    print(f"回归集 {payload.get('version')} · Prompt {payload.get('prompt')} · 端点 {payload.get('endpoint')}")
    print(f"用例数 {len(cases)}（control=干净对照看误报，injected=注入错误看检出）\n")

    results: list[CaseResult] = []
    with TestClient(app, raise_server_exceptions=False) as client:
        health = client.get("/api/v1/health").json()
        print(f"后端就绪：{health}\n")

        for case in cases:
            options = {"produceTranslation": False}
            response = client.post(
                "/api/v1/collate",
                json={"text": case["source"], "options": options},
            )
            result = CaseResult(
                case_id=case["id"],
                kind=case["kind"],
                origin=case["origin"],
                passed=False,
            )

            if response.status_code != 200:
                detail = response.json().get("error", {})
                result.error = f"HTTP {response.status_code} {detail.get('code', '')} {detail.get('message', '')}"
            else:
                body = response.json()
                result.item_count = len(body["items"])
                result.dropped = body["droppedCount"]
                result.types = [item["type"] for item in body["items"]]
                result.elapsed_ms = body["elapsedMs"]
                result.problems = _check_case(case, body)
                result.passed = not result.problems

                if verbose:
                    print(f"  [{case['id']}] 注入：{case['expected'].get('injected')}")
                    for item in body["items"]:
                        print(
                            f"      {item['type']} | {item['original']!r} -> {item['suggested']!r} "
                            f"| conf={item['confidence']} | {item['reason']}"
                        )
                    if not body["items"]:
                        print("      （无建议）")

            results.append(result)
            flag = "PASS" if result.passed else "FAIL"
            summary = result.error or (
                f"items={result.item_count} dropped={result.dropped} "
                f"types={'/'.join(result.types) or '-'} {result.elapsed_ms}ms"
            )
            print(f"{flag}  {result.case_id}  [{result.kind:8s}] {result.origin}")
            print(f"      {summary}")
            for problem in result.problems:
                print(f"      !! {problem}")

    passed = [r for r in results if r.passed]
    print(f"\n结果：{len(passed)}/{len(results)} 通过")
    failed = [r for r in results if not r.passed]
    if failed:
        print("未通过用例：" + "、".join(r.case_id for r in failed))
        print("提示：先看 expected.injected 与上面的实际输出差异，再决定改 collate_v1.md 还是改用例。")
    return 0 if not failed else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Prompt 回归集执行器（需要真实密钥）")
    parser.add_argument("--only", help="只跑某个用例，如 reg-005")
    parser.add_argument("--verbose", action="store_true", help="打印每条建议的内容")
    args = parser.parse_args()
    sys.exit(run(args.only, args.verbose))


if __name__ == "__main__":
    main()
