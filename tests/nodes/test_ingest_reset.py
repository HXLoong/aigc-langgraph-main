"""ingest 节点：每轮重置 per-turn 输出（reply_text/api_result/error）。

Round 10 eval trace 暴露：多轮 case 中，turn 4 正确路由到 close_cancel_close，但
最终 reply_text 显示的是 turn 3 的旧消息"互换订单已确认提交..."。原因是
LangGraph 在 checkpoint 模式下，前一轮的 reply_text 会被恢复进当前轮的初始 state，
render 检测到 state.reply_text 非空就直接 return {} 跳过渲染，旧 reply_text 留着。

修复：ingest 节点显式重置 per-turn 输出字段，确保每轮从干净状态开始。
"""
from __future__ import annotations

import pytest

from app.nodes.ingest import ingest


@pytest.mark.asyncio
class TestIngestPerTurnReset:
    """ingest 重置上一轮残留的 per-turn 输出。"""

    async def test_ingest_clears_reply_text(self) -> None:
        """state.reply_text 残留 → ingest 输出应包含 reply_text=None。"""
        state: dict = {
            "raw_text": "撤单",
            "reply_text": "上一轮残留的旧回复",
        }
        update = await ingest(state)  # type: ignore[arg-type]
        # 应该显式包含 reply_text=None
        assert "reply_text" in update, "ingest 必须重置 reply_text"
        assert update["reply_text"] is None, (
            f"reply_text 应清空为 None，实际: {update.get('reply_text')!r}"
        )

    async def test_ingest_clears_api_result(self) -> None:
        """state.api_result/api_code 残留 → ingest 重置。"""
        state: dict = {
            "raw_text": "下一轮新指令",
            "api_result": "旧的后端响应",
            "api_code": 0,
        }
        update = await ingest(state)  # type: ignore[arg-type]
        assert update.get("api_result") is None
        assert update.get("api_code") is None

    async def test_ingest_clears_error(self) -> None:
        """state.error 残留（上一轮某节点 fail）→ ingest 重置。"""
        from app.graph.state import ErrorInfo
        state: dict = {
            "raw_text": "继续",
            "error": ErrorInfo(node="x", type="Y", message="z"),
        }
        update = await ingest(state)  # type: ignore[arg-type]
        assert update.get("error") is None

    async def test_ingest_resets_business_objects_but_keeps_memory(self) -> None:
        """ADR 0024 D2：业务对象是 per-turn 的——上一轮残留的 place_params / cancel_params /
        close_params 会被 render 当本轮结果渲染成"已收到撤单请求"（状态串线）。
        ingest 统一清空；跨轮记忆只保留 history_messages（与入口字段 conversation_id 等）。"""
        state: dict = {
            "raw_text": "确认下单",
            "tickers": ["dummy_ticker"],
            "place_params": {"orderList": [{}]},
            "expected_action": "place",
            "cancel_params": {"cancelOrderNoList": ["H-1"]},
            "history_messages": ["msg1"],
            "conversation_id": "conv-001",
        }
        update = await ingest(state)  # type: ignore[arg-type]
        for key in (
            "tickers", "expected_action", "place_params", "cancel_params", "confirm", "query_filter",
            "close_params", "ticker_hitl_candidates", "swap_counterparty_picks", "swap_ticker_picks",
        ):
            assert key in update and update[key] is None, key
        assert "history_messages" not in update
        assert "conversation_id" not in update
        assert "last_confirmed_params" not in update, "ConversationMemory 跨轮保留"

    async def test_ingest_resets_trace_for_new_turn(self) -> None:
        """一轮的边界只在 ingest 维护：trace 用 Overwrite 清空上一轮，再记本轮 ingest。"""
        from langgraph.types import Overwrite

        update = await ingest({"raw_text": "x", "trace": ["stale-entry"]})  # type: ignore[arg-type]
        assert isinstance(update["trace"], Overwrite)
        assert [e.node for e in update["trace"].value] == ["ingest"]


@pytest.mark.asyncio
async def test_ingest_overrides_previous_turn_reply_text() -> None:
    """checkpoint 里残留的上一轮 reply_text 必须被 ingest 显式置空（真实两轮走图的验证在
    tests/test_api_turn_inputs.py 与 tests/test_smoke.py；这里只钉 ingest 自己的输出）。"""
    update = await ingest({"raw_text": "撤单", "reply_text": "上一轮残留的旧回复"})  # type: ignore[arg-type]
    assert update["reply_text"] is None
