"""app/llm/clients.py 工厂的 vendor 适配测试。

背景（ADR 0020）：模型经 .env 切换，适配层兼容 Qwen 与 DeepSeek。
关闭思考模式的参数两家不同：
- Qwen (dashscope)：extra_body={"enable_thinking": False}
- DeepSeek：extra_body={"thinking": {"type": "disabled"}}
  （DeepSeek 会静默忽略 enable_thinking，导致默认开思考、延迟爆炸）
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.llm import clients


class TestThinkingOffExtraBody:
    """_thinking_off_extra_body：按模型名选择关闭思考的参数。"""

    def test_deepseek_uses_thinking_disabled(self) -> None:
        assert clients._thinking_off_extra_body("deepseek-v4-pro") == {
            "thinking": {"type": "disabled"}
        }

    def test_deepseek_case_insensitive(self) -> None:
        assert clients._thinking_off_extra_body("DeepSeek-V4-Pro") == {
            "thinking": {"type": "disabled"}
        }

    def test_qwen_uses_enable_thinking_false(self) -> None:
        assert clients._thinking_off_extra_body("qwen3-30b-a3b") == {
            "enable_thinking": False
        }

    def test_unknown_vendor_falls_back_to_qwen_style(self) -> None:
        assert clients._thinking_off_extra_body("qwen-plus") == {
            "enable_thinking": False
        }


def _fake_settings(model: str) -> SimpleNamespace:
    return SimpleNamespace(
        qwen_api_base="https://api.deepseek.com/v1",
        qwen_api_key="sk-test",
        qwen_model_standard=model,
        qwen_model_thinking=model,
        qwen_model_complex=model,
        qwen_model_vl="qwen-vl-max-latest",
        llm_timeout_seconds=60.0,
        llm_output_max_tokens=800,
        llm_vision_max_tokens=4096,
        llm_trust_env=True,
    )


@pytest.fixture()
def _clear_factory_caches():
    """工厂是 lru_cache 单例，测试前后都要清掉，避免污染其他用例。"""
    for fn in (
        clients.get_qwen_standard,
        clients.get_qwen_thinking,
        clients.get_qwen_structured,
        clients.get_qwen_complex,
        clients.get_qwen_vl,
    ):
        fn.cache_clear()
    yield
    for fn in (
        clients.get_qwen_standard,
        clients.get_qwen_thinking,
        clients.get_qwen_structured,
        clients.get_qwen_complex,
        clients.get_qwen_vl,
    ):
        fn.cache_clear()


@pytest.mark.usefixtures("_clear_factory_caches")
@pytest.mark.parametrize(
    "factory_name",
    [
        "get_qwen_standard", "get_qwen_thinking", "make_qwen_thinking",
        "get_qwen_structured", "get_qwen_complex", "get_qwen_vl",
    ],
)
@pytest.mark.parametrize("trust_env", [False, True])
async def test_factory_respects_llm_trust_env(
    monkeypatch: pytest.MonkeyPatch, factory_name: str, trust_env: bool
) -> None:
    settings = _fake_settings("external-deepseek-v4-pro")
    settings.llm_trust_env = trust_env
    monkeypatch.setattr(clients, "get_settings", lambda: settings)
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7897")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7897")
    if not trust_env:
        monkeypatch.setenv("OPENAI_PROXY", "http://127.0.0.1:7897")
    llm = getattr(clients, factory_name)()
    try:
        assert llm.root_client._client.trust_env is trust_env
        assert llm.root_async_client._client.trust_env is trust_env
        if not trust_env:
            assert llm.openai_proxy is None
    finally:
        llm.root_client.close()
        await llm.root_async_client.close()


@pytest.mark.usefixtures("_clear_factory_caches")
async def test_rebuilt_factory_does_not_reuse_closed_http_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        clients, "get_settings", lambda: _fake_settings("external-deepseek-v4-pro")
    )
    first = clients.get_qwen_structured()
    first_sync = first.root_client._client
    first_async = first.root_async_client._client
    first.root_client.close()
    await first.root_async_client.close()
    clients.get_qwen_structured.cache_clear()

    second = clients.get_qwen_structured()
    try:
        assert second.root_client._client is not first_sync
        assert second.root_async_client._client is not first_async
        assert not second.root_async_client._client.is_closed
    finally:
        second.root_client.close()
        await second.root_async_client.close()


@pytest.mark.parametrize("configured", [False, True])
def test_llm_trust_env_loads_from_dotenv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, configured: bool
) -> None:
    from app.config import Settings

    monkeypatch.delenv("LLM_TRUST_ENV", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_TRUST_ENV=false\n" if configured else "", encoding="utf-8")
    settings = Settings(
        _env_file=env_file,
        mysql_uri="mysql://test:test@localhost/test",
        checkpoint_mysql_uri="mysql://test:test@localhost/test",
        business_mysql_uri="mysql+aiomysql://test:test@localhost/test",
        qwen_api_base="https://llm.example/v1",
        qwen_api_key="test-key",
        otc_api_base_url="http://backend.example",
        otc_api_secret="test-secret",
    )
    assert settings.model_dump().get("llm_trust_env") is (not configured)


@pytest.mark.usefixtures("_clear_factory_caches")
class TestFactoryExtraBody:
    """工厂函数在 DeepSeek 模型下应带 DeepSeek 风格的 extra_body。"""

    @pytest.mark.parametrize(
        "factory_name",
        ["get_qwen_standard", "get_qwen_thinking", "get_qwen_structured", "get_qwen_complex", "make_qwen_thinking"],
    )
    @pytest.mark.parametrize("model", ["deepseek-v4-pro", "external-deepseek-v4-pro"])
    def test_deepseek_model_gets_thinking_disabled(
        self, monkeypatch: pytest.MonkeyPatch, factory_name: str, model: str
    ) -> None:
        monkeypatch.setattr(
            clients, "get_settings", lambda: _fake_settings(model)
        )
        llm = getattr(clients, factory_name)()
        assert llm.model_name == model
        assert llm.extra_body == {"thinking": {"type": "disabled"}}

    def test_qwen_model_keeps_enable_thinking(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            clients, "get_settings", lambda: _fake_settings("qwen3-30b-a3b")
        )
        llm = clients.get_qwen_standard()
        assert llm.extra_body == {"enable_thinking": False}

    def test_make_qwen_thinking_deepseek(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            clients, "get_settings", lambda: _fake_settings("deepseek-v4-pro")
        )
        llm = clients.make_qwen_thinking()
        assert llm.extra_body == {"thinking": {"type": "disabled"}}


class _DummyOut(SimpleNamespace):
    pass


@pytest.mark.parametrize("factory_name,expected", [
    ("get_qwen_standard", 800), ("get_qwen_thinking", 800),
    ("get_qwen_structured", 800), ("get_qwen_complex", 800),
    ("make_qwen_thinking", 800), ("get_qwen_vl", 4096),
])
def test_factory_enforces_configured_output_budget(monkeypatch, factory_name, expected):
    factory = getattr(clients, factory_name)
    if hasattr(factory, "cache_clear"):
        factory.cache_clear()
    monkeypatch.setattr(clients, "get_settings", lambda: _fake_settings("deepseek-v4-pro"))
    try:
        assert factory().max_tokens == expected
    finally:
        if hasattr(factory, "cache_clear"):
            factory.cache_clear()


@pytest.mark.usefixtures("_clear_factory_caches")
class TestStructuredOutputMethod:
    """DeepSeek 不支持 response_format=json_schema（400），
    with_structured_output 不传 method 时必须自动降级为 function_calling。
    Qwen 保持 langchain 默认（json_schema）不变。
    """

    @staticmethod
    def _bound_kwargs(runnable) -> dict:
        # with_structured_output 返回 RunnableSequence，first 是 RunnableBinding
        return runnable.first.kwargs

    @pytest.mark.parametrize("model", [
        "deepseek-v4-pro", "external-deepseek-v4-pro", "External-DeepSeek-V4-Pro",
        "gateway/deepseek-v4-pro",
    ])
    def test_deepseek_defaults_to_function_calling(
        self, monkeypatch: pytest.MonkeyPatch, model: str
    ) -> None:
        from pydantic import BaseModel

        class Out(BaseModel):
            x: int

        monkeypatch.setattr(
            clients, "get_settings", lambda: _fake_settings(model)
        )
        llm = clients.get_qwen_standard()
        kwargs = self._bound_kwargs(llm.with_structured_output(Out))
        assert "tools" in kwargs
        assert "response_format" not in kwargs

    @pytest.mark.parametrize("model", ["deepseek-v4-pro", "external-deepseek-v4-pro"])
    def test_deepseek_explicit_method_respected(
        self, monkeypatch: pytest.MonkeyPatch, model: str
    ) -> None:
        from pydantic import BaseModel

        class Out(BaseModel):
            x: int

        monkeypatch.setattr(
            clients, "get_settings", lambda: _fake_settings(model)
        )
        llm = clients.get_qwen_standard()
        kwargs = self._bound_kwargs(
            llm.with_structured_output(Out, method="json_mode")
        )
        assert kwargs["response_format"] == {"type": "json_object"}
        assert "tools" not in kwargs

    @pytest.mark.parametrize("model", [
        "qwen3-30b-a3b", "external-qwen3-30b-a3b", "notdeepseek-v4-pro", "deepseeker-v1",
    ])
    def test_qwen_keeps_langchain_default(
        self, monkeypatch: pytest.MonkeyPatch, model: str
    ) -> None:
        from pydantic import BaseModel

        class Out(BaseModel):
            x: int

        monkeypatch.setattr(
            clients, "get_settings", lambda: _fake_settings(model)
        )
        llm = clients.get_qwen_standard()
        kwargs = self._bound_kwargs(llm.with_structured_output(Out))
        # langchain 默认 json_schema → response_format
        assert "response_format" in kwargs
