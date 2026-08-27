"""app/llm/clients.py 工厂的 vendor 适配测试。

背景（ADR 0018）：开发期 Qwen / 现场 DeepSeek-v4-pro 通过 .env 切换。
关闭思考模式的参数两家不同：
- Qwen (dashscope)：extra_body={"enable_thinking": False}
- DeepSeek：extra_body={"thinking": {"type": "disabled"}}
  （DeepSeek 会静默忽略 enable_thinking，导致默认开思考、延迟爆炸）
"""
from __future__ import annotations

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
    )


@pytest.fixture()
def _clear_factory_caches():
    """工厂是 lru_cache 单例，测试前后都要清掉，避免污染其他用例。"""
    for fn in (
        clients.get_qwen_standard,
        clients.get_qwen_thinking,
        clients.get_qwen_structured,
        clients.get_qwen_complex,
    ):
        fn.cache_clear()
    yield
    for fn in (
        clients.get_qwen_standard,
        clients.get_qwen_thinking,
        clients.get_qwen_structured,
        clients.get_qwen_complex,
    ):
        fn.cache_clear()


@pytest.mark.usefixtures("_clear_factory_caches")
class TestFactoryExtraBody:
    """工厂函数在 DeepSeek 模型下应带 DeepSeek 风格的 extra_body。"""

    @pytest.mark.parametrize(
        "factory_name",
        ["get_qwen_standard", "get_qwen_thinking", "get_qwen_structured", "get_qwen_complex"],
    )
    def test_deepseek_model_gets_thinking_disabled(
        self, monkeypatch: pytest.MonkeyPatch, factory_name: str
    ) -> None:
        monkeypatch.setattr(
            clients, "get_settings", lambda: _fake_settings("deepseek-v4-pro")
        )
        llm = getattr(clients, factory_name)()
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

    def test_deepseek_defaults_to_function_calling(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pydantic import BaseModel

        class Out(BaseModel):
            x: int

        monkeypatch.setattr(
            clients, "get_settings", lambda: _fake_settings("deepseek-v4-pro")
        )
        llm = clients.get_qwen_standard()
        kwargs = self._bound_kwargs(llm.with_structured_output(Out))
        assert "tools" in kwargs
        assert "response_format" not in kwargs

    def test_deepseek_explicit_method_respected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pydantic import BaseModel

        class Out(BaseModel):
            x: int

        monkeypatch.setattr(
            clients, "get_settings", lambda: _fake_settings("deepseek-v4-pro")
        )
        llm = clients.get_qwen_standard()
        kwargs = self._bound_kwargs(
            llm.with_structured_output(Out, method="function_calling")
        )
        assert "tools" in kwargs

    def test_qwen_keeps_langchain_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pydantic import BaseModel

        class Out(BaseModel):
            x: int

        monkeypatch.setattr(
            clients, "get_settings", lambda: _fake_settings("qwen3-30b-a3b")
        )
        llm = clients.get_qwen_standard()
        kwargs = self._bound_kwargs(llm.with_structured_output(Out))
        # langchain 默认 json_schema → response_format
        assert "response_format" in kwargs
