"""原文候选 → 归一化 → Java 询价；快速询价解析为空时回到候选提取。"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from evidence_support import candidate_output

from app.subgraphs.option import extract_inquiry as ei_module
from app.subgraphs.option.extract_inquiry import (
    InquiryOutput,
    build_inquiry_graph,
    option_extract_inquiry,
)
from app.subgraphs.option.models import OptionInquiryRawItem, OptionInquiryRawParams

STAGES = {
    "inquiry_fast_parse", "inquiry_fast_submit",
    "inquiry_extract", "inquiry_normalize", "inquiry_submit",
}


def _patch_llm(monkeypatch: pytest.MonkeyPatch, params: Any) -> None:
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=candidate_output(params))
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(ei_module, "get_qwen_thinking", lambda: fake_base)




def test_topology_has_stage_nodes_and_private_output_schema() -> None:
    builder = build_inquiry_graph().builder
    assert set(builder.nodes) >= STAGES
    assert set(InquiryOutput.__annotations__) >= {"expected_action", "place_params", "reply_text", "api_result", "api_code", "trace", "error"}
    assert not any(k.startswith("iq_") for k in InquiryOutput.__annotations__), "私有中间态不外泄"


@pytest.mark.asyncio
async def test_llm_path_traces_every_stage_and_keeps_summary_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_llm(monkeypatch, OptionInquiryRawParams(orderList=[OptionInquiryRawItem(stockCode="600519.SH", tenor="1M", strikePercentage="80%")]))
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "报价卡"})
    monkeypatch.setattr(ei_module, "call_option_backend", backend)

    out = await option_extract_inquiry({"raw_text": "600519.SH，欧式看涨,1M,80%"})

    nodes = [e.node for e in out["trace"]]
    assert [n for n in nodes if n in STAGES] == ["inquiry_extract", "inquiry_normalize", "inquiry_submit"]
    summary = [e for e in out["trace"] if e.node == "option_extract_inquiry"]
    assert summary and "action=inquiry" in summary[-1].decision
    assert out["expected_action"] == "inquiry" and out["api_result"] == "报价卡"
    assert not any(k.startswith("iq_") for k in out), "私有中间态不外泄"


@pytest.mark.asyncio
async def test_llm_failure_is_attributed_to_extract_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_llm = MagicMock()
    fake_llm.with_structured_output = MagicMock(return_value=MagicMock(ainvoke=AsyncMock(side_effect=RuntimeError("LLM down"))))
    monkeypatch.setattr(ei_module, "get_qwen_thinking", lambda: fake_llm)
    backend = AsyncMock()
    monkeypatch.setattr(ei_module, "call_option_backend", backend)

    out = await option_extract_inquiry({"raw_text": "茅台 欧式看涨 1M"})

    assert out["error"].node == "inquiry_extract" and "LLM down" in out["error"].message
    backend.assert_not_awaited()
    assert "inquiry_submit" not in [e.node for e in out["trace"]]


@pytest.mark.asyncio
async def test_unknown_security_reaches_backend(monkeypatch):
    _patch_llm(monkeypatch, OptionInquiryRawParams(orderList=[OptionInquiryRawItem(stockCode="000000.SZ")]))
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "后端未匹配"})
    monkeypatch.setattr(ei_module, "call_option_backend", backend)
    out = await option_extract_inquiry({"raw_text": "000000.SZ 欧式看涨"})
    assert out["api_result"] == "后端未匹配"
    assert backend.await_args.kwargs["order_list"][0]["stockCode"] == "000000.SZ"
    assert "inquiry_precheck" not in [entry.node for entry in out["trace"]]


@pytest.mark.asyncio
async def test_fast_inquiry_takes_goats_edge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.tools.goats_rfq.parse_rfq_instrument", AsyncMock(return_value={"productType": "雪球", "chatInstrument": "x"}))
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "雪球报价"})
    monkeypatch.setattr(ei_module, "call_option_backend", backend)
    monkeypatch.setattr(ei_module, "get_qwen_thinking", lambda: (_ for _ in ()).throw(AssertionError("不应调 LLM")))

    out = await option_extract_inquiry({"raw_text": "快速询价：雪球 600519.SH 3M"})

    nodes = [e.node for e in out["trace"]]
    assert "inquiry_fast_parse" in nodes and "inquiry_fast_submit" in nodes and "inquiry_extract" not in nodes
    assert backend.await_args.kwargs["option_rfq"]["productType"] == "雪球"
    assert out["api_result"] == "雪球报价" and "place_params" not in out


@pytest.mark.asyncio
async def test_fast_parse_empty_falls_through_to_llm_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.tools.goats_rfq.parse_rfq_instrument", AsyncMock(return_value=None))
    _patch_llm(monkeypatch, OptionInquiryRawParams(orderList=[OptionInquiryRawItem(stockCode="600519.SH")]))
    monkeypatch.setattr(ei_module, "call_option_backend", AsyncMock(return_value={"api_code": 0, "api_result": "卡"}))

    out = await option_extract_inquiry({"raw_text": "参与型看涨 600519.SH 1M"})

    nodes = [e.node for e in out["trace"]]
    assert "inquiry_fast_parse" in nodes and "inquiry_extract" in nodes and "inquiry_submit" in nodes
