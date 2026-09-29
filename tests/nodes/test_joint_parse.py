"""联合解析一次返回完整语义，不在产品子图再次请求模型。"""
from __future__ import annotations

import importlib
import importlib.util
from types import SimpleNamespace

import pytest

from app.parsing.models import CrossProductInstruction, OptionInstruction


def _node():
    """对尚未实现的节点给出明确失败。"""
    assert importlib.util.find_spec("app.nodes.parse_instruction") is not None, "缺少一次联合解析节点"
    return importlib.import_module("app.nodes.parse_instruction")


@pytest.mark.parametrize("product", ["option", "unknown"])
async def test_one_parse_returns_product_intent_and_orders(monkeypatch, product: str) -> None:
    """明确产品与跨产品解析都在一次结果中携带意图及接口参数。"""
    module = _node()
    calls = []
    result = OptionInstruction.model_validate({
        "product_type": "option", "intent": "new_inquiry", "confidence": 0.9,
        "evidence": [{"origin": "raw", "text": "询价"}],
        "orders": [{"stockCode": "茅台"}],
        "fields": [{"path": "orders.0.stockCode", "origin": "raw", "text": "茅台"}],
    })

    def structured(schema):
        """替换唯一外部模型边界，提示词和来源检查仍使用真实实现。"""
        async def invoke(messages):
            """保留请求次数和实际 PromptSpec 输出类型。"""
            calls.append(schema)
            return CrossProductInstruction(instruction=result) if schema is CrossProductInstruction else result
        return SimpleNamespace(ainvoke=invoke)

    monkeypatch.setattr(module, "get_llm_standard", lambda: SimpleNamespace(with_structured_output=structured))
    update = await module.parse_instruction({"raw_text": "茅台询价", "product_type": product})
    assert update.get("error") is None
    assert update["product_type"] == "option" and update["intent"] == "new_inquiry"
    assert update["parsed_instruction"]["orders"] == [{"stockCode": "茅台"}]
    assert len(calls) == 1


async def test_parse_error_does_not_request_repair(monkeypatch) -> None:
    """模型请求失败直接返回 E1，不修复输出或请求备用模型。"""
    import openai

    module = _node()
    calls = []

    async def invoke(messages):
        """记录唯一请求后模拟模型超时。"""
        calls.append(messages)
        raise openai.APITimeoutError(request=SimpleNamespace())

    monkeypatch.setattr(module, "get_llm_standard", lambda: SimpleNamespace(
        with_structured_output=lambda _: SimpleNamespace(ainvoke=invoke),
    ))
    update = await module.parse_instruction({"raw_text": "茅台询价", "product_type": "option"})
    assert update["error"].code == "E1" and len(calls) == 1


async def test_excel_echoed_row_list_cannot_hide_omitted_orders(monkeypatch) -> None:
    """仅回显全部行 ID 不等于完整抽取，遗漏行没有字段证据时停止提交。"""
    module = _node()
    first, second = "file:0:sheet:0:row:2", "file:0:sheet:0:row:3"
    result = OptionInstruction.model_validate({
        "product_type": "option", "intent": "new_inquiry", "confidence": 0.9,
        "evidence": [{"origin": "raw", "text": "期权询价"}],
        "orders": [{"stockCode": "茅台"}], "attachment_rows": [first, second],
        "fields": [{"path": "orders.0.stockCode", "origin": "attachment",
                    "reference": "attachment:" + first + ":column:A", "text": "茅台"}],
    })

    async def invoke(messages):
        """模拟一次模型结果包含完整行声明但只提取首行。"""
        return result

    monkeypatch.setattr(module, "get_llm_standard", lambda: SimpleNamespace(
        with_structured_output=lambda _: SimpleNamespace(ainvoke=invoke)))
    update = await module.parse_instruction({
        "raw_text": "期权询价", "product_type": "option", "attachment_rows": [first, second],
        "attachment_sources": {first + ":column:A": "茅台", second + ":column:A": "平安"},
    })
    assert update.get("error") is not None
    assert update["error"].code == "E2"
    assert not update.get("parsed_instruction")


async def test_unknown_parameter_is_not_silently_discarded(monkeypatch) -> None:
    """模型返回未声明业务字段时必须结构失败，不能丢字段后提交剩余参数。"""
    from tests.joint_support import instruction_data

    module = _node()
    raw = "期权询价茅台100万"
    payload = instruction_data("option", "new_inquiry", raw, orders=[{"stockCode": "茅台"}])
    payload["orders"][0]["notionalAmout"] = "1000000"

    async def invoke(messages):
        """保留拼错的原始模型字段，让真实 Pydantic 边界处理。"""
        return payload

    monkeypatch.setattr(module, "get_llm_standard", lambda: SimpleNamespace(
        with_structured_output=lambda _: SimpleNamespace(ainvoke=invoke)))
    result = await module.parse_instruction({"raw_text": raw})
    assert result.get("error") and result["error"].code == "E2"
    assert not result.get("parsed_instruction")
