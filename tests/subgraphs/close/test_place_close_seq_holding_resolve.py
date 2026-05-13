"""close.place_close 序号→持仓 orderId 解析测试 (P0-B from Round 3 eval)。

Round 3 eval 暴露问题：raw_text 用 "序号1平300万" 引用持仓时，LLM 没有真持仓数据可用，
会胡编 placeholder（如 "ORDER_ID_FROM_HOLDING_MAP_WITH..."、"<resolved_order_id_from_holding>"、
"序号1的orderId"）。结果是渲染卡里"合约编号"/"单号"字段是占位文字，用户无法确认。

修复策略：
1. 当 raw_text 含"序号N"/"第N笔" → 优先用持仓数据按位置覆盖 LLM 的占位 orderId / contractCode。
2. 持仓数据从已有的 OptionClient.query_close_orders 调用获取（空过滤 → 真后端返回当前持仓）。
3. placeholder 检测：orderId 不符合 CO-yyyymmdd-XXXX 格式 OR 含明显占位关键词。
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.close import place_close as pc_module
from app.subgraphs.close.models import CloseOrderItem, ClosePlaceParams
from app.subgraphs.close.place_close import close_place_close
from app.tools.models import CommonResult


def _patch_llm(
    monkeypatch: pytest.MonkeyPatch, params: ClosePlaceParams
) -> AsyncMock:
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=params)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(pc_module, "get_qwen_thinking", lambda: fake_base)
    return fake_llm.ainvoke


def _patch_query_close_orders(
    monkeypatch: pytest.MonkeyPatch, holdings: list[dict[str, Any]]
) -> None:
    """patch OptionClientHttpx.query_close_orders 返回固定持仓数据。"""
    async def _fake_query(self, order_ids=None, contract_codes=None):  # type: ignore[no-untyped-def]
        return CommonResult(code=0, msg="ok", data=holdings)

    monkeypatch.setattr(
        "app.subgraphs.close.place_close.OptionClientHttpx.query_close_orders",
        _fake_query,
    )


@pytest.mark.asyncio
class TestSeqHoldingResolution:
    """序号 X → 持仓数据按位置（seq 1-indexed）解析。"""

    async def test_seq1_placeholder_replaced_by_real_holding(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LLM 返回 placeholder orderId + 持仓 seq=1 数据 → 应使用真 orderId/contractCode。"""
        holdings = [
            {
                "orderId": "CO-20260506-85AB8526",
                "contractCode": "OPT-LYAFT20260001",
                "underlyingCode": "300750.SZ",
                "underlyingName": "宁德时代",
                "optionType": "欧式看涨",
            },
        ]
        _patch_query_close_orders(monkeypatch, holdings)

        # LLM 凭空生成 placeholder（模拟 Round 3 eval 的失败行为）
        params = ClosePlaceParams(
            closeOrderList=[
                CloseOrderItem(
                    orderId="ORDER_ID_FROM_HOLDING_MAP_WITH_SEQ_1",
                    closeOrderNotionalDelta="3000000",
                    closeOrderType="市价单",
                ),
            ]
        )
        _patch_llm(monkeypatch, params)

        result = await close_place_close(
            {"raw_text": "序号1平300万 不用跟量，正常挂单"}
        )
        reply = result.get("reply_text") or ""
        assert "CO-20260506-85AB8526" in reply, (
            f"应使用持仓中 seq=1 的真单号，实际 reply:\n{reply}"
        )
        assert "OPT-LYAFT20260001" in reply, (
            f"应使用持仓中 seq=1 的真合约编号，实际 reply:\n{reply}"
        )
        assert "ORDER_ID_FROM_HOLDING_MAP" not in reply, (
            f"LLM 占位 placeholder 必须被覆盖，实际 reply:\n{reply}"
        )

    async def test_seq2_uses_second_holding(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """raw_text "序号2" → 应取第 2 条持仓。"""
        holdings = [
            {"orderId": "CO-20260506-AAAA0001", "contractCode": "OPT-AAA001"},
            {"orderId": "CO-20260506-BBBB0002", "contractCode": "OPT-BBB002"},
            {"orderId": "CO-20260506-CCCC0003", "contractCode": "OPT-CCC003"},
        ]
        _patch_query_close_orders(monkeypatch, holdings)

        params = ClosePlaceParams(
            closeOrderList=[
                CloseOrderItem(
                    orderId="<resolved_order_id_from_holding>",
                    closeOrderNotionalDelta="2000000",
                    closeOrderType="市价单",
                ),
            ]
        )
        _patch_llm(monkeypatch, params)

        result = await close_place_close({"raw_text": "序号2平200万"})
        reply = result.get("reply_text") or ""
        assert "CO-20260506-BBBB0002" in reply, (
            f"应使用 seq=2 的真单号，实际 reply:\n{reply}"
        )
        assert "OPT-BBB002" in reply

    async def test_real_order_id_in_text_not_overridden(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """raw_text 含真实 CO- 单号 → LLM 输出已是合法格式 → 不应被位置映射覆盖。"""
        holdings = [
            {"orderId": "CO-20260506-XXXX0001", "contractCode": "OPT-XXX001"},
        ]
        _patch_query_close_orders(monkeypatch, holdings)

        params = ClosePlaceParams(
            closeOrderList=[
                CloseOrderItem(
                    orderId="CO-20260506-XXXX0001",  # LLM 已正确填好
                    closeOrderNotionalDelta="3000000",
                    closeOrderType="市价单",
                ),
            ]
        )
        _patch_llm(monkeypatch, params)

        result = await close_place_close(
            {"raw_text": "平 CO-20260506-XXXX0001 300万"}
        )
        reply = result.get("reply_text") or ""
        assert "CO-20260506-XXXX0001" in reply

    async def test_placeholder_blanked_when_no_holding_data(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """无可用持仓数据时 → LLM placeholder 必须被清空，避免污染回复。"""
        _patch_query_close_orders(monkeypatch, [])  # 后端返回空持仓

        params = ClosePlaceParams(
            closeOrderList=[
                CloseOrderItem(
                    orderId="ORDER_ID_FROM_HOLDING_MAP_WITH_PLACEHOLDER",
                    closeOrderNotionalDelta="3000000",
                    closeOrderType="POV",
                    closeOrderPovRatio=25,
                ),
            ]
        )
        _patch_llm(monkeypatch, params)

        result = await close_place_close({"raw_text": "序号1平300万pov25"})
        reply = result.get("reply_text") or ""
        assert "ORDER_ID_FROM_HOLDING_MAP" not in reply, (
            f"无持仓数据时 placeholder 必须被清空，实际 reply:\n{reply}"
        )
        assert "<resolved_order_id" not in reply
        assert "的orderId" not in reply

    async def test_multi_seq_legs_resolved_independently(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """多 leg "序号1留 300 万，序号2全平" → 分别按 seq 解析。"""
        holdings = [
            {"orderId": "CO-20260506-FIRST0001", "contractCode": "OPT-FIRST"},
            {"orderId": "CO-20260506-SECND0002", "contractCode": "OPT-SECND"},
        ]
        _patch_query_close_orders(monkeypatch, holdings)

        params = ClosePlaceParams(
            closeOrderList=[
                CloseOrderItem(
                    orderId="序号1的orderId",
                    closeOrderNotionalDelta="3000000",
                ),
                CloseOrderItem(
                    orderId="序号2的orderId",
                    confirmFullClose=True,
                ),
            ]
        )
        _patch_llm(monkeypatch, params)

        result = await close_place_close(
            {"raw_text": "序号1留 300 万，序号2全平，全部最大跟量"}
        )
        reply = result.get("reply_text") or ""
        assert "CO-20260506-FIRST0001" in reply
        assert "CO-20260506-SECND0002" in reply
