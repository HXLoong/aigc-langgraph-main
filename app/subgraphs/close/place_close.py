"""close.place_close 节点 · 平仓下单参数提取 + 全部平仓确认（P0 核心）。

ADR 0024 重构 5：原 215 行单节点拆成 LangGraph 子图（`build_place_close_graph`），
每阶段一个节点、一条 TraceEntry，两处早退做成图边：

    place_close_parse（引用消息解析，纯函数）
      → place_close_fetch_orders（OptionClient.query_close_orders）
      → place_close_extract（LLM 参数提取）
      → place_close_normalize（合并 + 确定性后处理：POV/跟量默认值、序号→真持仓覆盖）
          ├─ 空列表 → place_close_reject
          └─ place_close_validate（身份 / 名义本金 / 限价 / POV 预校验）
                ├─ 校验失败 → place_close_reject
                └─ place_close_submit（参数聚合 + 真后端 operate）

私有中间态 `pc_*` 住在 PlaceCloseState，不外泄（output_schema=PlaceCloseOutput）；
`close_place_close(state)` façade 契约不变（close 图用 `build_place_close_graph()` 原生嵌入）。

CLAUDE.md P0：严禁本地拼确认卡掩盖后端真实响应——`reply_text` 不再由本节点
拼接文案，改为真后端 `financial-orders/operate` 返回的 `api_result` 由
render 节点透传（`app/nodes/render.py` 已优先读取 `state['api_result']`）。

LLM：thinking 模型 + with_structured_output（ADR 0010）。
prompt：app/prompts/option_close/place_close.md（对齐 Dify
`请求下单和确认全部平仓参数提取`，823 行新版）。

注：close.place_close **不依赖 ticker resolver**——平仓基于订单号
（CO- / OPT- / OPTG-），标的代码已在订单中确定。
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.business_params import validated_close_params
from app.graph.cascade import has_error
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, ErrorInfo, TickerCandidate, TraceEntry, merge_by_id
from app.llm.clients import get_qwen_thinking
from app.prompts.spec import PromptSpec, register
from app.subgraphs.close.aggregate import build_close_order_req_vo
from app.subgraphs.close.backend import call_close_backend
from app.subgraphs.close.merge import merge_close_orders
from app.subgraphs.close.models import CloseOrderItem, ClosePlaceParams
from app.subgraphs.close.order_id import is_order_id
from app.subgraphs.close.reference_parser import ReferenceParseResult, parse_reference_message
from app.tools.exceptions import BackendUnreachableError
from app.tools.option_client import OptionClientHttpx


def _build_user_message(
    raw_content: str,
    quote_content: str,
    parsed: ReferenceParseResult,
    order_list: list[dict[str, Any]],
) -> str:
    """组装与 Dify `请求下单和确认全部平仓参数提取` user template 完全对齐的输入。"""

    def _j(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    single_candidate = parsed["singleHoldingCandidateOrderId"]
    return (
        f"User input: {raw_content}\n"
        f"Holding map (code parsing result): {_j(parsed['holdingMap'])}\n"
        f"Error order ID list: {_j(parsed['errorOrderIds'])}\n"
        f"Full-close confirmation order ID list: {_j(parsed['fullCloseIds'])}\n"
        f"Pure error order ID list: {_j(parsed['pureErrorOrderIds'])}\n"
        f"Pure error order count: {parsed['pureErrorOrderCount']}\n"
        f"Holding map candidate count: {parsed['holdingMapCandidateCount']}\n"
        f"Has single holding candidate: "
        f"{'true' if parsed['hasSingleHoldingCandidate'] else 'false'}\n"
        f"Single holding candidate order ID: {single_candidate if single_candidate else 'null'}\n"
        f"quote_content：{quote_content}\n"
        f"orderList：{_j(order_list)}"
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


SPEC = register(PromptSpec(
    category="option_close",
    name="place_close",
    output_model=ClosePlaceParams,
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
    try:
        result = await OptionClientHttpx().query_close_orders(
            order_ids=order_ids,
            contract_codes=contract_codes,
            room_id=room_id,
            message_id=message_id,
        )
        if result.code == 0 and isinstance(result.data, list):
            return result.data
    except BackendUnreachableError:
        # D2.3：网络不可达保守降级（不阻塞用户提交），下游用空 orderList 继续
        pass
    except Exception:  # noqa: BLE001
        # 业务异常 / 解析失败：降级处理
        pass
    return []


# ============================================================
# 子图 State
# ============================================================


class PlaceCloseState(AgentState, total=False):
    """place_close 子图私有 State：AgentState + `pc_*` 中间态。"""

    pc_parsed: ReferenceParseResult
    pc_order_data: list[dict[str, Any]]
    pc_llm_orders: list[dict[str, Any]]
    pc_llm_output: dict[str, Any]
    pc_close_orders: list[dict[str, Any]]
    pc_reject_reply: str | None
    pc_reject_decision: str | None


class PlaceCloseOutput(TypedDict, total=False):
    """子图对 close 图 / 父图的写回面。"""

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


@safe_node
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


@safe_node
async def place_close_extract(state: PlaceCloseState) -> dict[str, Any]:
    """步骤 4：请求下单和确认全部平仓参数提取（LLM）。"""
    raw = state.get("raw_text", "") or ""
    quote = state.get("quote_content") or ""
    system, _prompt_name = SPEC.render_system(state)
    llm = get_qwen_thinking().with_structured_output(ClosePlaceParams)
    user_message = _build_user_message(raw, quote, state["pc_parsed"], state.get("pc_order_data") or [])
    result: Any = await llm.ainvoke([("system", system), ("user", user_message)])
    llm_output = result.model_dump()
    return {
        "pc_llm_orders": [item.model_dump() for item in result.close_order_list],
        "pc_llm_output": llm_output,
        "trace": [TraceEntry(
            node="place_close_extract",
            decision=f"llm_orders={len(result.close_order_list)}",
            llm_output=llm_output,
        )],
    }


def _normalize_close_orders(
    close_list: list[CloseOrderItem],
    parsed: ReferenceParseResult,
    order_data: list[dict[str, Any]],
    combined: str,
) -> None:
    """确定性后处理（工程层增强，不影响后端语义，仅补全 / 校验参数）。就地修改 close_list。"""
    # "不用跟量"/"不跟量" → 市价单（用户明确不要跟量算法）
    _no_tracking = any(kw in combined for kw in ("不用跟量", "不跟量", "不要跟量"))
    _has_explicit_type = bool(re.search(r"限价|市价|pov\d*|twap", combined, re.IGNORECASE))
    if "正常挂单" in combined and not _has_explicit_type:
        for leg in close_list:
            if leg.confirm_full_close:
                continue
            leg.close_order_type = "市价单" if _no_tracking else "POV"

    # "最大跟量"/"拉满跟量" → POV 25%
    _pov_max_kw = ("最大跟量", "拉满跟量", "全跟量", "跟量拉满", "全部最大")
    if any(k in combined for k in _pov_max_kw):
        for leg in close_list:
            if leg.confirm_full_close:
                continue
            if not leg.close_order_type:
                leg.close_order_type = "POV"
            leg.close_order_pov_ratio = 25

    # "pov25"/"POV25" 等 → 提取数字作为 POV 比例
    _pov_match = re.search(r"pov\s*(\d{1,3})", combined, re.IGNORECASE)
    if _pov_match:
        _pov_val = int(_pov_match.group(1))
        if 1 <= _pov_val <= 100:
            for leg in close_list:
                if leg.confirm_full_close:
                    continue
                if not leg.close_order_type:
                    leg.close_order_type = "POV"
                leg.close_order_pov_ratio = _pov_val

    # === 序号 X / 第 X 笔 → 持仓位置映射（覆盖 LLM 凭空生成的 placeholder orderId）===
    # raw_text 用 "序号1平300万" 引用持仓时，LLM 可能输出 placeholder；按 1-indexed seq
    # 从已查到的 order_data 中按位置取真单号覆盖，确保发给真后端的 orderId 合法。
    _seq_iter = re.finditer(r"序号\s*[:：]?\s*(\d+)|第\s*(\d+)\s*笔", combined)
    _seq_list = [int(m.group(1) or m.group(2)) for m in _seq_iter]

    # 首次按单个合约平仓时，query-close-orders 不负责创建 orderId；用户原文中的
    # OPT-/OPTG- 合约编号是 operate 创建平仓申请所需的确定性身份。
    if len(parsed["contractCodes"]) == 1 and len(close_list) == 1:
        direct_leg = close_list[0]
        direct_leg.internal_trade_id = parsed["contractCodes"][0]
        if not is_order_id(direct_leg.order_id):
            direct_leg.order_id = None

    for _i, _leg in enumerate(close_list):
        if is_order_id(_leg.order_id) or _i >= len(_seq_list):
            continue
        _idx = _seq_list[_i] - 1
        _resolved = False
        if order_data and 0 <= _idx < len(order_data):
            _real = order_data[_idx]
            _real_oid = _real.get("orderId")
            _real_contract_code = _real.get("contractCode")
            _leg.order_id = _real_oid or None
            if _real_contract_code:
                _leg.internal_trade_id = _real_contract_code
            _resolved = bool(_real_oid or _real_contract_code)
        if not _resolved:
            # 查询阶段可能尚无 orderId；只清除 LLM 订单号占位文字，保留首次平仓的合约编号。
            _leg.order_id = None


@safe_node
async def place_close_normalize(state: PlaceCloseState) -> dict[str, Any]:
    """步骤 5：合并输出 + 确定性后处理。空列表 → 交给 reject 边。"""
    parsed = state["pc_parsed"]
    merged = merge_close_orders(parsed["messageType"], parsed["successOrders"], state.get("pc_llm_orders") or [])
    if not merged:
        return {
            "pc_close_orders": [],
            "pc_reject_reply": "未能识别平仓参数，请提供订单号或持仓序号。",
            "pc_reject_decision": "empty_close_order_list",
            "trace": [TraceEntry(node="place_close_normalize", decision="empty_close_order_list")],
        }
    close_list = [CloseOrderItem.model_validate(o) for o in merged]
    combined = f"{state.get('raw_text', '') or ''} {state.get('quote_content') or ''}"
    _normalize_close_orders(close_list, parsed, state.get("pc_order_data") or [], combined)
    return {
        "pc_close_orders": [item.model_dump() for item in close_list],
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


def build_place_close_graph() -> CompiledStateGraph:
    g: StateGraph = StateGraph(PlaceCloseState, output_schema=PlaceCloseOutput)
    g.add_node("place_close_parse", place_close_parse)
    g.add_node("place_close_fetch_orders", place_close_fetch_orders)
    g.add_node("place_close_extract", place_close_extract)
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
def get_place_close_graph() -> CompiledStateGraph:
    return build_place_close_graph()


async def close_place_close(state: AgentState) -> dict[str, Any]:
    """façade：跑 place_close 子图并返回写回面（供直接调用 / 测试；close 图原生嵌入编译图）。"""
    return await get_place_close_graph().ainvoke(state)


__all__ = ["build_place_close_graph", "close_place_close", "get_place_close_graph"]
