"""通用模型配置迁移与厂商适配行为；测试只使用合成凭据。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel, Field

from app.config import Settings
from app.llm import clients


def settings_input() -> dict:
    """隔离本地 .env，提供所有非模型依赖的占位配置。"""
    return {
        "_env_file": None,
        "mysql_uri": "mysql://test:test@localhost/test",
        "llm_api_base": "http://llm.invalid/v1",
        "llm_api_key": "synthetic-key",
        "llm_provider": "deepseek",
        "otc_api_base_url": "http://java.invalid",
        "otc_api_secret": "synthetic-secret",
    }


@pytest.mark.parametrize("source", ["environment", "dotenv", "constructor"])
def test_old_keys_are_rejected_without_exposing_values(monkeypatch, tmp_path, source) -> None:
    """新旧同时存在也不能静默兼容，错误只显示旧键名。"""
    values = settings_input()
    sensitive = "sensitive-migration-value"
    if source == "environment":
        monkeypatch.setenv("QWEN_API_KEY", sensitive)
    elif source == "dotenv":
        path = tmp_path / ".env"
        path.write_text(f"QWEN_API_KEY={sensitive}\n")
        values["_env_file"] = path
    else:
        values["qwen_api_key"] = sensitive
    with pytest.raises(ValueError) as error:
        Settings(**values)
    assert "QWEN_API_KEY" in str(error.value)
    assert "迁移" in str(error.value)
    assert sensitive not in str(error.value)


class Probe(BaseModel):
    """合成 function-calling 输出，不执行网络请求。"""

    ready: bool = Field(description="能力探针返回值")


@pytest.mark.parametrize(
    "provider,model,expected_body,method",
    [
        ("deepseek", "gateway-model-a", {"thinking": {"type": "disabled"}}, "tools"),
        (
            "qwen",
            "deepseek-name-is-not-the-provider",
            {"enable_thinking": False},
            "response_format",
        ),
        ("openai_compatible", "qwen-name-is-not-the-provider", None, "tools"),
    ],
)
async def test_factory_uses_explicit_provider_instead_of_model_name(
    monkeypatch, provider, model, expected_body, method
) -> None:
    """模型别名不决定私有参数；通用适配只发送标准协议字段。"""
    assert hasattr(clients, "get_llm_standard"), "通用工厂尚未提供"
    factory = clients.get_llm_standard
    factory.cache_clear()
    settings = SimpleNamespace(
        llm_api_base="http://llm.invalid/v1",
        llm_api_key="test-key",
        llm_provider=provider,
        llm_model_standard=model,
        llm_timeout_seconds=20,
        llm_output_max_tokens=1024,
        llm_trust_env=False,
    )
    monkeypatch.setattr(clients, "get_settings", lambda: settings)
    llm = factory()
    try:
        assert llm.model_name == model
        assert llm.extra_body == expected_body
        bound = llm.with_structured_output(Probe).first.kwargs
        assert method in bound
        assert "provider" not in llm._default_params
        assert llm.max_retries == 0
    finally:
        llm.root_client.close()
        await llm.root_async_client.close()
        factory.cache_clear()


async def test_three_roles_are_independent_and_structured_uses_standard(monkeypatch) -> None:
    """保留三个角色；角色名不打开思考模式。"""
    names = {
        "standard": "model-s",
        "thinking": "model-t",
        "complex": "model-c",
        "structured": "model-s",
    }
    assert all(hasattr(clients, f"get_llm_{name}") for name in names)
    settings = SimpleNamespace(
        llm_api_base="http://llm.invalid/v1",
        llm_api_key="test-key",
        llm_provider="deepseek",
        llm_model_standard="model-s",
        llm_model_thinking="model-t",
        llm_model_complex="model-c",
        llm_timeout_seconds=20,
        llm_output_max_tokens=1024,
        llm_trust_env=False,
    )
    monkeypatch.setattr(clients, "get_settings", lambda: settings)
    for role, expected in names.items():
        factory = getattr(clients, f"get_llm_{role}")
        factory.cache_clear()
        model = factory()
        try:
            assert model.model_name == expected
            assert model.extra_body == {"thinking": {"type": "disabled"}}
        finally:
            model.root_client.close()
            await model.root_async_client.close()
            factory.cache_clear()
