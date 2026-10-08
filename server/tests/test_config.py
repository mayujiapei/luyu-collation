"""配置加载测试：环境变量优先级，以及「改完 .env 无需重启进程即生效」。

这组用例守的是一个很容易被误判成「密钥填错了」的坑：`.env.example` 里是
`LLM_API_KEY=`（空值），照着复制成 .env 后，若用 os.environ.setdefault 注入，
空字符串会被钉在环境里，之后往 .env 填真实密钥再也不生效。
"""

from __future__ import annotations

import os

import pytest

from server import config


@pytest.fixture()
def isolated_env():
    """隔离 os.environ 与「来自 .env 的键」记录，避免污染其他用例。"""
    saved_environ = dict(os.environ)
    saved_keys = set(config._env_file_keys)
    yield
    os.environ.clear()
    os.environ.update(saved_environ)
    config._env_file_keys.clear()
    config._env_file_keys.update(saved_keys)


def _write_env(tmp_path, text: str):
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return path


def test_filling_key_after_copying_template_takes_effect_without_restart(tmp_path, isolated_env):
    """先照模板留空，再填真实密钥——不重启进程也应生效。"""
    env_path = _write_env(tmp_path, "LLM_API_KEY=\n")
    config.load_env_file(env_path)
    assert config.build_settings().llm_configured is False

    _write_env(tmp_path, "LLM_API_KEY=sk-real-key\n")
    config.load_env_file(env_path)
    settings = config.build_settings()
    assert settings.llm_api_key == "sk-real-key"
    assert settings.llm_configured is True


def test_switching_model_in_env_file_takes_effect_without_restart(tmp_path, isolated_env):
    env_path = _write_env(tmp_path, "LLM_API_KEY=sk-a\nLLM_MODEL=qwen-max\n")
    config.load_env_file(env_path)
    assert config.build_settings().llm_model == "qwen-max"

    _write_env(tmp_path, "LLM_API_KEY=sk-a\nLLM_MODEL=qwen-plus\n")
    config.load_env_file(env_path)
    assert config.build_settings().llm_model == "qwen-plus"


def test_real_environment_variable_wins_over_env_file(tmp_path, isolated_env, monkeypatch):
    """进程里真实设置的变量优先级更高，不被 .env 覆盖（CI/联调靠它临时改配置）。"""
    monkeypatch.setenv("LLM_API_KEY", "from-real-env")
    env_path = _write_env(tmp_path, "LLM_API_KEY=from-dotenv\n")
    config.load_env_file(env_path)

    assert config.build_settings().llm_api_key == "from-real-env"
    assert "LLM_API_KEY" not in config._env_file_keys


def test_env_file_parsing_handles_comments_quotes_and_export(tmp_path, isolated_env):
    env_path = _write_env(
        tmp_path,
        "\n".join(
            [
                "# 这是注释",
                "",
                "export LLM_PROVIDER=deepseek",
                'LLM_MODEL="deepseek-chat"',
                "LLM_BASE_URL='https://example.invalid/v1'",
                "LLM_API_KEY=sk-abc",
                "没有等号的行会被忽略",
            ]
        ),
    )
    config.load_env_file(env_path)
    settings = config.build_settings()
    assert settings.llm_provider == "deepseek"
    assert settings.llm_model == "deepseek-chat"
    assert settings.llm_base_url == "https://example.invalid/v1"
    assert settings.llm_api_key == "sk-abc"


def test_provider_defaults_fill_base_url_and_model(tmp_path, isolated_env):
    env_path = _write_env(tmp_path, "LLM_PROVIDER=qwen\nLLM_API_KEY=sk-abc\n")
    config.load_env_file(env_path)
    settings = config.build_settings()
    assert settings.llm_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert settings.llm_model == "qwen-max"
    assert settings.llm_configured is True


def test_unknown_provider_needs_explicit_base_url_and_model(tmp_path, isolated_env):
    """未内置默认值的 provider（如阶段三的本地推理）必须显式给地址与模型名。"""
    env_path = _write_env(tmp_path, "LLM_PROVIDER=some-local-llm\nLLM_API_KEY=sk-abc\n")
    config.load_env_file(env_path)
    settings = config.build_settings()
    assert settings.llm_provider == "some-local-llm"
    assert settings.llm_base_url == ""
    assert settings.llm_configured is False


def test_missing_env_file_is_not_an_error(tmp_path, isolated_env):
    config.load_env_file(tmp_path / "does-not-exist.env")
    assert config.build_settings().llm_provider == "qwen"


def test_invalid_port_falls_back_to_default(tmp_path, isolated_env):
    env_path = _write_env(tmp_path, "PORT=not-a-number\n")
    config.load_env_file(env_path)
    assert config.build_settings().port == config.DEFAULT_PORT
