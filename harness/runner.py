"""Runner — 跑单 case 通过 LangGraph 主图（ADR 0014 D5）。

职责：
- 把 GoldenCase 转成 initial AgentState
- 调 build_main_graph() 编译主图（M1 不传 checkpointer）
- 注册 LangFuse callback handler（如果启用）
- 返回 final_state + 失败定位所需的元数据
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.graph.main import build_main_graph
from harness.golden import GoldenCase
from harness.langfuse_client import get_callback_handler

logger = logging.getLogger(__name__)


class RunResult(BaseModel):
    """单 case 跑完的结果，供 differ + reporter 消费。"""

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    case: GoldenCase
    final_state: dict[str, Any] = Field(default_factory=dict)
    elapsed_ms: int = 0
    error: str | None = None


def _case_to_initial_state(case: GoldenCase) -> dict[str, Any]:
    """GoldenCase → AgentState 初始字典。"""
    cid = f"harness-{case.id}"
    state: dict[str, Any] = {
        "raw_text": case.raw_content,
        "conversation_id": cid,
        "message_id": 1,
        "message_content": case.raw_content,
        "user_id": "harness-user",
        "room_id": "harness-room",
    }
    if case.quote_content:
        state["quote_content"] = case.quote_content
    return state


async def run_case(
    case: GoldenCase,
    graph: Any | None = None,
) -> RunResult:
    """跑一条 case 的端到端。"""
    if graph is None:
        graph = build_main_graph()

    initial = _case_to_initial_state(case)

    config: dict[str, Any] = {
        "configurable": {"thread_id": initial["conversation_id"]},
    }

    handler = get_callback_handler()
    if handler is not None:
        config["callbacks"] = [handler]
        # 给 LangFuse trace 加业务标签便于过滤
        config.setdefault("metadata", {}).update(
            {
                "harness_case_id": case.id,
                "harness_category": case.category,
                "harness_run_id": str(uuid.uuid4()),
            }
        )

    t0 = time.perf_counter()
    try:
        final_state = await graph.ainvoke(initial, config=config)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        err = final_state.get("error")
        err_str: str | None = None
        if err is not None:
            err_str = (
                f"{err.type}: {err.message}"
                if hasattr(err, "type")
                else str(err)
            )

        return RunResult(
            case=case,
            final_state=_normalize_state(final_state),
            elapsed_ms=elapsed_ms,
            error=err_str,
        )
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        logger.exception("case=%s harness exception", case.id)
        return RunResult(
            case=case,
            final_state={},
            elapsed_ms=elapsed_ms,
            error=f"{type(exc).__name__}: {exc}",
        )


def _normalize_state(state: dict[str, Any]) -> dict[str, Any]:
    """把 final_state 里的 Pydantic 对象转成 dict（供 JSON 报告序列化）。"""
    out: dict[str, Any] = {}
    for k, v in state.items():
        out[k] = _to_jsonable(v)
    return out


def _to_jsonable(v: Any) -> Any:
    if hasattr(v, "model_dump"):
        return v.model_dump(mode="json")
    if isinstance(v, list):
        return [_to_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {k: _to_jsonable(x) for k, x in v.items()}
    return v
