"""close.holding_query 节点测试（mock LLM）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.subgraphs.close import holding_query as hq_module
from app.subgraphs.close.holding_query import close_holding_query
from app.subgraphs.close.models import HoldingQueryParams


def _patch_llm(
    monkeypatch: pytest.MonkeyPatch, params: HoldingQueryParams
) -> AsyncMock:
    fake_llm_with_schema = MagicMock()
    fake_llm_with_schema.ainvoke = AsyncMock(return_value=params)
    fake_base_llm = MagicMock()
    fake_base_llm.with_structured_output = MagicMock(
        return_value=fake_llm_with_schema
    )
    monkeypatch.setattr(hq_module, "get_qwen_thinking", lambda: fake_base_llm)
    monkeypatch.setattr(
        hq_module,
        "call_option_backend",
        AsyncMock(return_value={"api_code": 0, "api_result": "backend reply"}),
    )
    return fake_llm_with_schema.ainvoke


# ============================================================
# HoldingQueryParams Pydantic 模型
# ============================================================


class TestHoldingQueryParams:
    def test_minimal_with_only_required_field(self) -> None:
        params = HoldingQueryParams(closeable_only=False)
        assert params.closeable_only is False
        assert params.internalTradeIdList == []
        assert params.underlyingInsNameList == []

    def test_full_fields(self) -> None:
        params = HoldingQueryParams(
            closeable_only=True,
            internalTradeIdList=["OPTG-SZZSCF20250030"],
            keyCtptyIdList=[10049],
            underlyingInsNameList=["贵州茅台"],
            underlyingInsIdList=["600519.SH"],
            insFamilyList=["EQUITY"],
            contractTypeList=["AUTOCALL"],
        )
        assert params.closeable_only is True
        assert params.keyCtptyIdList == [10049]

    def test_invalid_ins_family_rejected(self) -> None:
        with pytest.raises(ValidationError):
            HoldingQueryParams(
                closeable_only=False, insFamilyList=["NOT_A_FAMILY"]
            )  # type: ignore[list-item]

    def test_invalid_contract_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            HoldingQueryParams(
                closeable_only=False, contractTypeList=["NOT_A_CONTRACT"]
            )  # type: ignore[list-item]

    def test_extra_fields_ignored(self) -> None:
        params = HoldingQueryParams.model_validate(
            {"closeable_only": False, "garbage": "x"}
        )
        assert params.closeable_only is False

    def test_missing_required_closeable_only(self) -> None:
        with pytest.raises(ValidationError):
            HoldingQueryParams.model_validate({})


# ============================================================
# 节点端到端（mock LLM）
# ============================================================


@pytest.mark.asyncio
class TestCloseHoldingQueryNode:
    async def test_simple_query_no_filters(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = HoldingQueryParams(closeable_only=False)
        _patch_llm(monkeypatch, params)
        result = await close_holding_query({"raw_text": "我有哪些期权持仓"})
        assert result["close_params"]["closeable_only"] is False
        assert result["close_params"]["underlyingInsNameList"] == []

    async def test_close_intent_with_ticker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = HoldingQueryParams(
            closeable_only=True,
            underlyingInsNameList=["贵州茅台"],
            contractTypeList=["AUTOCALL"],
        )
        _patch_llm(monkeypatch, params)
        result = await close_holding_query(
            {"raw_text": "帮我平掉对手阿凡提的贵州茅台雪球"}
        )
        assert result["close_params"]["closeable_only"] is True
        assert result["close_params"]["underlyingInsNameList"] == ["贵州茅台"]
        assert result["close_params"]["contractTypeList"] == ["AUTOCALL"]

    async def test_writes_trace_with_summary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = HoldingQueryParams(
            closeable_only=True,
            internalTradeIdList=["OPTG-SZZSCF20250030"],
            underlyingInsNameList=["贵州茅台", "腾讯"],
        )
        _patch_llm(monkeypatch, params)
        result = await close_holding_query({"raw_text": "..."})
        trace = result.get("trace", [])
        assert len(trace) == 1
        decision = trace[0].decision
        assert "closeable_only=True" in decision
        assert "tickers=2" in decision  # 2 个标的名称（idList 是空）
        assert "trades=1" in decision

    async def test_safe_node_catches_llm_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_llm = MagicMock()
        fake_llm.with_structured_output = MagicMock(
            return_value=MagicMock(
                ainvoke=AsyncMock(side_effect=RuntimeError("LLM down"))
            )
        )
        monkeypatch.setattr(
            hq_module, "get_qwen_thinking", lambda: fake_llm
        )
        result = await close_holding_query({"raw_text": "x"})
        assert result.get("error") is not None
        assert result["error"].node == "close_holding_query"
