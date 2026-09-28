"""唯一业务模型节点：同时识别产品、单一意图、参数与选择证据。"""
from __future__ import annotations

import json
from typing import Any

from app.config import get_settings
from app.extraction.fields import EvidenceError
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_llm_standard
from app.nodes.intent_route import resolve_product_hint
from app.parsing.evidence import verify_instruction
from app.parsing.models import (
    CloseInstruction,
    CrossProductInstruction,
    OptionInstruction,
    SwapInstruction,
    UnknownInstruction,
)
from app.parsing.prompts import SPECS


@safe_node
async def parse_instruction(state: AgentState) -> dict[str, Any]:
    """选择一套契约并请求一次；结构或来源错误沿 cascade 返回，不修复重试。"""
    # 1. 上游错误或明确入口回复直接收尾，空输入无需消耗模型额度。
    if state.get("error") or state.get("reply_text"):
        return {}
    if not (state.get("raw_text") or "").strip() and not state.get("attachment_sources"):
        return {"product_type": "unknown", "intent": "unknown_intent", "parsed_instruction": None}
    product, _ = resolve_product_hint(state)
    spec = SPECS[product]
    messages, prompt_name = spec.build_messages({**state, "product_type": product})
    schema = spec.output_model
    assert schema is not None

    # 2. 所有消息和 schema 计入预算；超限时整体退出，不切分订单或附件。
    payload = json.dumps({"messages": messages, "schema": schema.model_json_schema()}, ensure_ascii=False)
    if len(payload.encode("utf-8")) > get_settings().llm_input_max_bytes:
        return {"product_type": "unknown", "intent": "unknown_intent", "parsed_instruction": None,
                "reply_text": "输入内容超出单次解析容量，请减少本次文本或 Excel 内容后重新发送。"}
    output = await get_llm_standard().with_structured_output(schema).ainvoke(messages)
    parsed = schema.model_validate(output)
    if isinstance(parsed, CrossProductInstruction):
        instruction = parsed.instruction
    elif isinstance(parsed, (OptionInstruction, SwapInstruction, CloseInstruction, UnknownInstruction)):
        instruction = parsed
    else:
        raise TypeError("解析配置未声明受支持的产品契约")

    # 3. 校验所有字段来源与附件覆盖，再把同一结果交给确定性业务子图。
    records = verify_instruction(instruction, state)
    expected_rows = state.get("attachment_rows") or []
    if len(instruction.attachment_rows) != len(expected_rows) or set(instruction.attachment_rows) != set(expected_rows):
        raise EvidenceError("Excel 数据行覆盖不完整，请减少内容后重新提交")
    # 行声明必须有实际字段证据支撑，防止模型仅回显行 ID 却漏掉订单。
    referenced_rows = {
        item.reference.removeprefix("attachment:").split(":column:", 1)[0]
        for item in instruction.fields
        if item.origin == "attachment" and item.reference
    }
    if not set(expected_rows).issubset(referenced_rows):
        raise EvidenceError("Excel 数据行缺少提取字段，请减少内容后重新提交")
    return {
        "product_type": instruction.product_type, "intent": instruction.intent,
        "parsed_instruction": {
            **instruction.model_dump(by_alias=True, exclude_none=True, exclude_unset=True),
            "product_type": instruction.product_type,
        },
        "field_records": records,
        "trace": [TraceEntry(node="parse_instruction", decision=f"{instruction.product_type}/{instruction.intent}",
                             llm_output={"prompt_name": prompt_name, "parser": spec.key})],
    }
