"""公开 resolver 接口保留用户写出的交易所，固定 LLM 与 HTTP 边界。"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from langchain_core.messages import AIMessage

from app.prompts import load_prompt
from app.subgraphs.ticker import resolver, tools
from app.subgraphs.ticker.resolver import resolve_ticker_full
from app.tools.ticker_client import TickerClientHttpx


@pytest.fixture
def ticker_api(monkeypatch):
    queries = []
    options = {"reverse": False, "wrong_exchange": False}

    async def reply(messages):
        system, user = (message.content for message in messages)
        if system == load_prompt("ticker", "rank").system:
            return AIMessage(content='["000858.SZ", "600519.SH"]')
        candidates = json.loads(user.removeprefix("标的列表："))
        if options["reverse"]:
            candidates.reverse()
        if system == load_prompt("ticker", "judge_type").system:
            data = {value: "EQUITY" for value in candidates}
        else:
            data = {
                value: ([value, value.split(".")[0], "858"] if value.upper().startswith("000858")
                        else ["600519.SH"] if value == "茅台" else [value])
                for value in candidates
            }
        return AIMessage(content=json.dumps(data, ensure_ascii=False))

    llm = MagicMock()
    llm.ainvoke = AsyncMock(side_effect=reply)
    monkeypatch.setattr(tools, "get_qwen_standard", lambda: llm)

    def handle(request):
        assert request.method == "GET"
        keywords = json.loads(request.content)["keywordItems"]
        queries.append(keywords)
        results = []
        for code, name in [("000858.SZ", "五粮液"), ("600519.SH", "贵州茅台")]:
            root = code.split(".")[0]
            if any(item["keyword"].upper() in {code, root, root.lstrip("0"), name}
                   for item in keywords):
                results.append({"windCode": code, "insShtDesc": name})
        if options["wrong_exchange"] and any(item["keyword"].upper() == "000858.SH" for item in keywords):
            results = [{"windCode": "000858.SZ", "insShtDesc": "五粮液"}]
        if any(item["keyword"] == "700.HK" and item["isFull"] for item in keywords):
            results = [{"windCode": "00700.HK", "insShtDesc": "腾讯控股"}]
        return httpx.Response(200, json={"code": 0, "data": results})

    monkeypatch.setattr(resolver, "_make_client", lambda: TickerClientHttpx(
        base_url="http://ticker.test", token="test-only", transport=httpx.MockTransport(handle),
    ))
    return queries, options


async def test_invalid_explicit_exchange_never_resolves_bare_digits(ticker_api):
    result = await resolve_ticker_full("000858.SH")
    assert result.resolved == []


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("raw,expected", [
    ("000858.SH", []),
    ("000858.SH 0858", []),
    ("000858.sh", []),
    ("标的：000858.SH", []),
    ("000858.SZ", ["000858.SZ"]),
    ("000858", ["000858.SZ"]),
    ("000858.SH 600519.SH", ["600519.SH"]),
    ("000858.SH 茅台", ["600519.SH"]),
    ("600519.SH 茅台 600519", ["600519.SH"]),
])
async def test_explicit_code_guard_is_independent_of_llm_order(ticker_api, reverse, raw, expected):
    queries, options = ticker_api
    options["reverse"] = reverse
    result = await resolve_ticker_full(raw)
    assert [ticker.wind_code for ticker in result.resolved] == expected
    assert all(ticker.from_goats is True for ticker in result.resolved)
    assert result.hitl_pending == []
    if "000858." in raw.upper():
        assert all(item["keyword"] not in {"000858", "858"} for query in queries for item in query)
        first = queries[0]
        assert all(item["isFull"] for item in first)
        suffix = raw.upper().split("000858.")[1][:2]
        assert {item["keyword"] for item in first} == {f"000858.{suffix}", f"858.{suffix}"}
    if raw == "600519.SH 茅台 600519":
        assert set(result.resolved[0].source_keywords) == {"600519.SH", "茅台", "600519"}


async def test_backend_wrong_exchange_is_rejected_even_for_full_query(ticker_api):
    _, options = ticker_api
    options["wrong_exchange"] = True
    result = await resolve_ticker_full("000858.SH 600519.SH")
    assert [ticker.wind_code for ticker in result.resolved] == ["600519.SH"]


async def test_valid_full_code_keeps_zero_normalization_and_exchange(ticker_api):
    queries, _ = ticker_api
    result = await resolve_ticker_full("0700.HK")
    assert [ticker.wind_code for ticker in result.resolved] == ["00700.HK"]
    assert all(item["isFull"] and item["keyword"].endswith(".HK") for query in queries for item in query)
