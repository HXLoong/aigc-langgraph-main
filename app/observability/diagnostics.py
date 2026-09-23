"""Safe operational failure details; never include backend payloads or exception text."""
from collections.abc import Mapping
from typing import Any

from app.graph.state import ErrorInfo, TraceEntry

_LABELS = {"E1": "模型调用失败", "E2": "模型输出解析或证据校验失败", "E3": "参数校验失败",
           "E4": "后端或工具调用失败", "E5": "工作流超过总时限"}


def failure_diagnostic(state: Mapping[str, Any]) -> dict[str, Any] | None:
    raw = state.get("error")
    if not raw:
        return None
    error = raw if isinstance(raw, ErrorInfo) else ErrorInfo.model_validate(raw)
    summary = _LABELS[error.code]
    if error.type == "BackendUnreachableError" and "timeout" in error.message.lower():
        summary = "后端调用超时，执行结果待核对"
    elif error.type == "CloseOrderTypeNormalizationError":
        summary = "平仓执行方式无法识别或存在冲突"
    elapsed = None
    for entry in reversed(state.get("trace") or []):
        value = entry.model_dump() if isinstance(entry, TraceEntry) else entry
        if isinstance(value, dict) and value.get("node") == error.node:
            elapsed = value.get("elapsed_ms")
            break
    return {"code": error.code, "node": error.node, "type": error.type,
            "summary": summary, "elapsed_ms": elapsed,
            "causes": [{"code": e.code, "node": e.node, "type": e.type} for e in error.causes]}
