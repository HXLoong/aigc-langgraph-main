"""产品路由只给联合解析提供提示，不消耗模型请求。"""
from unittest.mock import MagicMock

import pytest

from app.llm.clients import _ChatLLM
from app.nodes.intent_route import intent_route


@pytest.mark.parametrize("raw,quote,expected", [
    ("撤掉 H-20260101-0000000001", "", "swap"),
    ("Q-20260101-0000000001 确认", "", "option"),
    ("OPTG-SZZSCF20250030 全部平掉", "", "option_close"),
    ("确认下单", "Q-20260101-0000000001", "option"),
    ("随便说点什么完全无关的", "", "unknown"),
])
async def test_product_hint_is_deterministic(monkeypatch, raw, quote, expected):
    """订单、引用与明确规则决定提示，歧义留给唯一联合模型。"""
    model = MagicMock(side_effect=AssertionError("产品路由不得调用模型"))
    monkeypatch.setattr(_ChatLLM, "with_structured_output", model)
    result = await intent_route({"raw_text": raw, "quote_content": quote})
    assert result["product_type"] == expected
    model.assert_not_called()


async def test_excel_does_not_force_swap_product():
    """附件可以属于所有产品，不能靠文件后缀强制落互换。"""
    result = await intent_route({"input_files": [{"type": "document", "extension": ".xlsx"}]})
    assert result["product_type"] == "unknown"
