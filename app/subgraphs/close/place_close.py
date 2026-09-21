"""close.place_close 节点 · 平仓下单参数提取 + 全部平仓确认（P0 核心）。

ADR 0024 重构 5：原 215 行单节点拆成 LangGraph 子图（`build_place_close_graph`），
每阶段一个节点、一条 TraceEntry，两处早退做成图边：

    place_close_parse（引用消息解析，纯函数）
      → place_close_fetch_orders（OptionClient.query_close_orders）
      → place_close_extract（LLM 原文候选与证据）
      → place_close_normalize（代码绑定目标、计算金额与比例、锁定字段）
          ├─ 空列表 → place_close_reject
          └─ place_close_validate（身份 / 名义本金 / 限价 / POV 预校验）
                ├─ 校验失败 → place_close_reject
                └─ place_close_submit（参数聚合 + 真后端 operate）

私有中间态 `pc_*` 住在 PlaceCloseState，不外泄（output_schema=PlaceCloseOutput）；
`close_place_close(state)` façade 契约不变（close 图用 `build_place_close_graph()` 原生嵌入）。

CLAUDE.md P0：严禁本地拼确认卡掩盖后端真实响应——`reply_text` 不再由本节点
拼接文案，改为真后端 `financial-orders/operate` 返回的 `api_result` 由
render 节点透传（`app/nodes/render.py` 已优先读取 `state['api_result']`）。

LLM：结构化原文候选；最终业务参数由 normalization.py 生成。
prompt：app/prompts/option_close/place_close.md。

注：close.place_close **不依赖 ticker resolver**——平仓基于订单号
（CO- / OPT- / OPTG-），标的代码已在订单中确定。
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Annotated, Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.extraction.candidates import candidate_model, evidence_sources, verify_candidates
from app.extraction.fields import FieldRecord, merge_fields
from app.graph.business_params import validated_close_params
from app.graph.cascade import has_error
from app.graph.retry import add_io_node, io_node
from app.graph.safe_node import safe_node
from app.graph.state import (
    AgentState,
    ErrorInfo,
    ExpectedAction,
    TickerCandidate,
    TraceEntry,
    merge_by_id,
)
from app.llm.clients import get_qwen_thinking
from app.prompts import blocks
from app.prompts.spec import PromptSpec, register
from app.subgraphs.close.aggregate import build_close_order_req_vo
from app.subgraphs.close.backend import call_close_backend
from app.subgraphs.close.models import CloseOrderItem, ClosePlaceParams
from app.subgraphs.close.normalization import normalize_place_candidates
from app.subgraphs.close.reference_parser import ReferenceParseResult, parse_reference_message
from app.tools.option_client import OptionClientHttpx


def _build_user_message(
    raw_content: str,
    quote_content: str,
    parsed: ReferenceParseResult,
    order_list: list[dict[str, Any]],
) -> str:
    """组装可验证原文来源、引用事实及只读查询结果，不注入规则。"""

    return blocks.source_payload(
        {"raw_text": raw_content, "quote_content": quote_content},
        context={"reference": parsed, "orderList": order_list}, include_history=False,
    )


def _user_from_state(state: AgentState) -> str:
    """state 可重建的 user 消息（orderList 由节点运行时经 HTTP 取单后注入）。

    完整消息在节点内用 `_build_user_message(parsed, order_data)` 组装；本函数为
    注册契约的 state-only 重建（引用解析是纯函数，取单结果为空时的形态），
    与 swap.place_order 的 `_user_from_state` 同一模式（渲染时机在节点内）。
    """
    raw = state.get("raw_text", "") or ""
    quote = state.get("quote_content") or ""
    parsed = parse_reference_message(quote, raw)
    return _build_user_message(raw, quote, parsed, [])


CANDIDATE_MODEL = candidate_model(ClosePlaceParams)
SPEC = register(PromptSpec(
    category="option_close",
    name="place_close",
    output_model=CANDIDATE_MODEL,
    inputs=("raw_text", "quote_content"),
    user_builder=_user_from_state,
))


async def _fetch_order_data(
    order_ids: list[str],
    contract_codes: list[str],
    room_id: str | None = None,
    message_id: int | None = None,
) -> list[dict[str, Any]]:
    """获取订单信息[http] + 格式化订单数据[code]（走标准 OptionClient）。

    roomId/messageId 对齐 DSL v2「获取订单信息」payload。
    """
    result = await OptionClientHttpx().query_close_orders(
        order_ids=order_ids, contract_codes=contract_codes,
        room_id=room_id, message_id=message_id,
    )
    if result.get("code") != 0:
        raise ValueError(f"平仓订单查询失败（code={result.get('code')}）")
    data = result.get("data")
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise ValueError("平仓订单查询响应结构不正确")
    return data



# ============================================================
# 子图 State
# ============================================================


class PlaceCloseState(AgentState, total=False):
    """place_close 子图私有 State：AgentState + `pc_*` 中间态。"""

    pc_parsed: ReferenceParseResult
    pc_order_data: list[dict[str, Any]]
    pc_candidates: dict[str, Any]
    pc_llm_output: dict[str, Any]
    pc_close_orders: list[dict[str, Any]]
    pc_reject_reply: str | None
    pc_reject_decision: str | None


class PlaceCloseOutput(TypedDict, total=False):
    """子图对 close 图 / 父图的写回面。"""

    expected_action: ExpectedAction | None
    field_records: Annotated[dict[str, FieldRecord], merge_fields]
    close_params: dict[str, Any] | None
    reply_text: str | None
    intent: str
    api_result: str | dict[str, Any] | list[Any] | None
    api_code: int | None
    tickers: list[TickerCandidate]
    trace: Annotated[list[TraceEntry], merge_by_id]
    error: ErrorInfo | None


# ============================================================
# 阶段节点
# ============================================================


@safe_node
async def place_close_parse(state: PlaceCloseState) -> dict[str, Any]:
    """步骤 1：平仓参数提取-引用消息解析（纯函数）。"""
    raw = state.get("raw_text", "") or ""
    quote = state.get("quote_content") or ""
    parsed = parse_reference_message(quote, raw)
    return {
        "pc_parsed": parsed,
        "trace": [TraceEntry(
            node="place_close_parse",
            decision=f"type={parsed['messageType']},orders={len(parsed['orderIds'])},"
            f"contracts={len(parsed['contractCodes'])}",
        )],
    }


@io_node
async def place_close_fetch_orders(state: PlaceCloseState) -> dict[str, Any]:
    """步骤 2+3：获取订单信息 → 格式化订单数据。"""
    parsed = state["pc_parsed"]
    order_data = await _fetch_order_data(
        parsed["orderIds"],
        parsed["contractCodes"],
        room_id=state.get("room_id"),
        message_id=state.get("message_id"),
    )
    return {
        "pc_order_data": order_data,
        "trace": [TraceEntry(node="place_close_fetch_orders", decision=f"holdings={len(order_data)}")],
    }


@io_node
async def place_close_extract(state: PlaceCloseState) -> dict[str, Any]:
    """步骤 4：原文候选提取并验证证据，不接受模型计算的最终参数。"""
    raw = state.get("raw_text", "") or ""
    quote = state.get("quote_content") or ""
    system, _prompt_name = SPEC.render_system(state)
    llm = get_qwen_thinking().with_structured_output(CANDIDATE_MODEL)
    user_message = _build_user_message(raw, quote, state["pc_parsed"], state.get("pc_order_data") or [])
    candidates = CANDIDATE_MODEL.model_validate(await llm.ainvoke([("system", system), ("user", user_message)]))
    verify_candidates(candidates, evidence_sources(state))
    count = len(cast(Any, candidates).close_order_list)
    return {
        "pc_candidates": candidates.model_dump(by_alias=True),
        "pc_llm_output": {"prompt_name": _prompt_name, "candidate_orders": count},
        "trace": [TraceEntry(node="place_close_extract", decision=f"candidate_orders={count}")],
    }


@safe_node
async def place_close_normalize(state: PlaceCloseState) -> dict[str, Any]:
    """步骤 5：合并输出 + 确定性后处理。空列表 → 交给 reject 边。"""
    parsed = state["pc_parsed"]
    candidates = CANDIDATE_MODEL.model_validate(state.get("pc_candidates") or {})
    params, records = normalize_place_candidates(
        candidates, evidence_sources(state), parsed, state.get("pc_order_data") or [],
    )
    if not params.close_order_list:
        return {
            "pc_close_orders": [],
            "pc_reject_reply": "未能识别平仓参数，请提供订单号或持仓序号。",
            "pc_reject_decision": "empty_close_order_list",
            "trace": [TraceEntry(node="place_close_normalize", decision="empty_close_order_list")],
        }
    close_list = params.close_order_list
    return {
        "pc_close_orders": [item.model_dump() for item in close_list],
        "field_records": records,
        "pc_reject_reply": None,
        "pc_reject_decision": None,
        "trace": [TraceEntry(node="place_close_normalize", decision=f"orders={len(close_list)}")],
    }


@safe_node
async def place_close_validate(state: PlaceCloseState) -> dict[str, Any]:
    """步骤 6：客户端预校验（fail-fast，不调用真后端——是拒绝提交，不是掩盖后端响应）。"""
    close_list = [CloseOrderItem.model_validate(o) for o in state.get("pc_close_orders") or []]
    if any(not item.order_id and not item.internal_trade_id for item in close_list):
        return {
            "pc_reject_reply": "未能识别平仓目标，请提供合约编号或持仓序号。",
            "pc_reject_decision": "missing_close_order_identity",
            "trace": [TraceEntry(node="place_close_validate", decision="missing_close_order_identity")],
        }

    relative_twap = re.search(
        r"TWAP[\s，,]*\d+(?:\.\d+)?\s*(?:分钟|分|小时|min(?:utes)?)",
        state.get("raw_text") or "", re.IGNORECASE,
    )
    missing_twap_range = [
        item for item in close_list
        if item.close_order_type == "TWAP"
        and not (item.close_order_algo_start_time and item.close_order_algo_end_time)
    ]
    if relative_twap and missing_twap_range:
        labels = [
            f"期权平仓订单[{item.order_id}]参数需要完善：" if item.order_id
            else f"合约编号：{item.internal_trade_id}"
            for item in missing_twap_range
        ]
        return {
            "pc_reject_reply": "\n".join(labels + [
                "TWAP 仅提供时长，无法确定起止时间。",
                "请引用本消息重新提供平仓金额、限价和明确的 TWAP 起止时间（HH:MM-HH:MM）。",
            ]),
            "pc_reject_decision": "twap_duration_requires_time_range",
            "trace": [TraceEntry(node="place_close_validate", decision="twap_duration_requires_time_range")],
        }

    errors: list[str] = []
    for leg in close_list:
        amt = leg.close_order_notional_delta
        if amt is not None:
            try:
                amt_val = float(amt)
                if amt_val <= 0:
                    errors.append("平仓名义本金必须大于0")
                elif amt_val < 1_000_000:
                    errors.append("平仓名义本金不能低于100万")
            except (ValueError, TypeError):
                pass
        if leg.close_order_type == "限价单" and leg.close_order_price is None:
            errors.append("限价单必须填写限定价格")
        if leg.close_order_type == "POV" and leg.close_order_pov_ratio is not None:
            pov = leg.close_order_pov_ratio
            if not (1 <= pov <= 100):
                errors.append(f"POV比例{pov}%超出合法范围(1-100%)")
    if errors:
        err_msg = "参数校验不通过：" + "；".join(set(errors))
        return {
            "pc_reject_reply": err_msg,
            "pc_reject_decision": f"validation_failed: {err_msg}",
            "trace": [TraceEntry(node="place_close_validate", decision="validation_failed")],
        }
    return {
        "pc_reject_reply": None,
        "pc_reject_decision": None,
        "trace": [TraceEntry(node="place_close_validate", decision="ok")],
    }


@safe_node
async def place_close_reject(state: PlaceCloseState) -> dict[str, Any]:
    """早退出口：写 close_params + 引导文案，不调后端。汇总条目沿用 close_place_close 名。"""
    return {
        "expected_action": "close",
        "close_params": validated_close_params(closeOrderList=state.get("pc_close_orders") or []),
        "reply_text": state.get("pc_reject_reply"),
        "intent": "close_order_request",
        "trace": [
            TraceEntry(node="place_close_reject", decision=state.get("pc_reject_decision")),
            TraceEntry(
                node="close_place_close",
                decision=state.get("pc_reject_decision"),
                llm_output=state.get("pc_llm_output"),
            ),
        ],
    }


@safe_node
async def place_close_submit(state: PlaceCloseState) -> dict[str, Any]:
    """步骤 7：期权平仓-参数聚合 + 前置清洗 + 真后端调用。

    CLAUDE.md P0：严禁本地拼确认卡掩盖后端真实响应——reply_text 由 render 节点从
    state['api_result']（真后端返回）透传，本节点不拼接文案。
    """
    close_order_list_dump = state.get("pc_close_orders") or []
    close_list = [CloseOrderItem.model_validate(o) for o in close_order_list_dump]
    req_vo = build_close_order_req_vo(close_order_list=close_order_list_dump)
    backend = await call_close_backend(state, intent="close_order_request", close_order_req_vo=req_vo)

    types = [item.close_order_type for item in close_list if item.close_order_type]
    full_closes = sum(1 for item in close_list if item.confirm_full_close)
    decision = f"orders={len(close_list)}, types={types}, full_close={full_closes}"
    return {
        "expected_action": "close",
        "close_params": validated_close_params(closeOrderList=close_order_list_dump),
        **backend,
        "intent": "close_order_request",
        "trace": [
            TraceEntry(node="place_close_submit", decision=f"api_code={backend.get('api_code')}"),
            TraceEntry(node="close_place_close", decision=decision, llm_output=state.get("pc_llm_output")),
        ],
    }


# ============================================================
# 拓扑
# ============================================================


def _route_or_end(next_node: str):  # type: ignore[no-untyped-def]
    def _router(state: PlaceCloseState) -> str:
        return END if has_error(state) else next_node

    return _router


def _route_after_normalize(state: PlaceCloseState) -> str:
    if has_error(state):
        return END
    return "place_close_reject" if state.get("pc_reject_reply") else "place_close_validate"


def _route_after_validate(state: PlaceCloseState) -> str:
    if has_error(state):
        return END
    return "place_close_reject" if state.get("pc_reject_reply") else "place_close_submit"


def build_place_close_graph() -> CompiledStateGraph[PlaceCloseState, None, AgentState, PlaceCloseOutput]:
    g: StateGraph[PlaceCloseState, None, AgentState, PlaceCloseOutput] = StateGraph(PlaceCloseState, input_schema=AgentState, output_schema=PlaceCloseOutput)
    g.add_node("place_close_parse", place_close_parse)
    add_io_node(g, "place_close_fetch_orders", place_close_fetch_orders)
    add_io_node(g, "place_close_extract", place_close_extract)
    g.add_node("place_close_normalize", place_close_normalize)
    g.add_node("place_close_validate", place_close_validate)
    g.add_node("place_close_submit", place_close_submit)
    g.add_node("place_close_reject", place_close_reject)

    g.add_edge(START, "place_close_parse")
    g.add_conditional_edges("place_close_parse", _route_or_end("place_close_fetch_orders"),
                            ["place_close_fetch_orders", END])
    g.add_conditional_edges("place_close_fetch_orders", _route_or_end("place_close_extract"),
                            ["place_close_extract", END])
    g.add_conditional_edges("place_close_extract", _route_or_end("place_close_normalize"),
                            ["place_close_normalize", END])
    g.add_conditional_edges("place_close_normalize", _route_after_normalize,
                            ["place_close_reject", "place_close_validate", END])
    g.add_conditional_edges("place_close_validate", _route_after_validate,
                            ["place_close_reject", "place_close_submit", END])
    g.add_edge("place_close_submit", END)
    g.add_edge("place_close_reject", END)
    return g.compile(name="close_place_close")


@lru_cache(maxsize=1)
def get_place_close_graph() -> CompiledStateGraph[PlaceCloseState, None, AgentState, PlaceCloseOutput]:
    return build_place_close_graph()


async def close_place_close(state: AgentState) -> dict[str, Any]:
    """façade：跑 place_close 子图并返回写回面（供直接调用 / 测试；close 图原生嵌入编译图）。"""
    return await get_place_close_graph().ainvoke(state)


__all__ = ["build_place_close_graph", "close_place_close", "get_place_close_graph"]
