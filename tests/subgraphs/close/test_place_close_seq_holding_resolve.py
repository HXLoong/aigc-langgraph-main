"""close.place_close 序号→持仓 orderId 解析测试 (P0-B from Round 3 eval)。

Round 3 eval 暴露问题：raw_text 用 "序号1平300万" 引用持仓时，LLM 没有真持仓数据可用，
会胡编 placeholder（如 "ORDER_ID_FROM_HOLDING_MAP_WITH..."、"<resolved_order_id_from_holding>"、
"序号1的orderId"）。结果是发给真后端的 closeOrderReqVO 里 orderId 是占位文字，后端无法处理。

修复策略：
1. 当 raw_text 含"序号N"/"第N笔" → 优先用持仓数据按位置覆盖 LLM 的占位 orderId / contractCode。
2. 持仓数据从已有的 OptionClient.query_close_orders 调用获取（空过滤 → 真后端返回当前持仓）。
3. placeholder 检测：orderId 不符合 CO-yyyymmdd-XXXX 格式 OR 含明显占位关键词。

工程重构（对齐新 Dify DSL close_order_request 5 步链路）：place_close 不再本地拼
"确认卡"文案，而是把清洗后的 closeOrderList 提交真后端（`financial-orders/operate`），
`reply_text`/`api_result` 由后端返回（CLAUDE.md P0：不得掩盖后端真实响应）。因此本文件
断言从"reply 文案含真单号"改为"提交给后端的 closeOrderReqVO.closeOrderList 含真单号（不含
placeholder）"+ "api_result 与真后端返回逐字节一致（verbatim passthrough）"。
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.close import place_close as pc_module
from app.subgraphs.close.models import CloseOrderItem, ClosePlaceParams
from app.subgraphs.close.place_close import close_place_close


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
    async def _fake_query(self, order_ids=None, contract_codes=None, **kwargs):  # type: ignore[no-untyped-def]
        # kwargs 吸收 room_id/message_id(DSL v2「获取订单信息」payload 对齐)
        return {"code": 0, "msg": "ok", "data": holdings}

    monkeypatch.setattr(
        "app.subgraphs.close.place_close.OptionClientHttpx.query_close_orders",
        _fake_query,
    )


def _patch_operate(
    monkeypatch: pytest.MonkeyPatch, *, api_result: str = "mock-backend-result"
) -> MagicMock:
    """patch OptionClientHttpx.operate，捕获发送的 req 供断言，并回传固定 api_result。"""
    captured: MagicMock = MagicMock()

    async def _fake_operate(self, req):  # type: ignore[no-untyped-def]
        captured(req)
        return {"code": 0, "msg": "ok", "data": api_result}

    monkeypatch.setattr(
        "app.subgraphs.close.place_close.OptionClientHttpx.operate", _fake_operate
    )
    return captured


def _full_context(raw_text: str) -> dict[str, Any]:
    """call_close_backend 要求 conversation_id/room_id/user_id 均非空才会真调用。"""
    return {
        "raw_text": raw_text,
        "conversation_id": "t-seq",
        "user_id": "u-seq",
        "room_id": "r-seq",
        "message_id": 1,
    }


def _sent_close_order_list(captured: MagicMock) -> list[dict[str, Any]]:
    req = captured.call_args[0][0]
    return req.close_order_req_vo.model_dump()["closeOrderList"]


@pytest.mark.asyncio
class TestDirectContractResolution:
    async def test_contract_id_preserved_when_query_has_no_order_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """首次按合约平仓时，orderId 由 operate 创建，查询阶段允许为空。"""
        contract_code = "OPT-SZZSCF20260001"
        _patch_query_close_orders(
            monkeypatch,
            [{"orderId": None, "contractCode": contract_code}],
        )
        captured = _patch_operate(monkeypatch)
        _patch_llm(
            monkeypatch,
            ClosePlaceParams(
                closeOrderList=[
                    CloseOrderItem(orderId=None, internalTradeId=contract_code)
                ]
            ),
        )

        result = await close_place_close(
            _full_context(f"我想平掉 {contract_code}")
        )

        assert result.get("error") is None
        sent = _sent_close_order_list(captured)
        assert sent[0]["orderId"] is None
        assert sent[0]["internalTradeId"] == contract_code

    async def test_explicit_contract_restored_when_llm_uses_placeholder_order_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """单合约首次平仓以用户原文为准，不向后端发送 LLM 订单号占位文字。"""
        contract_code = "OPT-SZZSCF20260001"
        _patch_query_close_orders(
            monkeypatch,
            [{"orderId": None, "contractCode": contract_code}],
        )
        captured = _patch_operate(monkeypatch)
        _patch_llm(
            monkeypatch,
            ClosePlaceParams(
                closeOrderList=[
                    CloseOrderItem(
                        orderId="ORDER_ID_FROM_CONTRACT_QUERY",
                        internalTradeId=None,
                    )
                ]
            ),
        )

        result = await close_place_close(
            _full_context(f"我想平掉 {contract_code}")
        )

        assert result.get("error") is None
        sent = _sent_close_order_list(captured)
        assert sent[0]["orderId"] is None
        assert sent[0]["internalTradeId"] == contract_code

    async def test_contract_id_preserved_when_sequence_query_has_no_order_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """序号查询尚无 orderId 时，也不能清空已有的合法合约编号。"""
        contract_code = "OPT-SZZSCF20260001"
        _patch_query_close_orders(
            monkeypatch,
            [{"orderId": None, "contractCode": contract_code}],
        )
        captured = _patch_operate(monkeypatch)
        _patch_llm(
            monkeypatch,
            ClosePlaceParams(
                closeOrderList=[
                    CloseOrderItem(
                        orderId="ORDER_ID_FROM_HOLDING_MAP_WITH_SEQ_1",
                        internalTradeId=contract_code,
                        closeOrderNotionalDelta="2000000",
                    )
                ]
            ),
        )

        result = await close_place_close(
            _full_context("序号1平200万，合约编号 OPT-SZZSCF20260001")
        )

        assert result.get("error") is None
        sent = _sent_close_order_list(captured)
        assert sent[0]["orderId"] is None
        assert sent[0]["internalTradeId"] == contract_code

    async def test_full_close_preserves_llm_execution_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """全平 leg 不追加默认值，也不清空 LLM 已识别的执行参数。"""
        contract_code = "OPT-SZZSCF20260001"
        _patch_query_close_orders(
            monkeypatch,
            [{"orderId": None, "contractCode": contract_code}],
        )
        captured = _patch_operate(monkeypatch)
        _patch_llm(
            monkeypatch,
            ClosePlaceParams(
                closeOrderList=[
                    CloseOrderItem(
                        orderId=None,
                        internalTradeId=contract_code,
                        closeOrderType="POV",
                        closeOrderPovRatio=25,
                        confirmFullClose=True,
                    )
                ]
            ),
        )

        result = await close_place_close(
            _full_context(f"{contract_code} 全平")
        )

        assert result.get("error") is None
        sent = _sent_close_order_list(captured)
        assert sent[0]["closeOrderType"] == "POV"
        assert sent[0]["closeOrderPovRatio"] == 25
        assert sent[0]["confirmFullClose"] is True


@pytest.mark.asyncio
class TestSeqHoldingResolution:
    """序号 X → 持仓数据按位置（seq 1-indexed）解析。"""

    async def test_seq1_placeholder_replaced_by_real_holding(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LLM 返回 placeholder orderId + 持仓 seq=1 数据 → 提交后端时应使用真 orderId。"""
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
        captured = _patch_operate(monkeypatch)

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
            _full_context("序号1平300万 不用跟量，正常挂单")
        )
        assert result.get("error") is None
        sent = _sent_close_order_list(captured)
        assert sent[0]["orderId"] == "CO-20260506-85AB8526", (
            f"应使用持仓中 seq=1 的真单号提交后端，实际提交:\n{sent}"
        )
        assert sent[0]["internalTradeId"] == "OPT-LYAFT20260001"
        assert "ORDER_ID_FROM_HOLDING_MAP" not in str(sent), (
            f"LLM 占位 placeholder 必须被覆盖，实际提交:\n{sent}"
        )
        # P0：后端真实响应逐字节透传，不做本地二次加工
        assert result.get("api_result") == "mock-backend-result"

    async def test_sequence_uses_contract_id_when_query_has_no_order_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """按序号首次平仓时，查询结果中的合约编号足以提交 operate。"""
        contract_code = "OPT-LYAFT20260001"
        _patch_query_close_orders(
            monkeypatch,
            [{"orderId": None, "contractCode": contract_code}],
        )
        captured = _patch_operate(monkeypatch)
        _patch_llm(
            monkeypatch,
            ClosePlaceParams(
                closeOrderList=[
                    CloseOrderItem(
                        orderId="ORDER_ID_FROM_HOLDING_MAP_WITH_SEQ_1",
                        closeOrderNotionalDelta="2000000",
                    )
                ]
            ),
        )

        result = await close_place_close(_full_context("序号1平200万"))

        assert result.get("error") is None
        sent = _sent_close_order_list(captured)
        assert sent[0]["orderId"] is None
        assert sent[0]["internalTradeId"] == contract_code

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
        captured = _patch_operate(monkeypatch)

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

        result = await close_place_close(_full_context("序号2平200万"))
        assert result.get("error") is None
        sent = _sent_close_order_list(captured)
        assert sent[0]["orderId"] == "CO-20260506-BBBB0002", (
            f"应使用 seq=2 的真单号提交后端，实际提交:\n{sent}"
        )

    async def test_real_order_id_in_text_not_overridden(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """raw_text 含真实 CO- 单号 → LLM 输出已是合法格式 → 不应被位置映射覆盖。"""
        holdings = [
            {"orderId": "CO-20260506-XXXX0001", "contractCode": "OPT-XXX001"},
        ]
        _patch_query_close_orders(monkeypatch, holdings)
        captured = _patch_operate(monkeypatch)

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
            _full_context("平 CO-20260506-XXXX0001 300万")
        )
        assert result.get("error") is None
        sent = _sent_close_order_list(captured)
        assert sent[0]["orderId"] == "CO-20260506-XXXX0001"

    async def test_unresolved_placeholder_does_not_call_backend(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """序号无法解析且无合约编号时，不得向后端提交无身份平仓明细。"""
        _patch_query_close_orders(monkeypatch, [])
        captured = _patch_operate(monkeypatch)

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

        result = await close_place_close(_full_context("序号1平300万pov25"))

        assert result.get("error") is None
        assert result["reply_text"] == "未能识别平仓目标，请提供合约编号或持仓序号。"
        captured.assert_not_called()

    async def test_multi_seq_legs_resolved_independently(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """多 leg "序号1留 300 万，序号2全平" → 分别按 seq 解析。"""
        holdings = [
            {"orderId": "CO-20260506-FIRST0001", "contractCode": "OPT-FIRST"},
            {"orderId": "CO-20260506-SECND0002", "contractCode": "OPT-SECND"},
        ]
        _patch_query_close_orders(monkeypatch, holdings)
        captured = _patch_operate(monkeypatch)

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
            _full_context("序号1留 300 万，序号2全平，全部最大跟量")
        )
        assert result.get("error") is None
        sent = _sent_close_order_list(captured)
        sent_by_id = {leg["orderId"]: leg for leg in sent}
        assert set(sent_by_id) == {"CO-20260506-FIRST0001", "CO-20260506-SECND0002"}
        assert sent_by_id["CO-20260506-FIRST0001"]["closeOrderType"] == "POV"
        assert sent_by_id["CO-20260506-FIRST0001"]["closeOrderPovRatio"] == 25
        assert sent_by_id["CO-20260506-SECND0002"]["confirmFullClose"] is True
        assert sent_by_id["CO-20260506-SECND0002"]["closeOrderType"] is None
        assert sent_by_id["CO-20260506-SECND0002"]["closeOrderPovRatio"] is None
