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

    async def test_ingest_preserves_business_state(self) -> None:
        """业务字段（tickers/history_messages/conversation_id 等）不该被 ingest 清除。"""
        state: dict = {
            "raw_text": "确认下单",
            "tickers": ["dummy_ticker"],
            "history_messages": ["msg1"],
            "conversation_id": "conv-001",
        }
        update = await ingest(state)  # type: ignore[arg-type]
        # tickers / history_messages / conversation_id 不应出现在 update 里
        # （ingest 不动业务对象，保留原值）
        assert "tickers" not in update
        assert "history_messages" not in update
