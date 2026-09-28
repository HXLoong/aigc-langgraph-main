"""联合解析保留接口值与原文来源，不在代码中重算业务数值。"""
from __future__ import annotations

import importlib
import importlib.util
from typing import Any

import pytest


def _modules() -> tuple[Any, Any]:
    """缺少新契约时给出明确 RED，不依赖导入异常。"""
    assert importlib.util.find_spec("app.parsing") is not None, "缺少联合解析契约"
    return importlib.import_module("app.parsing.models"), importlib.import_module("app.parsing.evidence")


def _option() -> dict[str, Any]:
    """接口数值与原文不同，但保留同一条用户证据。"""
    return {"product_type": "option", "intent": "new_inquiry", "confidence": 0.9,
        "evidence": [{"text": "询价", "origin": "raw"}],
        "orders": [{"stockCode": "茅台", "notionalAmount": "1000000"}],
        "fields": [
            {"path": "orders.0.stockCode", "text": "茅台", "origin": "raw"},
            {"path": "orders.0.notionalAmount", "text": "100万", "origin": "raw"},
        ]}


def test_wire_value_is_retained_without_numeric_recalculation() -> None:
    """数值语义由联合提取给出，代码只验证证据来源并建立账本。"""
    models, evidence = _modules()
    parsed = models.OptionInstruction.model_validate(_option())
    records = evidence.verify_instruction(parsed, {"raw_text": "茅台询价100万"})
    assert records["option/parse.orderList.0.notionalAmount"].value == "1000000"
    assert records["option/parse.orderList.0.notionalAmount"].evidence == "100万"
    assert records["option/parse.orderList.0.notionalAmount"].locked


def test_missing_field_evidence_rejects_entire_instruction() -> None:
    """有值而无来源时整体失败，不能漏掉该字段继续提交。"""
    models, evidence = _modules()
    data = _option()
    data["fields"].pop()
    with pytest.raises(ValueError, match="证据"):
        evidence.verify_instruction(models.OptionInstruction.model_validate(data), {"raw_text": "茅台询价100万"})


def test_security_value_cannot_be_invented_from_a_name() -> None:
    """标的必须保持原始表达；模型不能在客户端补成证券代码。"""
    models, evidence = _modules()
    data = _option()
    data["orders"][0]["stockCode"] = "600519.SH"
    with pytest.raises(ValueError, match="标的"):
        evidence.verify_instruction(models.OptionInstruction.model_validate(data), {"raw_text": "茅台询价100万"})


def test_stale_quote_cannot_supply_an_explicit_confirmation_increment() -> None:
    """确认订单的旧参数不能作为本次用户显式增量重新提交。"""
    models, evidence = _modules()
    data = _option()
    data["intent"] = "confirm_order"
    data["evidence"] = [{"text": "确认下单", "origin": "raw"}]
    for item in data["fields"]:
        item["origin"] = "quote"
    with pytest.raises(ValueError, match="本次"):
        evidence.verify_instruction(models.OptionInstruction.model_validate(data), {
            "raw_text": "确认下单", "quote_content": "茅台询价100万",
        })


def test_excel_can_supply_current_intent_evidence_without_text() -> None:
    """仅附件输入也有本次证据，不得强制伪造 raw 文本。"""
    models, evidence = _modules()
    reference = "file:0:sheet:0:row:2:column:A"
    source = "标的: 茅台"
    parsed = models.OptionInstruction.model_validate({
        "product_type": "option", "intent": "new_inquiry", "confidence": 0.9,
        "evidence": [{"origin": "attachment", "reference": "attachment:" + reference, "text": source}],
        "orders": [{"stockCode": "茅台"}],
        "fields": [{"path": "orders.0.stockCode", "origin": "attachment", "reference": "attachment:" + reference, "text": source}],
    })
    records = evidence.verify_instruction(parsed, {"raw_text": "", "attachment_sources": {reference: source}})
    assert records["option/parse.orderList.0.stockCode"].origin == "attachment:" + reference


@pytest.mark.parametrize("product,intent,identity,field,value", [
    ("option", "place_order_from_quote", "Q-20260922-0000000001", "limitPrice", 10),
    ("swap", "place_order_request", "H-20260922-0000000001", "placeOrderPrice", 10),
    ("option_close", "close_order_request", "CO-20260922-ABCDEF12", "closeOrderPrice", 10),
])
def test_existing_order_updates_cannot_copy_old_quoted_parameters(product, intent, identity, field, value):
    """既有订单的补参只提交当前增量，引用旧价格不能进入新 DTO。"""
    from app.extraction.fields import EvidenceError
    from app.parsing.evidence import verify_instruction
    from app.parsing.models import CloseInstruction, OptionInstruction, SwapInstruction
    from tests.joint_support import instruction_data

    schema = {"option": OptionInstruction, "swap": SwapInstruction, "option_close": CloseInstruction}[product]
    raw, quote = "改数量", f"单号：{identity}，原限价10"
    payload = instruction_data(product, intent, raw, orders=[{"orderId": identity, field: value}], quote=quote)
    payload["fields"][1].update(origin="quote", text="原限价10")
    with pytest.raises(EvidenceError):
        verify_instruction(schema.model_validate(payload), {"raw_text": raw, "quote_content": quote})


def test_context_reference_uses_the_exact_key_given_to_model():
    """上下文来源键直接复制，不要求模型删除未声明的类型前缀。"""
    from app.parsing.evidence import verify_instruction
    from app.parsing.models import CloseInstruction

    result = CloseInstruction.model_validate({"intent": "close_order_request", "confidence": .9,
        "evidence": [{"origin": "raw", "text": "OPT-AAAA1"}],
        "orders": [{"orderId": "CO-20260922-ABCDEF12", "internalTradeId": "OPT-AAAA1"}],
        "fields": [{"path": "orders.0.orderId", "origin": "context", "reference": "context:order:0", "text": "CO-20260922-ABCDEF12"},
                   {"path": "orders.0.internalTradeId", "origin": "raw", "text": "OPT-AAAA1"}]})
    records = verify_instruction(result, {"raw_text": "平掉 OPT-AAAA1", "parse_context": {
        "sources": {"context:order:0": '{"orderId":"CO-20260922-ABCDEF12","contractCode":"OPT-AAAA1"}'}}})
    assert records["close/parse.orderList.0.orderId"].origin == "context:order:0"


def test_order_identity_cannot_be_reconstructed_from_history():
    """本次订单目标只能来自当前选择与只读匹配结果，不能从未引用历史补目标。"""
    from app.extraction.fields import EvidenceError
    from app.parsing.evidence import verify_instruction
    from app.parsing.models import CloseInstruction

    result = CloseInstruction.model_validate({"intent": "close_order_request", "confidence": .9,
        "evidence": [{"origin": "raw", "text": "全部平仓"}],
        "orders": [{"internalTradeId": "OPT-OLD"}],
        "fields": [{"path": "orders.0.internalTradeId", "origin": "history", "reference": "history:old", "text": "OPT-OLD"}]})
    with pytest.raises(EvidenceError):
        verify_instruction(result, {"raw_text": "全部平仓", "history_messages": [
            {"id": "old", "role": "assistant", "content": "OPT-OLD"}]})


def test_attachment_only_intent_record_keeps_actual_source():
    """仅 Excel 输入时，汇总意图记录不能被标成并不存在的 raw 原文。"""
    models, evidence = _modules()
    key = "attachment:file:0:sheet:0:row:2:column:A"
    parsed = models.OptionInstruction.model_validate({"intent": "new_inquiry", "confidence": .9,
        "evidence": [{"origin": "attachment", "reference": key, "text": "询价"}]})
    records = evidence.verify_instruction(parsed, {"attachment_sources": {key.removeprefix("attachment:"): "询价"}})
    assert records["option/parse.intent"].origin == key
    assert records["option/parse.intent"].derived_from == ["option/parse.intent.evidence.0"]
