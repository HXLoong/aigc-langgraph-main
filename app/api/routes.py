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

import logging
import time
import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.idempotency import PROCESSING_NOTICE, IdempotencyStore
from app.api.turn_state import inputs_to_state
from app.config import get_settings
from app.graph.state import AgentState
from app.observability.llm_metrics import LLMMetricsCallback
from app.observability.logs import bound_request_context
from app.observability.metrics import emit_intent_latency
from app.observability.tracing import attach_request_trace

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
        initial_state = inputs_to_state(req.inputs)
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

    # ADR 0024 D4：请求级幂等——同一企微 message_id 重投不重跑整图（重跑 = 重复下单）
    store: IdempotencyStore | None = getattr(request.app.state, "idempotency_store", None)
    message_id = initial_state.get("message_id")
    idem_key = str(message_id) if message_id not in (None, "") else None
    if store is not None and idem_key is not None:
        existing = await _idempotency_begin(store, idem_key, initial_state)
        if existing is not None:
            answer = existing.reply_text if existing.status == "done" else PROCESSING_NOTICE
            return DifyWorkflowRunResponse(
                workflow_run_id=workflow_run_id,
                task_id=task_id,
                conversation_id=conversation_id,
                answer=answer or "",
                data=DifyWorkflowRunData(
                    id=workflow_run_id, status="succeeded",
                    outputs={"replayed": True, "trace_id": request_trace_id,
                             "idempotency_status": existing.status},
                    created_at=created_at, finished_at=int(time.time()),
                ),
            )

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
    config["callbacks"] = [LLMMetricsCallback()] + ([trace.handler] if trace.handler is not None else [])

    t0 = time.perf_counter()
    # ADR 0024 D5：整次图调用期间的每条日志都带 trace_id / conversation_id / message_id
    with bound_request_context(
        trace_id=request_trace_id, conversation_id=conversation_id, message_id=message_id
    ):
        try:
            # ADR 0024 D4：图内无 interrupt、单轮无需中途恢复，退出时落一次 checkpoint 即可，
            # 避免默认 "async" 每个 superstep 都写 MySQL（单连接 saver 上是队头阻塞源）
            final_state: AgentState = await graph.ainvoke(
                initial_state, config=config, durability="exit"
            )
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

    if store is not None and idem_key is not None:
        await _idempotency_complete(store, idem_key, final_state, error_msg, int(elapsed * 1000))

    # 必须等图完成：persist 已记录 set-intent 的失败 trace 后才返回 502。
    # 使用固定文案，不透传后端响应、URL、鉴权信息或异常堆栈。
    error = final_state.get("error")
    if error is not None and error.node == "persist_intent":
        raise HTTPException(
            status_code=502, detail="消息会话与意图持久化失败，请稍后重试。",
        )

    outputs = _state_to_outputs(final_state)
    # 业务审计 ID：与 node_trace.trace_id / config.metadata.trace_id 同源，恒定暴露
    outputs["trace_id"] = request_trace_id
    # LangFuse 侧信息：仅在接入成功时存在
    if trace.langfuse_trace_id is not None:
        outputs["langfuse_trace_id"] = trace.langfuse_trace_id
    if trace.url is not None:
        outputs["trace_url"] = trace.url

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


async def _idempotency_begin(store: IdempotencyStore, key: str, state: AgentState):  # type: ignore[no-untyped-def]
    """存储故障只 warning：幂等是加固，不阻断业务（此时退化为无幂等）。"""
    try:
        return await store.begin(
            key,
            conversation_id=str(state.get("conversation_id") or ""),
            user_id=str(state.get("user_id") or ""),
            room_id=str(state.get("room_id") or ""),
            raw_text=str(state.get("raw_text") or ""),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("idempotency begin 失败，本次不做幂等：%s", exc)
        return None


async def _idempotency_complete(
    store: IdempotencyStore, key: str, final_state: AgentState, error_msg: str | None, latency_ms: int
) -> None:
    try:
        await store.complete(
            key,
            reply_text=final_state.get("reply_text"),
            product_type=final_state.get("product_type"),
            intent=final_state.get("intent"),
            api_code=final_state.get("api_code"),
            api_result=final_state.get("api_result"),
            error=error_msg,
            latency_ms=latency_ms,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("idempotency complete 失败：%s", exc)


#: 图递归上限(架构体检 2026-08 改进 A):现图均为 DAG,50 为防御纵深上限;
#: 未来引入循环子图时按 CLAUDE.md 指引单独收紧(复杂子图 25)
GRAPH_RECURSION_LIMIT = 50


def _build_run_config(
    conversation_id: str,
    trace_id: str,
    user_id: str | None = None,
    environment: str | None = None,
) -> dict:
    """构造 graph.ainvoke 的 RunnableConfig(thread 绑定 + trace 关联 + 递归上限)。

    metadata 里的 `langfuse_*` 键由 langfuse v4 CallbackHandler 读取（ADR 0024 D5）：
    session = conversation_id 让多轮在 LangFuse 里串成一个 Session；user / tags 供聚合过滤。
    """
    metadata: dict[str, Any] = {
        "trace_id": trace_id,
        "langfuse_session_id": conversation_id,
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
    ):
        v = state.get(key)
        if v is None:
            continue
        if key in ("place_params", "cancel_params") and expected_action is not None:
            # wire 兼容投影（ADR 0024 D2）：state 内 expected_action 已是顶层字段，
            # 既有读者（探针脚本 / 日志解析）仍从信封里读，这里只投影不改写 state
            v = {"expected_action": expected_action, **v}
        outputs[key] = v
    return outputs


# /health 与 /ready 已迁至 app/api/health.py（D2.6 / Issue #72）
