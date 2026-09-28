"""POST /v1/workflows/run — 兼容 Dify Workflow Run API（ADR 0001 D3）。

设计要点：
- Body: {conversation_id?: "...", inputs: {...}, response_mode: "blocking", user: "..."}
- Response: Dify 协议形态 + Java 顶层字段
  {workflow_run_id, task_id, conversationId, answer, data: {outputs, status, ...}}
- 仅支持 blocking 模式（Java StockBotMessageServiceImpl.java:1646 写死 blocking）
- inputs 字段透传 9 个机器人上下文 + raw_text
- outputs 字段含 intent / product_type / 业务对象
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.api.turn_state import inputs_to_state
from app.config import get_settings
from app.graph.state import AgentState, ErrorInfo, TraceEntry
from app.llm.budget import model_request_scope
from app.nodes.persist import persist
from app.observability.diagnostics import failure_diagnostic
from app.observability.llm_metrics import LLMMetricsCallback
from app.observability.logs import bound_request_context
from app.observability.metrics import emit_intent_latency
from app.observability.tracing import HandledErrorCallback, attach_request_trace, session_identifier
from app.tools.bot_context import normalize_message_id

router = APIRouter()
logger = logging.getLogger(__name__)


# ============================================================
# Dify Workflow Run API 请求/响应 schema
# ============================================================


class DifyWorkflowRunRequest(BaseModel):
    """Dify Workflow Run API 请求体（POST /v1/workflows/run）。"""

    model_config = ConfigDict(extra="allow")

    inputs: dict[str, Any] = Field(default_factory=dict)
    query: str | None = None
    files: list[dict[str, Any]] | None = None
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
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event: Literal["message"] = "message"
    mode: Literal["advanced-chat"] = "advanced-chat"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @computed_field(alias="conversation_id")  # type: ignore[prop-decorator]
    @property
    def canonical_conversation_id(self) -> str:
        """读取并检查兼容字段中的同一业务会话身份。"""
        return self.conversation_id

    @computed_field  # type: ignore[prop-decorator]
    @property
    def message_id(self) -> str:
        """读取当前消息身份，避免借用历史消息编号。"""
        return self.id

    @computed_field  # type: ignore[prop-decorator]
    @property
    def created_at(self) -> int:
        """提供本次响应的创建时间。"""
        return self.data.created_at


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
) -> DifyWorkflowRunResponse | JSONResponse:
    """Bound the entire request, including tracing and persistence, before Java's 90s timeout."""
    settings = get_settings()
    deadline = time.monotonic() + settings.request_timeout_seconds
    try:
        with model_request_scope():
            async with asyncio.timeout(settings.request_timeout_seconds):
                return await _execute_workflow(req, request, deadline=deadline)
    except TimeoutError:
        # 超时仅说明本次结果未知；调用端自行决定是否重投。
        return _timeout_response()


def _timeout_response() -> JSONResponse:
    """保留本次超时的明确状态，不回放旧响应或推定交易结果。"""
    return JSONResponse(status_code=504, content={
        "code": "workflow_timeout", "status": 504,
        "message": "指令处理超时，执行结果待核对，请勿重复提交。",
    })


async def _execute_workflow(
    req: DifyWorkflowRunRequest, request: Request, *, deadline: float,
) -> DifyWorkflowRunResponse | JSONResponse:
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
        inputs = dict(req.inputs)
        if req.query is not None and not any(
            key in inputs for key in ("rawContent", "raw_content", "raw_text", "messageContent", "message_content")
        ):
            inputs["raw_content"] = req.query
        if req.files is not None:
            for key in ("files", "sysFiles"):
                if key in inputs and inputs[key] != req.files:
                    raise ValueError("顶层 files 与 inputs 附件冲突")
            inputs["files"] = req.files
        initial_state = inputs_to_state(inputs)
        conversation_id = _resolve_conversation_id(req)
        normalize_message_id(initial_state.get("message_id"))
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

    # ADR 0004：每次调用保留独立的 node_trace 关联 ID；测试工作台可另行
    # 把多轮调用挂到同一个 LangFuse 父 Trace，不改变业务审计粒度。
    request_trace_id = uuid.uuid4().hex
    initial_state["trace_id"] = request_trace_id

    # 消息 ID 只用于传递与审计，调用方重投仍独立执行本次图。
    message_id = initial_state.get("message_id")

    config = _build_run_config(
        conversation_id=conversation_id,
        trace_id=request_trace_id,
        user_id=str(initial_state.get("user_id") or "") or None,
        environment=get_settings().environment,
    )
    trace = await attach_request_trace(
        request_trace_id=request_trace_id,
        traceparent=request.headers.get("traceparent"),
    )
    # LLM 指标 callback 常驻（ADR 0024 D5）；LangFuse handler 接入成功时并列
    config["callbacks"] = [LLMMetricsCallback()] + (
        [HandledErrorCallback(trace.handler), trace.handler] if trace.handler is not None else []
    )

    t0 = time.perf_counter()
    timed_out = False
    # ADR 0024 D5：整次图调用期间的每条日志都带 trace_id / conversation_id / message_id
    with bound_request_context(
        trace_id=request_trace_id, conversation_id=conversation_id, message_id=message_id
    ):
        try:
            # ADR 0024 D4：图内无 interrupt、单轮无需中途恢复，退出时落一次 checkpoint 即可，
            # 避免默认 "async" 每个 superstep 都写 MySQL（单连接 saver 上是队头阻塞源）
            graph_budget = max(0, deadline - time.monotonic() - get_settings().response_reserve_seconds)
            async with asyncio.timeout(graph_budget):
                final_state: AgentState = await graph.ainvoke(
                    initial_state, config=config, durability="exit"
                )
            status: Literal["succeeded", "failed", "stopped"] = (
                "failed" if final_state.get("error") else "succeeded"
            )
            graph_error = final_state.get("error")
            error_msg = graph_error.message if graph_error is not None else None
        except TimeoutError:
            final_state = {**initial_state,
                "error": ErrorInfo(node="workflow_deadline", type="WorkflowTimeout", message="request deadline exceeded"),
                "trace": [TraceEntry(node="workflow_deadline", decision="error:E5:timeout")],
            }
            status = "failed"
            error_msg = "workflow_timeout: execution result is unknown"
            timed_out = True
        except Exception as exc:  # noqa: BLE001
            final_state = {}
            status = "failed"
            error_msg = f"{type(exc).__name__}: {exc}"

    elapsed = time.perf_counter() - t0
    # 端到端 P95 数据源（ADR 0030 D3 上线观察与 ADR 0019 p95_latency_degraded 告警）
    # 无 node label —— alerts 侧以此与节点级样本区分
    emit_intent_latency(
        product_type=final_state.get("product_type") or "unknown",
        intent=final_state.get("intent") or "unknown",
        elapsed_ms=int(elapsed * 1000),
    )
    finished_at = int(time.time())

    if timed_out:
        timeout_response = _timeout_response()
        await persist(final_state)
        return timeout_response

    # 必须等图完成：persist 已记录 set-intent 的失败 trace 后才返回 502。
    # 使用固定文案，不透传后端响应、URL、鉴权信息或异常堆栈。
    error = final_state.get("error")
    failure_message = None
    if error is not None and any(e.node == "persist_intent" for e in (error.causes or [error])):
        failure_message = "消息会话与意图持久化失败，请稍后重试。"
    elif status == "failed" and not final_state.get("reply_text"):
        failure_message = "指令处理失败，请稍后重试。"
    if failure_message:
        failed_body = {"code": "internal_server_error", "message": failure_message, "status": 502}
        return JSONResponse(status_code=502, content=failed_body)

    outputs = _state_to_outputs(final_state)
    # 业务审计 ID：与 node_trace.trace_id / config.metadata.trace_id 同源，恒定暴露
    outputs["trace_id"] = request_trace_id
    outputs["session_id"] = session_identifier(conversation_id)
    # LangFuse 侧信息：仅在接入成功时存在
    if trace.langfuse_trace_id is not None:
        outputs["langfuse_trace_id"] = trace.langfuse_trace_id
    if trace.observation_id is not None:
        outputs["observation_id"] = trace.observation_id
    if trace.url is not None:
        outputs["trace_url"] = trace.url

    data = DifyWorkflowRunData(
        id=workflow_run_id,
        status=status,
        outputs=outputs,
        error="指令处理失败，请核对输入或稍后重试。" if error_msg else None,
        elapsed_time=elapsed,
        total_steps=len(final_state.get("trace", [])),
        created_at=created_at,
        finished_at=finished_at,
    )
    response = DifyWorkflowRunResponse(
        workflow_run_id=workflow_run_id,
        task_id=task_id,
        conversation_id=conversation_id,
        answer=final_state.get("reply_text") or "",
        data=data,
    )
    return response


# ============================================================
# Helpers
# ============================================================


#: 图递归上限(架构体检 2026-08 改进 A):现图均为 DAG,50 为防御纵深上限;
#: 未来引入循环子图时按 CLAUDE.md 指引单独收紧(复杂子图 25)
GRAPH_RECURSION_LIMIT = 50


def _build_run_config(
    conversation_id: str,
    trace_id: str,
    user_id: str | None = None,
    environment: str | None = None,
) -> dict[str, Any]:
    """构造 graph.ainvoke 的 RunnableConfig(thread 绑定 + trace 关联 + 递归上限)。

    metadata 里的 `langfuse_*` 键由 langfuse v4 CallbackHandler 读取（ADR 0024 D5）：
    session = conversation_id 让多轮在 LangFuse 里串成一个 Session；user / tags 供聚合过滤。
    """
    metadata: dict[str, Any] = {
        "trace_id": trace_id,
        "langfuse_session_id": session_identifier(conversation_id),
        "langfuse_tags": [environment or "unknown"],
    }
    if user_id:
        metadata["langfuse_user_id"] = user_id
    return {
        "configurable": {"thread_id": conversation_id},
        "metadata": metadata,
        "recursion_limit": GRAPH_RECURSION_LIMIT,
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
            for t in state.get("tickers") or []
        ],
        "trace": _format_trace(state.get("trace", [])),
    }
    error = state.get("error")
    if error is not None:
        outputs["diagnostic"] = failure_diagnostic(state)
        outputs["error"] = {"code": error.code, "node": error.node, "type": error.type,
                            "causes": [{"code": e.code, "node": e.node, "type": e.type}
                                       for e in error.causes]}
    outputs["trace_entries"] = [
        {"id": e.id, "node": e.node, "decision": e.decision, "elapsed_ms": e.elapsed_ms}
        if isinstance(e, TraceEntry) else {k: e.get(k) for k in ("id", "node", "decision", "elapsed_ms")}
        for e in state.get("trace", []) if isinstance(e, (TraceEntry, dict))
    ]
    expected_action = state.get("expected_action")
    if expected_action is not None:
        outputs["expected_action"] = expected_action
    # 业务对象运行时为 dict，直接 dump
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
        "session_status",
        "backend_request",
        "cleaning_records",
    ):
        v = (state.get("submitted_params") or {}).get(key, state.get(key))
        if v is None:
            continue
        if key in ("place_params", "cancel_params") and expected_action is not None and isinstance(v, dict):
            # wire 兼容投影（ADR 0024 D2）：state 内 expected_action 已是顶层字段，
            # 既有读者（探针脚本 / 日志解析）仍从信封里读，这里只投影不改写 state
            v = {"expected_action": expected_action, **v}
        outputs[key] = v
    return outputs


# /health 与 /ready 在 app/api/health.py
