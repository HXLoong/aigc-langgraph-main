"""模型前的只读上下文准备不依赖任何模型分类结果。"""
from __future__ import annotations

import importlib
import importlib.util


def _module():
    """先证明缺少前置上下文准备，再实现节点。"""
    assert importlib.util.find_spec("app.nodes.prepare_parse_context") is not None, "缺少模型前的上下文准备"
    return importlib.import_module("app.nodes.prepare_parse_context")


async def test_close_context_is_loaded_from_explicit_reference_before_parse(monkeypatch) -> None:
    """按引用中的订单号读取上下文，保留原始余额供同一次模型解析。"""
    module = _module()
    requests = []

    async def query(self, **kwargs):
        """替换 HTTP 边界并记录查询范围。"""
        requests.append(kwargs)
        return {"code": 0, "data": [{"orderId": "CO-20260928-AABBCCDD", "availableNotional": 1234567.89}]}

    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.query_close_orders", query)
    result = await module.prepare_parse_context({"product_type": "option_close", "raw_text": "第一笔，平一半",
        "quote_content": "序号：1\n单号：CO-20260928-AABBCCDD", "room_id": "room", "message_id": 1})
    assert requests[0]["order_ids"] == ["CO-20260928-AABBCCDD"]
    assert result["parse_context"]["orders"][0]["availableNotional"] == 1234567.89


async def test_other_products_do_not_query_close_orders(monkeypatch) -> None:
    """无平仓依据时不会为了通用解析预读所有订单。"""
    module = _module()

    async def forbidden(self, **kwargs):
        """不允许扩大无关查询范围。"""
        raise AssertionError("不应查询平仓订单")

    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.query_close_orders", forbidden)
    result = await module.prepare_parse_context({"product_type": "option", "raw_text": "期权询价"})
    assert not result.get("error") and not result.get("parse_context", {}).get("orders")
