"""本次订单身份可以来自明确单号，历史订单不能代替当前授权。"""
from importlib import import_module
from unittest.mock import AsyncMock

import pytest

from tests.graph.test_confirmation_paths import PATHS
from tests.joint_support import instruction_data


@pytest.mark.parametrize("module_name,node_name,backend_name,intent,action,oid", PATHS)
async def test_explicit_order_confirmation_without_quote(
    monkeypatch, module_name, node_name, backend_name, intent, action, oid,
):
    """明确单号和动作可以独立提交，不强制本地先申请再引用卡片。"""
    module = import_module("app.subgraphs." + module_name)
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "Java receipt"})
    monkeypatch.setattr(module, backend_name, backend)
    raw = f"{oid}，{action}"
    product = "option" if module_name.startswith("option.") else "swap" if module_name.startswith("swap.") else "option_close"
    result = await getattr(module, node_name)({
        "raw_text": raw, "intent": intent,
        "parsed_instruction": instruction_data(product, intent, raw, orders=[{"orderId": oid}]),
    })
    assert not result.get("error"), result
    assert result.get("api_result") == "Java receipt", result
    backend.assert_awaited_once()
    assert all(record.origin != "quote" for record in result.get("field_records", {}).values())


async def test_close_cancel_does_not_reuse_conversation_order(monkeypatch):
    """无本次身份时将空范围交给 Java，不从本地历史挑选最近订单。"""
    module = import_module("app.subgraphs.close.cancel_close")
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "Java receipt"})
    monkeypatch.setattr(module, "prepare_close_request", backend)
    await module.close_cancel_close({"raw_text": "撤单", "conversation_orders": [
        {"orderId": "CO-20260920-ABCDEF12"},
    ]})
    assert backend.await_args.kwargs["close_order_req_vo"]["cancelOrderNoList"] == []
