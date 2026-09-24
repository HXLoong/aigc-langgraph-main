"""普通期权询价：原文候选 → 归一化 → Java 询价。"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.option import extract_inquiry as ei_module
from app.subgraphs.option.extract_inquiry import (
    InquiryOutput,
    build_inquiry_graph,
    option_extract_inquiry,
)
from app.subgraphs.option.models import OptionInquiryRawItem, OptionInquiryRawParams
from tests.evidence_support import candidate_output

STAGES = {
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
    assert set(builder.nodes) == STAGES
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
@pytest.mark.parametrize(("raw", "fragment"), [("600519.SH 看跌 1M 80%", "看跌"), ("600519.SH put 1M 80%", "put")])
async def test_unsupported_option_type_replies_without_backend(
    monkeypatch: pytest.MonkeyPatch, raw: str, fragment: str
) -> None:
    """看跌等不支持的类型给出明确回复，不以校验异常落入兜底文案，也不调 Java。"""
    _patch_llm(monkeypatch, OptionInquiryRawParams(orderList=[OptionInquiryRawItem(
        stockCode="600519.SH", optionType=fragment, tenor="1M", strikePercentage="80%",
    )]))
    backend = AsyncMock()
    monkeypatch.setattr(ei_module, "call_option_backend", backend)

    out = await option_extract_inquiry({"raw_text": raw})

    assert out.get("error") is None
    assert fragment in out["reply_text"] and "欧式看涨" in out["reply_text"]
    backend.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw", "fields", "label"),
    [
        ("600519.SH 欧式看涨 1M 执行价八十", {"strikePercentage": "八十"}, "执行价"),
        ("600519.SH 欧式看涨 1M 80% 本金1,000,000", {"strikePercentage": "80%", "notionalAmount": "1,000,000"}, "名义本金"),
        ("600519.SH 参与型看涨 1M 80% 参与率高", {"strikePercentage": "80%", "participationRate": "高"}, "参与率"),
    ],
)
async def test_unparseable_given_parameter_replies_without_backend(
    monkeypatch: pytest.MonkeyPatch, raw: str, fields: dict[str, str], label: str
) -> None:
    """用户明确给出但无法解析的询价参数与期限同口径：提示修正，不静默置空后询价。"""
    option_type = "参与型看涨" if "参与型" in raw else "欧式看涨"
    _patch_llm(monkeypatch, OptionInquiryRawParams(orderList=[OptionInquiryRawItem(
        stockCode="600519.SH", optionType=option_type, tenor="1M", **fields,
    )]))
    backend = AsyncMock()
    monkeypatch.setattr(ei_module, "call_option_backend", backend)

    out = await option_extract_inquiry({"raw_text": raw})

    assert out.get("error") is None
    assert label in out["reply_text"]
    backend.assert_not_awaited()
