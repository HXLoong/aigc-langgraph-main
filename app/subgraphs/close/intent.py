"""平仓入口复用一次联合解析结果，不再进行模型意图识别。"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.parsing.evidence import verify_instruction
from app.parsing.models import CloseInstruction


@safe_node
async def close_intent(state: AgentState) -> dict[str, Any]:
    """校验平仓产品与来源，沿已有意图路由进入确定性节点。"""
    if state.get("error"):
        return {}
    parsed = CloseInstruction.model_validate(state.get("parsed_instruction") or {})
    return {"intent": parsed.intent, "field_records": verify_instruction(parsed, state),
            "trace": [TraceEntry(node="close_intent", decision=f"parsed→{parsed.intent}")]}
