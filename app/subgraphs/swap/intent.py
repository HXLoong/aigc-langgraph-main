"""互换入口检查联合解析结果，意图不再由子图重新识别。"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.parsing.evidence import verify_instruction
from app.parsing.models import SwapInstruction


@safe_node
async def swap_intent(state: AgentState) -> dict[str, Any]:
    """检查来源并沿已识别意图分发，始终不调用模型。"""
    if state.get("error"):
        return {}
    parsed = SwapInstruction.model_validate(state.get("parsed_instruction") or {})
    return {"intent": parsed.intent, "field_records": verify_instruction(parsed, state),
            "trace": [TraceEntry(node="swap_intent", decision=f"parsed→{parsed.intent}")]}
