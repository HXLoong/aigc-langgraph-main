"""infer_code event-loop 线程安全 TDD 测试。

根因：get_qwen_thinking() 是 @lru_cache 单例，首次在主 loop 创建；
infer_code 在子线程 asyncio.run() 里复用该单例，httpx 连接池被跨 loop
调用/关闭，污染主 loop 的 LLM 客户端，导致 option_extract_inquiry 等
主路径节点随之报 Connection error。

修复：_ainvoke() 使用非缓存工厂 make_qwen_thinking() 每次创建新实例。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock


def test_make_qwen_thinking_factory_exists():
    """clients.py 必须提供不带 @lru_cache 的 make_qwen_thinking() 工厂。"""
    from app.llm import clients
    assert callable(getattr(clients, "make_qwen_thinking", None)), (
        "需要在 clients.py 中添加 make_qwen_thinking()（无 lru_cache）"
    )


def test_infer_code_uses_make_qwen_thinking_not_cached_singleton(monkeypatch):
    """_ainvoke() 必须调用 make_qwen_thinking()，不得调用 get_qwen_thinking()。

    用 spy 验证：patch 后调用 infer_code，确认
    - make_qwen_thinking 返回的 llm.ainvoke 被调用
    - get_qwen_thinking（lru_cache 单例）未被调用
    """
    import app.subgraphs.ticker.tools as tools_mod

    # 给 tools_mod 注入 make_qwen_thinking spy（修复前该属性不存在→ raising=False）
    mock_resp = MagicMock()
    mock_resp.content = "<result>600519.SH</result>"
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=mock_resp)

    make_calls: list[int] = []

    def _mock_make():
        make_calls.append(1)
        return mock_llm

    monkeypatch.setattr(tools_mod, "make_qwen_thinking", _mock_make, raising=False)
    monkeypatch.setattr(tools_mod, "_get_dynamic_prompt_cached", lambda: "")

    # Spy: get_qwen_thinking 在 tools_mod 里不应再被调用
    get_calls: list[int] = []
    orig = getattr(tools_mod, "get_qwen_thinking", None)
    if orig is not None:
        monkeypatch.setattr(tools_mod, "get_qwen_thinking", lambda: (get_calls.append(1) or orig()))

    result = tools_mod.infer_code.invoke({"keyword": "茅台"})

    assert make_calls, "_ainvoke() 应调用 make_qwen_thinking()"
    assert not get_calls, "_ainvoke() 不应调用 lru_cached get_qwen_thinking()"
    assert "600519" in str(result)
