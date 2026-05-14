"""infer_code event-loop 线程安全 TDD 测试。

根因 v2：_llm_infer 在 _run_async 里调 asyncio.run(coroutine)，
anyio 在主 loop 初始化后绑定了 loop 的 asyncio 原语（Event/Lock），
sub-thread 的新 loop 里复用这些原语导致 "is bound to a different event loop"。

修复：_llm_infer 切换成 llm.invoke()（同步 HTTP，无 asyncio），
在独立线程中运行以不阻塞主 event loop。
"""
from __future__ import annotations

from unittest.mock import MagicMock


def test_make_qwen_thinking_factory_exists():
    """clients.py 必须提供不带 @lru_cache 的 make_qwen_thinking() 工厂。"""
    from app.llm import clients
    assert callable(getattr(clients, "make_qwen_thinking", None)), (
        "需要在 clients.py 中添加 make_qwen_thinking()（无 lru_cache）"
    )


def test_infer_code_uses_sync_invoke_not_ainvoke(monkeypatch):
    """_llm_infer 必须使用 llm.invoke()（同步），不得使用 llm.ainvoke()（异步）。

    用 spy 验证：
    - make_qwen_thinking 返回的 llm.invoke（sync）被调用
    - llm.ainvoke 未被调用（无 asyncio.run 在子线程跑 async coroutine）
    """
    import app.subgraphs.ticker.tools as tools_mod

    mock_resp = MagicMock()
    mock_resp.content = "<result>600519.SH</result>"
    mock_llm = MagicMock()
    mock_llm.invoke = MagicMock(return_value=mock_resp)  # sync invoke

    make_calls: list[int] = []

    def _mock_make():
        make_calls.append(1)
        return mock_llm

    monkeypatch.setattr(tools_mod, "make_qwen_thinking", _mock_make, raising=False)
    monkeypatch.setattr(tools_mod, "_get_dynamic_prompt_cached", lambda: "")

    # Spy: get_qwen_thinking（lru_cache 单例）不应被调用
    get_calls: list[int] = []
    orig = getattr(tools_mod, "get_qwen_thinking", None)
    if orig is not None:
        monkeypatch.setattr(
            tools_mod, "get_qwen_thinking", lambda: (get_calls.append(1) or orig())
        )

    result = tools_mod.infer_code.invoke({"keyword": "茅台"})

    assert make_calls, "_llm_infer 应调用 make_qwen_thinking()"
    assert not get_calls, "_llm_infer 不应调用 lru_cached get_qwen_thinking()"
    assert mock_llm.invoke.called, "_llm_infer 必须调用 llm.invoke()（同步）"
    assert not mock_llm.ainvoke.called, "_llm_infer 不得调用 llm.ainvoke()（异步）"
    assert "600519" in str(result)
