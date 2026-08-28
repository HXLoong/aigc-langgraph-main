"""POST /v1/workflows/run — 兼容 Dify Workflow Run API（ADR 0001 D3）。

设计要点：
- Body: {inputs: {...}, response_mode: "blocking", user: "<conversation_id>"}
- Response: Dify 协议形态 — {workflow_run_id, task_id, data: {outputs, status, ...}}
- 仅支持 blocking 模式（Java StockBotMessageServiceImpl.java:1646 写死 blocking）
- inputs 字段透传 9 个机器人上下文 + raw_text
- outputs 字段含 intent / product_type / 业务对象（M1 阶段含 stub 数据）
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.graph.state import AgentState
from app.observability.metrics import emit_intent_latency

router = APIRouter()


# ============================================================
# Dify Workflow Run API 请求/响应 schema
# ============================================================


class DifyWorkflowRunRequest(BaseModel):
    """Dify Workflow Run API 请求体（POST /v1/workflows/run）。"""

    model_config = ConfigDict(extra="allow")

    inputs: dict[str, Any] = Field(default_factory=dict)
    response_mode: Literal["blocking", "streaming"] = "blocking"
    user: str  # Java 侧传 conversation_id


class DifyWorkflowRunData(BaseModel):
    """Dify response.data 字段。"""

    model_config = ConfigDict(extra="allow")

    id: str
    workflow_id: str = "otc-agent-langgraph"
    status: Literal["succeeded", "failed", "stopped"] = "succeeded"
    outputs: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    elapsed_time: float = 0.0
    total_tokens: int = 0
    total_steps: int = 0
    created_at: int = 0
    finished_at: int = 0


class DifyWorkflowRunResponse(BaseModel):
    """Dify Workflow Run API 响应。"""

    model_config = ConfigDict(extra="allow")

    workflow_run_id: str
    task_id: str
    data: DifyWorkflowRunData


# ============================================================
# 路由
# ============================================================


@router.post("/v1/workflows/run", response_model=DifyWorkflowRunResponse)
async def run_workflow(
    req: DifyWorkflowRunRequest, request: Request
) -> DifyWorkflowRunResponse:
    """模拟 Dify 的 Workflow Run API，把请求路由到 LangGraph 主图。"""
    if req.response_mode != "blocking":
        raise HTTPException(
            status_code=400,
            detail="Only blocking mode is supported (ADR 0001 D3).",
        )

    # 从 app.state 取主图（在 lifespan 创建并注入）
    graph = request.app.state.main_graph
    if graph is None:
        raise HTTPException(status_code=503, detail="Main graph not initialized")

    workflow_run_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    created_at = int(time.time())

    # 把 inputs 解构成 AgentState（按 contracts §2.1 §3.1 的 9 个机器人上下文字段）
    initial_state = _inputs_to_state(req.inputs, fallback_conversation_id=req.user)

    # ADR 0004/#156：单次调用关联 ID——node_trace.trace_id 与 LangFuse trace metadata 同源
    trace_id = uuid.uuid4().hex
    initial_state["trace_id"] = trace_id

    config = _build_run_config(conversation_id=req.user, trace_id=trace_id)

    t0 = time.perf_counter()
    try:
        final_state: AgentState = await graph.ainvoke(initial_state, config=config)
        status: Literal["succeeded", "failed", "stopped"] = (
            "failed" if final_state.get("error") else "succeeded"
        )
        error_msg = (
            final_state["error"].message if final_state.get("error") else None
        )
    except Exception as exc:  # noqa: BLE001
        final_state = {}
        status = "failed"
        error_msg = f"{type(exc).__name__}: {exc}"

    elapsed = time.perf_counter() - t0
    # #157 裁决：端到端 P95 数据源（ADR 0017/0019 退出门与 p95_latency_degraded 告警）
    # 无 node label —— alerts 侧以此与节点级样本区分
    emit_intent_latency(
        product_type=final_state.get("product_type") or "unknown",
        intent=final_state.get("intent") or "unknown",
        elapsed_ms=int(elapsed * 1000),
    )
    finished_at = int(time.time())

    outputs = _state_to_outputs(final_state)

    data = DifyWorkflowRunData(
        id=workflow_run_id,
        status=status,
        outputs=outputs,
        error=error_msg,
        elapsed_time=elapsed,
        total_steps=len(final_state.get("trace", [])),
        created_at=created_at,
        finished_at=finished_at,
    )
    return DifyWorkflowRunResponse(
        workflow_run_id=workflow_run_id, task_id=task_id, data=data
    )


# ============================================================
# Helpers
# ============================================================


#: 图递归上限(架构体检 2026-08 改进 A):现图均为 DAG,50 为防御纵深上限;
#: 未来引入循环子图时按 CLAUDE.md 指引单独收紧(复杂子图 25)
GRAPH_RECURSION_LIMIT = 50


def _build_run_config(conversation_id: str, trace_id: str) -> dict:
    """构造 graph.ainvoke 的 RunnableConfig(thread 绑定 + trace 关联 + 递归上限)。"""
    return {
        "configurable": {"thread_id": conversation_id},
        "metadata": {"trace_id": trace_id},
        "recursion_limit": GRAPH_RECURSION_LIMIT,
    }


# Dify inputs 字段名（Java 透传）→ AgentState 字段名 映射
# DSL v2（2026-08 主干工作流 start 节点）新增:fast_query / at_bot /
# existing_command / bot_name / operator_user_id / option_counterparties /
# swap_counterparties;旧 9 字段保留兼容（userId/messageContent 仍接受）。
_INPUT_FIELD_MAP = {
    "rawContent": "raw_text",
    "raw_content": "raw_text",
    "conversationId": "conversation_id",
    "conversation_id": "conversation_id",
    "messageId": "message_id",
    "message_id": "message_id",
    "userId": "user_id",
    "roomId": "room_id",
    "room_id": "room_id",
    "guid": "guid",
    "messageContent": "message_content",
    "quoteContent": "quote_content",
    "quote_content": "quote_content",
    "quoteAppinfo": "quote_appinfo",
    "quote_appinfo": "quote_appinfo",
    # -------- DSL v2 新入参 --------
    "fast_query": "fast_query",
    "fastQuery": "fast_query",
    "at_bot": "at_bot",
    "atBot": "at_bot",
    "existing_command": "existing_command",
    "existingCommand": "existing_command",
    "bot_name": "bot_name",
    "botName": "bot_name",
    "operator_user_id": "operator_user_id",
    "operatorUserId": "operator_user_id",
    # 对手预查 JSON 串（pre_route 解析成精简列表）
    "option_counterparties": "option_counterparties_raw",
    "optionCounterparties": "option_counterparties_raw",
    "swap_counterparties": "swap_counterparties_raw",
    "swapCounterparties": "swap_counterparties_raw",
    # 输入文件（Dify sys.files 等价物;全图片/全 Excel 分流互换多模态链）
    "files": "input_files",
    "sysFiles": "input_files",
}


def _inputs_to_state(
    inputs: dict[str, Any], fallback_conversation_id: str
) -> AgentState:
    """把 Dify inputs 转成 AgentState（接受 camelCase 和 snake_case 两种）。"""
    state: dict[str, Any] = {}
    for src, dst in _INPUT_FIELD_MAP.items():
        if src in inputs:
            state[dst] = inputs[src]

    # 补默认值
    if "conversation_id" not in state:
        state["conversation_id"] = fallback_conversation_id
    if "raw_text" not in state and "message_content" in state:
        state["raw_text"] = state["message_content"]
    return state  # type: ignore[return-value]


def _state_to_outputs(state: AgentState) -> dict[str, Any]:
    """把 final state 渲染成 Dify outputs schema。"""
    outputs: dict[str, Any] = {
        "intent": state.get("intent"),
        "product_type": state.get("product_type"),
        "tickers": [
            t.model_dump() if hasattr(t, "model_dump") else t
            for t in state.get("tickers", [])
        ],
    }
    # M1 阶段：业务对象用 dict 占位，直接 dump
    for key in (
        "place_params",
        "cancel_params",
        "confirm",
        "query_filter",
        "close_params",
        "ticker_hitl_candidates",
        "reply_text",
    ):
        v = state.get(key)
        if v is not None:
            outputs[key] = v
    return outputs


# /health 与 /ready 已迁至 app/api/health.py（D2.6 / Issue #72）
