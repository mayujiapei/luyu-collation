"""测试环境隔离。

整个测试会话都不读仓库根目录的 .env，否则开发者本机若已配好真实密钥：
1. 用例可能意外打真实上游，产生费用或把结果算进免费额度；
2. `monkeypatch.delenv("LLM_API_KEY")` 一类用例会被 .env 的值重新填上而失败。
"""

from __future__ import annotations

import pytest

from server import config


@pytest.fixture(scope="session", autouse=True)
def _isolate_env_file(tmp_path_factory: pytest.TempPathFactory):
    missing = tmp_path_factory.mktemp("isolated") / ".env"
    original = config.ENV_FILE
    config.ENV_FILE = missing
    yield
    config.ENV_FILE = original
