"""Evidence-checked planning and native Send preparation waves for multi-instructions."""
from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from copy import deepcopy
from typing import Annotated, Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send
from pydantic import BaseModel, ConfigDict, Field

from app.execution.operations import (
    authoritative_order_id,
    batch_operations,
    capture_operations,
    execute_batches,
    response_text,
)
from app.extraction.fields import EvidenceError
from app.graph.retry import io_node
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, ErrorInfo, Message, TraceEntry
from app.llm.clients import get_qwen_standard
from app.observability.diagnostics import failure_diagnostic
from app.prompts.spec import PromptSpec, register
from app.tools.bot_context import BotContext
from app.tools.receipts import receipt_text


class InstructionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(description="原始输入中本条指令的连续原文，不改写、不补全参数")
    evidence: str = Field(description="支持本条指令的原文证据，必须与 text 相同")
    confidence: float = Field(ge=0, le=1, description="拆分边界和依赖关系的可信度，无法确定时降低")
    depends_on: list[int] = Field(default_factory=list, description="依赖的前序指令零起始下标，只能引用本条之前的条目")
    requires_result: bool = Field(default=False, description="是否必须使用前序生成的订单身份；只有顺序关系时为 false")


class Instruction(InstructionCandidate):
    start: int = Field(ge=0, description="Code 校验的原文字符起点")
    end: int = Field(gt=0, description="Code 校验的原文字符终点，不含该位置")


class InstructionCandidatePlan(BaseModel):
    instructions: list[InstructionCandidate] = Field(min_length=1, max_length=8,
        description="按原文顺序的连续指令片段；只复制文本，不计算索引")


class InstructionPlan(BaseModel):
    instructions: list[Instruction] = Field(min_length=1, max_length=8,
        description="按原文顺序的完整指令分解；同一动作的批量订单或共享参数无法独立时保留为一条")


def _planner_input(state: AgentState) -> str:
    return f"raw_content: {state.get('raw_text', '')}\nquote_content: {state.get('quote_content') or ''}"


SPEC = register(PromptSpec(
    category="router", name="split_instructions", output_model=InstructionCandidatePlan,
    inputs=("raw_text", "quote_content"), user_builder=_planner_input,
))

_GAP = re.compile(r"[\s，,；;。.、]*(?:(?:然后|接着|另外|并且|同时|再)[\s，,；;。.、]*)*")
_ACTION = re.compile(r"确认(?:下单|平仓|撤单|改单)|买入|卖出|买|卖|询价|平仓|撤单|查询|下单")
_BUSINESS_CONDITION = re.compile(
    r"(?:成交|成功|完成).{0,3}(?:后|再|才|就)|(?:如果|若|等(?:待)?).{0,30}(?:成交|成功|完成)"
)


def validate_instruction_plan(raw: str, plan: InstructionPlan) -> list[dict[str, Any]]:
    if len(plan.instructions) > 1 and _BUSINESS_CONDITION.search(raw):
        # An HTTP response (even code=0) does not prove fill/order success. Until
        # there is an authoritative condition/event contract, no partial write is safe.
        raise EvidenceError("business-success conditional instructions require explicit later confirmation")
    previous_end = 0
    result: list[dict[str, Any]] = []
    for index, instruction in enumerate(plan.instructions):
        if (
            instruction.start < previous_end or instruction.end > len(raw)
            or instruction.end <= instruction.start
            or raw[instruction.start:instruction.end] != instruction.text
            or instruction.evidence != instruction.text or instruction.confidence < 0.8
            or not _GAP.fullmatch(raw[previous_end:instruction.start])
            or len(instruction.depends_on) != len(set(instruction.depends_on))
            or any(dependency < 0 or dependency >= index for dependency in instruction.depends_on)
            or (instruction.requires_result and not instruction.depends_on)
        ):
            raise EvidenceError("instruction boundaries, evidence or dependencies cannot be verified")
        result.append({"instruction_id": f"instruction-{index + 1}", **instruction.model_dump()})
        previous_end = instruction.end
    if not _GAP.fullmatch(raw[previous_end:]):
        raise EvidenceError("instruction plan omitted part of the original request")
    return result


def materialize_instruction_plan(raw: str, candidates: InstructionCandidatePlan) -> InstructionPlan:
    cursor = 0
    items = []
    for candidate in candidates.instructions:
        start = raw.find(candidate.text, cursor) if candidate.text else -1
        if start < 0 or not _GAP.fullmatch(raw[cursor:start]):
            raise EvidenceError("instruction text cannot be located without omitting input")
        end = start + len(candidate.text)
        items.append(Instruction(**candidate.model_dump(), start=start, end=end))
        cursor = end
    plan = InstructionPlan(instructions=items)
    validate_instruction_plan(raw, plan)
    return plan


@io_node
async def plan_instructions(state: AgentState) -> dict[str, Any]:
    raw = state.get("raw_text") or ""
    from app.subgraphs.option.place_params import OrderScopeError, is_quoted_batch_supplement

    try:
        batch = is_quoted_batch_supplement(raw, state.get("quote_content") or "")
    except OrderScopeError as exc:
        raise EvidenceError(str(exc)) from exc
    if batch:
        return {"sub_instructions": [], "trace": [TraceEntry(node="plan_instructions", decision="quoted_batch_supplement")]}
    if not raw.strip() or (
        not re.search(r"[;；\n]|然后|另外|并且|同时|接着|再[买卖撤建下平查询确]|期权.*互换|互换.*期权", raw)
        and len(_ACTION.findall(raw)) <= 1
    ):
        return {"sub_instructions": [], "trace": [TraceEntry(node="plan_instructions", decision="single_instruction")]}
    messages, prompt_name = SPEC.build_messages(state)
    output = await get_qwen_standard().with_structured_output(InstructionCandidatePlan).ainvoke(messages)
    candidates = InstructionCandidatePlan.model_validate(output)
    plan = validate_instruction_plan(raw, materialize_instruction_plan(raw, candidates))
    if len(plan) > 1 and state.get("input_files"):
        raise EvidenceError("multi-instruction attachment ownership requires explicit separation")
    return {"sub_instructions": plan, "trace": [TraceEntry(
        node="plan_instructions", decision=f"validated:{len(plan)}",
        llm_output={"prompt_name": prompt_name, "instruction_count": len(plan)},
    )]}


def _merge_prepared(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = {item["instruction_id"]: item for item in left}
    merged.update({item["instruction_id"]: item for item in right})
    return list(merged.values())


class InstructionsState(AgentState, total=False):
    _base: AgentState
    _plan: list[dict[str, Any]]
    _ready: list[dict[str, Any]]
    _instruction: dict[str, Any]
    _dependencies: list[dict[str, Any]]
    _prepared: Annotated[list[dict[str, Any]], _merge_prepared]
    _results: dict[str, dict[str, Any]]
    _last_finished: dict[str, float]
    _blocked_keys: set[str]


class InstructionsOutput(TypedDict, total=False):
    instruction_results: list[dict[str, Any]]
    reply_text: str
    error: ErrorInfo | None
    trace: list[TraceEntry]
    product_type: str
    intent: str


def build_instructions_graph(
    worker_graph: Any, *, dedup_window_seconds: float = 10.0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> CompiledStateGraph[InstructionsState, None, AgentState, InstructionsOutput]:
    """worker_graph ends after business extraction; it must not persist or invoke this graph."""

    @safe_node
    async def initialize_instructions(state: InstructionsState) -> dict[str, Any]:
        raw_plan = [{key: value for key, value in item.items() if key != "instruction_id"}
                    for item in state.get("sub_instructions") or []]
        plan = validate_instruction_plan(state.get("raw_text") or "", InstructionPlan(instructions=raw_plan))
        base = {key: deepcopy(value) for key, value in state.items()
                if not key.startswith("_") and key not in {"sub_instructions", "instruction_results"}}
        return {"_base": base, "_plan": plan, "_ready": [], "_prepared": [],
                "_results": {}, "_last_finished": {}, "_blocked_keys": set()}

    @safe_node
    async def schedule_instructions(state: InstructionsState) -> dict[str, Any]:
        if state.get("error"):
            return {"_ready": []}
        results = deepcopy(state.get("_results") or {})
        ready = []
        for instruction in state["_plan"]:
            identity = instruction["instruction_id"]
            if identity in results:
                continue
            dependencies = [f"instruction-{index + 1}" for index in instruction["depends_on"]]
            if not all(dependency in results for dependency in dependencies):
                continue
            if any(results[dependency]["status"] != "response_received" for dependency in dependencies):
                results[identity] = {"instruction_id": identity, "status": "blocked", "reason": "dependency_unavailable"}
                continue
            if instruction["requires_result"] and (
                len(dependencies) != 1 or authoritative_order_id(results[dependencies[0]]) is None
            ):
                results[identity] = {"instruction_id": identity, "status": "blocked", "reason": "dependency_binding_ambiguous"}
                continue
            ready.append(instruction)
        return {"_ready": ready, "_results": results}

    def dispatch_preparations(state: InstructionsState) -> list[Send] | str:
        if not state.get("_ready"):
            return "finish_instructions"
        return [Send("prepare_instruction", {
            "_base": state["_base"], "_instruction": instruction,
            "_dependencies": [state["_results"][f"instruction-{index + 1}"]
                              for index in instruction["depends_on"]],
        }) for instruction in state["_ready"]]

    @safe_node
    async def prepare_instruction(state: InstructionsState, config: RunnableConfig) -> dict[str, Any]:
        instruction, base = state["_instruction"], deepcopy(state["_base"])
        identity = instruction["instruction_id"]
        base["raw_text"] = instruction["text"]
        quote = base.get("quote_content")
        base["message_content"] = instruction["text"] + (
            "\n" + quote if quote else ""
        )
        base["trace"] = []
        base["error"] = None
        allowed_order_ids = None
        dependency_product = None
        if instruction["requires_result"]:
            dependency = state["_dependencies"][0]
            order_id = authoritative_order_id(dependency)
            allowed_order_ids = {order_id} if order_id is not None else set()
            dependency_product = dependency.get("product_type")
            # Actual response is history, never a fabricated quote/confirmation card.
            base["history_messages"] = [*(base.get("history_messages") or []), Message(
                role="assistant", content=response_text(dependency["api_result"]),
            )]
        context = BotContext.from_state(base)
        ownership = {"messageId": context.message_id, "userId": context.user_id,
                     "roomId": context.room_id, "conversationId": context.conversation_id}
        try:
            with capture_operations(ownership, allowed_order_ids=allowed_order_ids,
                                    dependency_product=dependency_product) as captured:
                final = await worker_graph.ainvoke(base, config=config)
            if final.get("error"):
                prepared = {"instruction_id": identity, "status": "failed", "reason": "preparation_failed",
                            "diagnostic": failure_diagnostic(final)}
            elif len(captured.operations) == 1:
                prepared = {"instruction_id": identity, "operation": captured.operations[0]}
            elif not captured.operations:
                prepared = {"instruction_id": identity, "status": "needs_input", "reason": "no_operation_prepared",
                            "reply_text": final.get("reply_text") or "该条指令需要补充信息。"}
            else:
                prepared = {"instruction_id": identity, "status": "blocked", "reason": "multiple_operations_in_one_instruction"}
            prepared["product_type"] = final.get("product_type")
            prepared["intent"] = final.get("intent")
            prepared["trace"] = final.get("trace") or []
        except Exception as exc:  # noqa: BLE001 - preserve independent instruction failures
            prepared = {"instruction_id": identity, "status": "failed", "reason": "preparation_failed",
                        "error_type": type(exc).__name__, "diagnostic": {
                            "code": "E3", "node": "prepare_instruction", "type": type(exc).__name__,
                            "summary": "指令参数准备失败",
                        }}
        return {"_prepared": [prepared]}

    @safe_node
    async def submit_instruction_batches(state: InstructionsState) -> dict[str, Any]:
        ready_ids = {item["instruction_id"] for item in state["_ready"]}
        prepared = [item for item in state.get("_prepared") or [] if item["instruction_id"] in ready_ids]
        results = deepcopy(state["_results"])
        operations = []
        for item in prepared:
            if "operation" in item:
                operations.append(item)
            else:
                results[item["instruction_id"]] = {key: value for key, value in item.items() if key != "trace"}
        outcomes, finished, blocked = await execute_batches(
            batch_operations(operations), last_finished=state["_last_finished"],
            blocked_keys=state["_blocked_keys"], dedup_window_seconds=dedup_window_seconds,
            clock=clock, sleep=sleep,
        )
        for item in prepared:
            identity = item["instruction_id"]
            if identity in outcomes:
                outcomes[identity].update({key: item[key] for key in ("product_type", "intent")
                                           if item.get(key) is not None})
        results.update(outcomes)
        return {"_results": results, "_last_finished": finished, "_blocked_keys": blocked}

    @safe_node
    async def finish_instructions(state: InstructionsState) -> dict[str, Any]:
        results = [state.get("_results", {}).get(item["instruction_id"], {
            "instruction_id": item["instruction_id"], "status": "blocked", "reason": "execution_unavailable",
        }) for item in state.get("_plan") or []]
        replies = []
        seen_batches: set[tuple[str, ...]] = set()
        for result in results:
            batch = tuple(result.get("batch_instruction_ids") or [result["instruction_id"]])
            if batch in seen_batches:
                continue
            seen_batches.add(batch)
            if result.get("api_result") is not None or result.get("api_code") is not None:
                reply = receipt_text(result.get("api_code"), result.get("api_result"))
            elif result.get("reply_text"):
                reply = result["reply_text"]
            else:
                reply = {
                    "uncertain": "执行结果待核对，请勿重复提交。", "blocked": "前置结果或指令范围未能确定，本条尚未提交。",
                    "failed": "本条指令处理失败。", "needs_input": "本条指令需要补充信息。",
                }.get(result["status"], "本条指令尚未提交。")
            numbers = "、".join(identity.removeprefix("instruction-") for identity in batch)
            replies.append(f"第 {numbers} 条指令：\n{reply}")
        error = state.get("error")
        if any(result["status"] == "uncertain" for result in results):
            error = ErrorInfo(node="submit_instruction_batches", type="BackendUnreachableError", message="one or more instruction results require reconciliation")
        elif any(result["status"] in {"failed", "blocked"} for result in results):
            error = error or ErrorInfo(node="instructions", type="InstructionFailure", message="one or more instructions were not completed")
        trace = [entry for item in state.get("_prepared") or [] for entry in item.get("trace") or []]
        trace.append(TraceEntry(node="finish_instructions", decision=f"instructions={len(results)}"))
        return {"instruction_results": results, "reply_text": "\n\n".join(replies), "error": error, "trace": trace,
                "product_type": "unknown", "intent": "multi_instruction"}

    graph: StateGraph[InstructionsState, None, AgentState, InstructionsOutput] = StateGraph(
        InstructionsState, input_schema=AgentState, output_schema=InstructionsOutput,
    )
    for name, node in (
        ("initialize_instructions", initialize_instructions), ("schedule_instructions", schedule_instructions),
        ("prepare_instruction", prepare_instruction), ("submit_instruction_batches", submit_instruction_batches),
        ("finish_instructions", finish_instructions),
    ):
        graph.add_node(name, node)
    graph.add_edge(START, "initialize_instructions")
    graph.add_edge("initialize_instructions", "schedule_instructions")
    graph.add_conditional_edges("schedule_instructions", dispatch_preparations, ["prepare_instruction", "finish_instructions"])
    graph.add_edge("prepare_instruction", "submit_instruction_batches")
    graph.add_edge("submit_instruction_batches", "schedule_instructions")
    graph.add_edge("finish_instructions", END)
    return graph.compile(checkpointer=False, name="instructions")
