"""swap.place_order 节点 · 互换下单/改单参数提取（P0 核心，最大节点）。

DSL v2 拓扑（互换-意图路由 true 分支）：

    swap_place_order（本文件，互换-规整引用补参摘要[code] → 互换-节点-下单[llm]
                      → ticker resolver）
        → [quote_content 非空且非 "null"]
            → swap_select_counterparty → swap_select_ticker
              （互换-标的对手覆盖聚合[code] 的确定性查表覆盖，拆到两个节点里）
        → [无引用] swap_recognize_fresh_counterparty（独立召回并校验交易对手）
        → swap_place_order_submit（本文件，互换开仓-前置清洗[code] → 互换开仓[code]）

输入：raw_text + quote_content + swap_counterparties + history_messages
输出：state['place_params'] = {expected_action, orderList}
      state['tickers'] = list[TickerCandidate]（来自 ticker resolver）

关键约定：
- 互换下单/改单在 Java 端**共用同一个 `place_order_request` 类型**
  （ADR 0001 D5 / CONTEXT.md），靠 orderList[i].orderId 是否存在区分
- expected_action 由调用方推导：有 orderId → "modify"；否则 → "place"
- ★ 含 ticker resolver 集成（与 option.extract_inquiry 同模板，独立于
  swap.select_ticker——resolver 负责"全新标的"的 GOATS 识别，select_ticker
  负责"引用消息候选标的"的切换/选择，两者互不冲突，resolver 先跑、
  select_ticker 的确定性覆盖若命中则优先生效）
- 后端调用（call_swap_backend）延后到 swap_place_order_submit，确保
  引用选择链或全新对手识别的覆盖已经落到 orderList 上再提交

LLM：complex 模型 + with_structured_output（ADR 0010）。
prompt：app/prompts/swap/place_order.md（DSL v2 互换-节点-下单，最大节点）。
"""
from __future__ import annotations

import re
from typing import Any

from app.graph.business_params import validated_place_params
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_complex
from app.prompts import load_prompt
from app.prompts.spec import PromptSpec, register
from app.subgraphs.swap.backend import _with_resolved_ticker, call_swap_backend
from app.subgraphs.swap.models import SwapPlaceOrderParams
from app.subgraphs.swap.quote_hints import refine_quote_hints
from app.subgraphs.ticker.resolver import resolve_ticker_full


def _format_counterparty_list(counterparties: list[dict[str, Any]] | None) -> str:
    """[{ctptyId,shortName,longName,sort}] → "shortName1, shortName2" 近似 Dify trsShortListStr。"""
    items = counterparties or []
    return ", ".join(
        c.get("shortName", "") for c in items if isinstance(c, dict)
    )


def _build_user_message(
    state: AgentState, hints: dict[str, str], prompt_name: str | None = None
) -> str:
    """渲染 place_order.md 的 [user] 模板（规则文本住在 .md，代码只供变量，ADR 0023）。

    3 个变量：raw_content_for_llm / quote_param_hints（refine_quote_hints 产出）、
    counterparty_list（state["swap_counterparties"]）。
    """
    prompt = load_prompt("swap", prompt_name or SPEC.resolve_name(state))
    return prompt.render_user(
        raw_content_for_llm=hints["raw_content_for_llm"],
        quote_param_hints=hints["quote_param_hints"],
        counterparty_list=_format_counterparty_list(state.get("swap_counterparties")),
    )


def _user_from_state(state: AgentState) -> str:
    hints = refine_quote_hints(state.get("quote_content"), state.get("raw_text", "") or "")
    return _build_user_message(state, hints)


SPEC = register(PromptSpec(
    category="swap",
    name="place_order",
    output_model=SwapPlaceOrderParams,
    inputs=("raw_text", "quote_content", "swap_counterparties", "conversation_id"),
    user_builder=_user_from_state,
    gray=True,
))


def _expected_action(params: SwapPlaceOrderParams) -> str:
    """根据 orderList 中是否有 orderId 推导 expected_action。

    swap 下单/改单共用 place_order_request 意图（ADR 0001 D5 / CONTEXT.md）：
    - 任一订单有 orderId → "modify"
    - 全部 orderId=null → "place"
    """
    if any(item.order_id for item in params.order_list):
        return "modify"
    return "place"


@safe_node
async def swap_place_order(state: AgentState) -> dict[str, Any]:
    """swap.place_order 节点（提取阶段，不调后端）。

    出参约定：
    - place_params: {expected_action, orderList}（草稿，标的/对手候选覆盖 + 后端
      提交由下游 swap_select_counterparty / swap_select_ticker /
      swap_place_order_submit 接力完成）
    - tickers: list[TickerCandidate]（resolver 输出，from_goats=True）
    - trace: 单条 TraceEntry，记录 action + 订单数 + 标的数
    """
    raw_text = state.get("raw_text", "") or ""
    quote_content = state.get("quote_content")

    # 1. 互换-规整引用补参摘要（确定性 code，纯函数移植）
    hints = refine_quote_hints(quote_content, raw_text)

    # 2. LLM 提取下单参数
    system, prompt_name = SPEC.render_system(state)
    llm = get_qwen_complex().with_structured_output(SwapPlaceOrderParams)
    params: Any = await llm.ainvoke(
        [("system", system), ("user", _build_user_message(state, hints, prompt_name))]
    )

    # 3. ticker resolver 识别标的（独立通道，含 HITL 信号；与 swap.select_ticker
    #    的候选标的切换互不冲突，resolver 先填，select_ticker 命中会再覆盖）
    resolution = await resolve_ticker_full(
        raw_text,
        filter_order_context=True,
        counterparty_shortnames=[
            c["shortName"] for c in state.get("swap_counterparties") or []
            if isinstance(c.get("shortName"), str)
        ],
    )
    tickers = resolution.resolved

    action = _expected_action(params)
    order_list = []
    ticker_bindings = []
    for index, item in enumerate(params.order_list):
        order, match_result = _with_resolved_ticker(item.model_dump(), tickers)
        order_list.append(order)
        ticker_bindings.append({
            "order_index": index,
            "original_wind_code": item.place_order_wind_code,
            "resolved_wind_code": order.get("placeOrderWindCode"),
            "result": match_result,
        })

    decision = (
        f"action={action},"
        f" orders={len(params.order_list)},"
        f" tickers={len(tickers)},"
        f" hitl={len(resolution.hitl_pending)}"
    )

    out: dict = {
        "place_params": validated_place_params(expected_action=action, orderList=order_list),
        "tickers": tickers,
        "trace": [
            TraceEntry(
                node="swap_place_order",
                decision=decision,
                llm_output={
                    "prompt_name": prompt_name,  # ADR 0003 灰度硬前置：trace 记录实际加载文件名
                    "params": params.model_dump(),
                    "tickers_count": len(tickers),
                    "hitl_count": len(resolution.hitl_pending),
                    "ticker_bindings": ticker_bindings,
                },
            )
        ],
    }
    if resolution.hitl_pending:
        out["ticker_hitl_candidates"] = resolution.hitl_pending
    return out


_ORDER_ID_PATTERN = re.compile(r"H-\d{8}-\d+")


@safe_node
async def swap_place_order_submit(state: AgentState) -> dict[str, Any]:
    """swap.place_order_submit 节点（互换开仓-前置清洗 → 互换开仓）。

    汇总 swap_place_order（+ 可选 swap_select_counterparty / swap_select_ticker
    覆盖后）的 state['place_params']，调真后端 POST
    /admin-api/swap-order/operate，并把后端返回的真实订单号回写到
    orderList[i].orderId，供结构化 state、trace 和输出观测使用。用户可见回复始终
    原样透传 api_result，不使用回写后的参数重新渲染。
    """
    place_params = state.get("place_params") or {}
    action = place_params.get("expected_action", "")
    order_list = [dict(item) for item in (place_params.get("orderList") or [])]

    backend = await call_swap_backend(
        state,
        intent="place_order_request",
        order_list=order_list,
    )

    if backend.get("api_code") == 0:
        data = backend.get("api_result")
        oids: list[str] = []
        if isinstance(data, dict) and data.get("orderId"):
            oids = [data["orderId"]]
        elif isinstance(data, list):
            oids = [
                item["orderId"]
                for item in data
                if isinstance(item, dict) and item.get("orderId")
            ]
        elif isinstance(data, str):
            # backend 返回文本如 "下单成功 H-20260514-XXX" → regex 抓 H-YYYYMMDD-NNNN
            oids = _ORDER_ID_PATTERN.findall(data)
        for i, oid in enumerate(oids):
            if i < len(order_list) and oid:
                order_list[i]["orderId"] = oid

    return {
        "place_params": validated_place_params(expected_action=action, orderList=order_list),
        **backend,
        "trace": [
            TraceEntry(
                node="swap_place_order_submit",
                decision=f"orders={len(order_list)},api_code={backend.get('api_code')}",
            )
        ],
    }


__all__ = ["swap_place_order", "swap_place_order_submit"]
