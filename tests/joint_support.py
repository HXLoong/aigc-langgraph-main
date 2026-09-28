"""联合解析测试的模型出口替身；只替换外部调用，生产来源检查保持开启。"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from app.parsing.models import (
    CloseInstruction,
    CrossProductInstruction,
    OptionInstruction,
    SwapInstruction,
    UnknownInstruction,
)


def instruction_data(product: str, intent: str, raw: str, *, orders: list[dict[str, Any]] | None = None,
                     quote: str = "", **extra: Any) -> dict[str, Any]:
    """建立明确的模型样本；身份与证券引用可来自 quote，其余证据取当前消息。"""
    fields = []
    for index, order in enumerate(orders or []):
        for name, value in order.items():
            if value is None:
                continue
            quoted = name in {"orderId", "internalTradeId", "stockCode", "placeOrderWindCode"} and str(value) not in raw and str(value) in quote
            fields.append({"path": f"orders.{index}.{name}", "origin": "quote" if quoted else "raw",
                           "text": str(value) if quoted else raw})
    return {"product_type": product, "intent": intent, "confidence": 0.9,
            "evidence": [{"origin": "raw", "text": raw}], "orders": orders or [], "fields": fields, **extra}


def joint_model(product: str, intent: str, *, orders: list[dict[str, Any]] | None = None,
                calls: list[Any] | None = None) -> SimpleNamespace:
    """每次从真实提示词提取原文，避免测试关闭或伪造来源校验。"""
    def structured(schema: Any) -> SimpleNamespace:
        """由实际 PromptSpec 决定单产品或跨产品输出形状。"""
        async def invoke(messages: Any, **kwargs: Any) -> Any:
            """返回测试明确给出的语义结果，不模拟业务节点内部逻辑。"""
            if calls is not None:
                calls.append(messages)
            source = json.loads(messages[-1][1])["sources"]
            raw, quote = source.get("raw", ""), source.get("quote", "")
            selected_product = product
            if product == "unknown" and schema is not CrossProductInstruction:
                selected_product = {OptionInstruction: "option", SwapInstruction: "swap", CloseInstruction: "option_close"}[schema]
            data = instruction_data(selected_product, intent, raw, orders=orders, quote=quote)
            if selected_product == "unknown":
                data.pop("orders")
            model = {"option": OptionInstruction, "swap": SwapInstruction,
                     "option_close": CloseInstruction, "unknown": UnknownInstruction}[selected_product]
            result = model.model_validate(data)
            return CrossProductInstruction(instruction=result) if schema is CrossProductInstruction else result
        return SimpleNamespace(ainvoke=invoke)
    return SimpleNamespace(with_structured_output=structured)
