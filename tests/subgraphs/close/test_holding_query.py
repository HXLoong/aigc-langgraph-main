"""持仓查询只向 Java 传当前明确过滤条件。"""
from unittest.mock import AsyncMock

import pytest

from app.subgraphs.close.holding_query import close_holding_query
from tests.joint_support import instruction_data


@pytest.mark.parametrize("query,fields,expected", [
    ({}, [], {}),
    ({"closeable_only": False}, [{"path": "query.closeable_only", "origin": "raw", "text": "查全部持仓"}], {"allowCloseOut": False}),
    ({"underlyingInsNameList": ["茅台"]}, [{"path": "query.underlyingInsNameList.0", "origin": "raw", "text": "茅台"}], {"underlyingInsNameList": ["茅台"]}),
])
async def test_current_filters_reach_java_without_defaults(monkeypatch, query, fields, expected):
    """过滤字段仅作 wire 映射，不强行补可平仓范围或对手哨兵值。"""
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "Java holdings"})
    monkeypatch.setattr("app.subgraphs.close.holding_query.prepare_close_request", backend)
    raw = "查全部持仓，茅台"
    parsed = instruction_data("option_close", "close_order_query", raw, query=query)
    parsed["fields"] = fields
    result = await close_holding_query({"raw_text": raw, "parsed_instruction": parsed})
    assert not result.get("error"), result
    assert backend.await_args.kwargs["close_order_req_vo"] == {"contractQuery": expected}
    assert result["api_result"] == "Java holdings"
