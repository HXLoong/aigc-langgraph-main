"""POST /v1/workflows/run — 兼容 Dify Workflow Run API（ADR 0001 D3）。

设计要点：
- Body: {conversation_id?: "...", inputs: {...}, response_mode: "blocking", user: "..."}
- Response: Dify 协议形态 + Java 顶层字段
  {workflow_run_id, task_id, conversationId, answer, data: {outputs, status, ...}}
- 仅支持 blocking 模式（Java StockBotMessageServiceImpl.java:1646 写死 blocking）
- inputs 字段透传 9 个机器人上下文 + raw_text
- outputs 字段含 intent / product_type / 业务对象（M1 阶段含 stub 数据）
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings
from app.graph.state import AgentState
from app.observability.metrics import emit_intent_latency

router = APIRouter()
logger = logging.getLogger(__name__)


# ============================================================
# Dify Workflow Run API 请求/响应 schema
# ============================================================


class DifyWorkflowRunRequest(BaseModel):
    """Dify Workflow Run API 请求体（POST /v1/workflows/run）。"""

    model_config = ConfigDict(extra="allow")

    inputs: dict[str, Any] = Field(default_factory=dict)
    conversation_id: str | None = Field(
        default=None, description="Java 会话 ID；非空时原样复用，兼容 inputs 中的两种别名",
    )
    response_mode: Literal["blocking", "streaming"] = "blocking"
    user: str  # 调用方的稳定用户标识；不作为 LangGraph conversation_id


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

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    workflow_run_id: str
    task_id: str
    conversation_id: str = Field(alias="conversationId")
    answer: str
    data: DifyWorkflowRunData


# ============================================================
# 路由
# ============================================================


@router.post(
    "/v1/workflows/run",
    response_model=DifyWorkflowRunResponse,
    responses={502: {"description": "消息会话与意图写回 Java 失败，不返回正常 answer"}},
)
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

    # 把 inputs 解构成 AgentState（按 contracts §2.1 §3.1 的 9 个机器人上下文字段）
    try:
        initial_state = _inputs_to_state(req.inputs)
        conversation_id = _resolve_conversation_id(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # 所有兼容位置均为空才生成一次纯 UUID；已有 ID 不做任何格式转换。
    if conversation_id is None:
        conversation_id = str(uuid.uuid4())
    initial_state["conversation_id"] = conversation_id

    workflow_run_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    created_at = int(time.time())

    # Dify 顶层 user 会成为工作流内的 sys.user_id；Java 业务接口也把它
    # 作为客户唯一 ID。显式 inputs.userId/user_id 非空时仍保持最高优先级。
    user_id = str(initial_state.get("user_id") or "").strip()
    if not user_id:
        initial_state["user_id"] = req.user.strip()

    # ADR 0004/#156：每次调用保留独立的 node_trace 关联 ID；测试工作台可另行
    # 把多轮调用挂到同一个 LangFuse 父 Trace，不改变业务审计粒度。
    request_trace_id = uuid.uuid4().hex
    initial_state["trace_id"] = request_trace_id

    config = _build_run_config(
        conversation_id=conversation_id, trace_id=request_trace_id
    )
    incoming_traceparent = (
        request.headers.get("traceparent")
        if conversation_id.startswith("ai-test-")
        else None
    )
    trace_handler, trace_url, langfuse_trace_id = await _development_langfuse_trace(
        request_trace_id, incoming_traceparent
    )
    if trace_handler is not None:
        config["callbacks"] = [trace_handler]

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

    # 必须等图完成：persist 已记录 set-intent 的失败 trace 后才返回 502。
    # 使用固定文案，不透传后端响应、URL、鉴权信息或异常堆栈。
    error = final_state.get("error")
    if error is not None and error.node == "persist_intent":
        raise HTTPException(
            status_code=502, detail="消息会话与意图持久化失败，请稍后重试。",
        )

    outputs = _state_to_outputs(final_state)
    if trace_handler is not None:
        outputs["trace_id"] = langfuse_trace_id
    if trace_url:
        outputs["trace_url"] = trace_url

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
        workflow_run_id=workflow_run_id,
        task_id=task_id,
        conversation_id=conversation_id,
        answer=final_state.get("reply_text") or "",
        data=data,
    )


# ============================================================
# Helpers
# ============================================================


#: 图递归上限(架构体检 2026-08 改进 A):现图均为 DAG,50 为防御纵深上限;
#: 未来引入循环子图时按 CLAUDE.md 指引单独收紧(复杂子图 25)
GRAPH_RECURSION_LIMIT = 50


_TRACEPARENT_RE = re.compile(
    r"^00-(?P<trace_id>[0-9a-f]{32})-(?P<span_id>[0-9a-f]{16})-[0-9a-f]{2}$"
)


def _parse_traceparent(value: str | None) -> tuple[str, str] | None:
    """解析测试工作台发送的 W3C traceparent。"""
    match = _TRACEPARENT_RE.fullmatch(value or "")
    if match is None:
        return None
    trace_id = match.group("trace_id")
    span_id = match.group("span_id")
    if trace_id == "0" * 32 or span_id == "0" * 16:
        return None
    return trace_id, span_id


async def _development_langfuse_trace(
    request_trace_id: str, traceparent: str | None
) -> tuple[Any | None, str | None, str]:
    """开发环境创建请求 Trace，或接入测试工作台的用例级父 Trace。"""
    settings = get_settings()
    if (
        settings.environment != "development"
        or not settings.enable_langfuse
        or not settings.langfuse_public_key
        or not settings.langfuse_secret_key
    ):
        return None, None, request_trace_id

    parent_context = _parse_traceparent(traceparent)
    langfuse_trace_id = parent_context[0] if parent_context else request_trace_id
    trace_context = {"trace_id": langfuse_trace_id}
    if parent_context:
        trace_context["parent_span_id"] = parent_context[1]

    try:
        from langfuse import Langfuse
        from langfuse.langchain import CallbackHandler

        client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_base_url,
        )
        handler = CallbackHandler(
            public_key=settings.langfuse_public_key,
            trace_context=trace_context,
        )
    except Exception as exc:  # noqa: BLE001 - tracing 失败不阻断业务
        logger.warning("development LangFuse trace unavailable: %s", exc)
        return None, None, request_trace_id

    if parent_context:
        return handler, None, langfuse_trace_id
    try:
        trace_url = await asyncio.to_thread(
            client.get_trace_url, trace_id=langfuse_trace_id
        )
    except Exception as exc:  # noqa: BLE001 - 链接失败不影响 trace 上报
        logger.warning("development LangFuse trace link unavailable: %s", exc)
        trace_url = None
    return handler, trace_url, langfuse_trace_id


def _build_run_config(conversation_id: str, trace_id: str) -> dict:
    """构造 graph.ainvoke 的 RunnableConfig(thread 绑定 + trace 关联 + 递归上限)。"""
    return {
        "configurable": {"thread_id": conversation_id},
        "metadata": {"trace_id": trace_id},
        "recursion_limit": GRAPH_RECURSION_LIMIT,
    }


# Dify inputs 字段名（Java 透传）→ AgentState 字段名 映射
_INPUT_FIELD_ALIASES = {
    "raw_text": ("rawContent", "raw_content"),
    "message_id": ("messageId", "message_id"),
    "user_id": ("userId", "user_id"),
    "room_id": ("roomId", "room_id"),
    "guid": ("guid",),
    "message_content": ("messageContent", "message_content"),
    "quote_content": ("quoteContent", "quote_content"),
    "quote_appinfo": ("quoteAppinfo", "quote_appinfo"),
    "fast_query": ("fast_query", "fastQuery"),
    "at_bot": ("at_bot", "atBot"),
    "existing_command": ("existing_command", "existingCommand"),
    "bot_name": ("bot_name", "botName"),
    "operator_user_id": ("operator_user_id", "operatorUserId"),
    "option_counterparties_raw": ("option_counterparties", "optionCounterparties"),
    "swap_counterparties_raw": ("swap_counterparties", "swapCounterparties"),
    "input_files": ("files", "sysFiles"),
}


def _resolve_conversation_id(req: DifyWorkflowRunRequest) -> str | None:
    """会话 ID 为不透明字符串：仅判空，非空值按原文比较并保留。"""
    resolved: str | None = None
    for location, value in (
        ("conversation_id", req.conversation_id),
        ("inputs.conversationId", req.inputs.get("conversationId")),
        ("inputs.conversation_id", req.inputs.get("conversation_id")),
    ):
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"conversation_id 必须为字符串: {location}")
        if not value.strip():
            continue
        if resolved is not None and value != resolved:
            raise ValueError("conversation_id 的非空值冲突")
        resolved = value
    return resolved


def _inputs_to_state(inputs: dict[str, Any]) -> AgentState:
    """把 Dify inputs 转成 AgentState（接受 camelCase 和 snake_case 两种）。"""
    state: dict[str, Any] = {}
    for target, aliases in _INPUT_FIELD_ALIASES.items():
        provided = [(alias, inputs[alias]) for alias in aliases if alias in inputs]
        if not provided:
            continue

        first_alias, first_value = provided[0]
        conflicting_aliases = [
            alias for alias, value in provided[1:] if value != first_value
        ]
        if conflicting_aliases:
            alias_names = ", ".join([first_alias, *conflicting_aliases])
            raise ValueError(f"输入字段 {target} 的别名值冲突: {alias_names}")

        state[target] = first_value

    if "raw_text" not in state and "message_content" in state:
        state["raw_text"] = state["message_content"]
    return state  # type: ignore[return-value]


def _format_trace(trace: list[Any]) -> str:
    """把逐节点 trace 压成 `node[decision] → ...` 单行字符串。"""
    parts: list[str] = []
    for entry in trace:
        if isinstance(entry, dict):
            node, decision = entry.get("node", "?"), entry.get("decision")
        else:
            node, decision = getattr(entry, "node", "?"), getattr(entry, "decision", None)
        parts.append(f"{node}[{decision}]" if decision else str(node))
    return " → ".join(parts)


def _state_to_outputs(state: AgentState) -> dict[str, Any]:
    """把 final state 渲染成 Dify outputs schema。"""
    outputs: dict[str, Any] = {
        "intent": state.get("intent"),
        "product_type": state.get("product_type"),
        "tickers": [
            t.model_dump() if hasattr(t, "model_dump") else t
            for t in state.get("tickers", [])
        ],
        "trace": _format_trace(state.get("trace", [])),
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
        "api_code",
        "api_result",
    ):
        v = state.get(key)
        if v is not None:
            outputs[key] = v
    return outputs


# /health 与 /ready 已迁至 app/api/health.py（D2.6 / Issue #72）
