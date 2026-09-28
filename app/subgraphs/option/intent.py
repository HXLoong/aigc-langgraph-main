"""期权入口检查：复用主图的联合解析结果，不再次请求模型。"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.parsing.evidence import verify_instruction
from app.parsing.models import OptionInstruction


@safe_node
async def option_intent(state: AgentState) -> dict[str, Any]:
    """检查产品契约和来源，再按已识别意图分发。"""
    if state.get("error"):
        return {}
    result = OptionInstruction.model_validate(state.get("parsed_instruction") or {})
    records = verify_instruction(result, state)
    return {"intent": result.intent, "field_records": records,
            "trace": [TraceEntry(node="option_intent", decision=f"parsed→{result.intent}")]}
