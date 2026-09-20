"""固定节点目录；名称来自现役图，不接受请求指定的 Python 导入路径。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.graph.state import AgentState
from app.nodes.fallback import fallback
from app.nodes.fast_query import existing_command_query, quick_inquiry
from app.nodes.ingest import ingest
from app.nodes.intent_route import intent_route
from app.nodes.persist import persist
from app.nodes.persist_intent import make_persist_intent
from app.nodes.pre_route import pre_route
from app.nodes.record_history import record_history
from app.nodes.remember_confirmed import remember_confirmed_params
from app.nodes.render import render
from app.subgraphs.close import graph as close_graph
from app.subgraphs.close import place_close as pc
from app.subgraphs.close.cancel_close import close_cancel_close
from app.subgraphs.close.confirm_cancel import close_confirm_cancel
from app.subgraphs.close.confirm_close import close_confirm_close
from app.subgraphs.close.holding_query import close_holding_query
from app.subgraphs.close.intent import close_intent
from app.subgraphs.close.query_status import close_query_status
from app.subgraphs.option import extract_inquiry as iq
from app.subgraphs.option import graph as option_graph
from app.subgraphs.option.extract_cancel import option_extract_cancel
from app.subgraphs.option.extract_cancel_place import option_extract_cancel_place
from app.subgraphs.option.extract_confirm_cancel import option_extract_confirm_cancel
from app.subgraphs.option.extract_confirm_place import option_extract_confirm_place
from app.subgraphs.option.extract_place import option_extract_place
from app.subgraphs.option.extract_query import option_extract_query
from app.subgraphs.option.intent import option_intent
from app.subgraphs.swap import graph as swap_graph
from app.subgraphs.swap.apply_picks import swap_apply_picks
from app.subgraphs.swap.cancel import swap_cancel
from app.subgraphs.swap.confirm import swap_confirm
from app.subgraphs.swap.fresh_counterparty import swap_recognize_fresh_counterparty
from app.subgraphs.swap.intent import swap_intent
from app.subgraphs.swap.multimodal import swap_excel_order, swap_image_order
from app.subgraphs.swap.place_order import swap_place_order, swap_place_order_submit
from app.subgraphs.swap.query_order import swap_query_order
from app.subgraphs.swap.select_counterparty import swap_select_counterparty
from app.subgraphs.swap.select_ticker import swap_select_ticker
from app.subgraphs.ticker import resolver as ticker
from app.tools.message_client import MessageClient


class OrgItemState(ticker.OrgItemInput, total=False):
    """单条 ticker 调用承载输入与输出；不包含 fan-out 或 assemble。"""

    winners: list[ticker.OrgWinner]


@dataclass(frozen=True)
class NodeRegistration:
    product: str
    name: str
    action: Any
    input_schema: Any = AgentState
    state_schema: Any = AgentState
    required: tuple[str, ...] = ()
    backend_context: bool = False
    io: bool = False
    with_error_handler: bool = True
    factory: bool = False


def build_registry(
    message_client_factory: Callable[[], MessageClient] | None = None,
) -> tuple[NodeRegistration, ...]:
    """与主图共用注入的 MessageClient 工厂；仅编译子图时调用 factory。"""
    r = NodeRegistration
    return (
        r("main", "ingest", ingest),
        r("main", "quick_inquiry", quick_inquiry, backend_context=True),
        r("main", "existing_command_query", existing_command_query, io=True),
        r("main", "pre_route", pre_route),
        r("main", "intent_route", intent_route, io=True),
        r("main", "swap", swap_graph.build_swap_graph, backend_context=True, factory=True),
        r("main", "option", option_graph.build_option_graph, backend_context=True, factory=True),
        r(
            "main",
            "option_close",
            close_graph.build_close_graph,
            backend_context=True,
            factory=True,
        ),
        r("main", "fallback", fallback),
        r(
            "main",
            "persist_intent",
            make_persist_intent(message_client_factory),
            required=("conversation_id", "message_id") if message_client_factory else (),
        ),
        r("main", "persist", persist),
        r("main", "render", render),
        r("main", "remember_confirmed_params", remember_confirmed_params),
        r("main", "record_history", record_history),
        r("option", "option_intent", option_intent, io=True),
        r(
            "option",
            "option_extract_inquiry",
            iq.build_inquiry_graph,
            backend_context=True,
            factory=True,
        ),
        r("option", "option_extract_place", option_extract_place, backend_context=True),
        r(
            "option",
            "option_extract_confirm_place",
            option_extract_confirm_place,
            backend_context=True,
        ),
        r(
            "option",
            "option_extract_cancel_place",
            option_extract_cancel_place,
            backend_context=True,
        ),
        r("option", "option_extract_cancel", option_extract_cancel, backend_context=True),
        r(
            "option",
            "option_extract_confirm_cancel",
            option_extract_confirm_cancel,
            backend_context=True,
        ),
        r("option", "option_extract_query", option_extract_query, backend_context=True, io=True),
        r("option", "option_unknown", option_graph.option_unknown),
        r(
            "option",
            "inquiry_fast_parse",
            iq.inquiry_fast_parse,
            iq.InquiryState,
            iq.InquiryState,
            io=True,
        ),
        r(
            "option",
            "inquiry_fast_submit",
            iq.inquiry_fast_submit,
            iq.InquiryState,
            iq.InquiryState,
            backend_context=True,
        ),
        r(
            "option",
            "inquiry_precheck",
            iq.inquiry_precheck,
            iq.InquiryState,
            iq.InquiryState,
            io=True,
        ),
        r("option", "inquiry_reject", iq.inquiry_reject, iq.InquiryState, iq.InquiryState),
        r(
            "option",
            "inquiry_extract",
            iq.inquiry_extract,
            iq.InquiryState,
            iq.InquiryState,
            io=True,
        ),
        r(
            "option",
            "inquiry_resolve",
            iq.inquiry_resolve,
            iq.InquiryState,
            iq.InquiryState,
            io=True,
        ),
        r(
            "option",
            "inquiry_submit",
            iq.inquiry_submit,
            iq.InquiryState,
            iq.InquiryState,
            backend_context=True,
        ),
        r("swap", "swap_intent", swap_intent, io=True),
        r("swap", "swap_place_order", swap_place_order, io=True),
        r("swap", "swap_recognize_fresh_counterparty", swap_recognize_fresh_counterparty),
        r("swap", "swap_select_counterparty", swap_select_counterparty, io=True),
        r("swap", "swap_select_ticker", swap_select_ticker, io=True),
        r("swap", "swap_apply_picks", swap_apply_picks),
        r("swap", "swap_place_order_submit", swap_place_order_submit, backend_context=True),
        r("swap", "swap_confirm", swap_confirm, backend_context=True),
        r("swap", "swap_cancel", swap_cancel, backend_context=True),
        r("swap", "swap_query_order", swap_query_order, backend_context=True, io=True),
        r("swap", "swap_unknown", swap_graph.swap_unknown),
        r("swap", "swap_image_order", swap_image_order, required=("input_files",), io=True),
        r("swap", "swap_excel_order", swap_excel_order, required=("input_files",), io=True),
        r("option_close", "close_intent", close_intent, io=True),
        r(
            "option_close",
            "close_holding_query",
            close_holding_query,
            backend_context=True,
            io=True,
        ),
        r(
            "option_close",
            "close_place_close",
            pc.build_place_close_graph,
            backend_context=True,
            factory=True,
        ),
        r("option_close", "close_confirm_close", close_confirm_close, backend_context=True),
        r("option_close", "close_cancel_close", close_cancel_close, backend_context=True),
        r("option_close", "close_confirm_cancel", close_confirm_cancel, backend_context=True),
        r("option_close", "close_query_status", close_query_status, backend_context=True, io=True),
        r("option_close", "close_unknown", close_graph.close_unknown),
        r(
            "option_close",
            "place_close_parse",
            pc.place_close_parse,
            pc.PlaceCloseState,
            pc.PlaceCloseState,
        ),
        r(
            "option_close",
            "place_close_fetch_orders",
            pc.place_close_fetch_orders,
            pc.PlaceCloseState,
            pc.PlaceCloseState,
            required=("pc_parsed",),
            io=True,
        ),
        r(
            "option_close",
            "place_close_extract",
            pc.place_close_extract,
            pc.PlaceCloseState,
            pc.PlaceCloseState,
            required=("pc_parsed",),
            io=True,
        ),
        r(
            "option_close",
            "place_close_normalize",
            pc.place_close_normalize,
            pc.PlaceCloseState,
            pc.PlaceCloseState,
            required=("pc_parsed",),
        ),
        r(
            "option_close",
            "place_close_validate",
            pc.place_close_validate,
            pc.PlaceCloseState,
            pc.PlaceCloseState,
        ),
        r(
            "option_close",
            "place_close_submit",
            pc.place_close_submit,
            pc.PlaceCloseState,
            pc.PlaceCloseState,
            backend_context=True,
        ),
        r(
            "option_close",
            "place_close_reject",
            pc.place_close_reject,
            pc.PlaceCloseState,
            pc.PlaceCloseState,
        ),
        r(
            "ticker",
            "extract_candidates",
            ticker.extract_candidates,
            ticker.TickerState,
            ticker.TickerState,
            required=("raw_text",),
        ),
        r(
            "ticker",
            "infer_codes",
            ticker.infer_codes,
            ticker.TickerState,
            ticker.TickerState,
            required=("candidates",),
            io=True,
            with_error_handler=False,
        ),
        r(
            "ticker",
            "split_keywords",
            ticker.split_keywords,
            ticker.TickerState,
            ticker.TickerState,
            required=("candidates",),
            io=True,
            with_error_handler=False,
        ),
        r(
            "ticker",
            "judge_type",
            ticker.judge_type,
            ticker.TickerState,
            ticker.TickerState,
            required=("candidates",),
            io=True,
            with_error_handler=False,
        ),
        r(
            "ticker",
            "merge_candidates",
            ticker.merge_candidates,
            ticker.TickerState,
            ticker.TickerState,
            required=("raw_text",),
        ),
        r(
            "ticker",
            "resolve_org_item",
            ticker.resolve_org_item,
            ticker.OrgItemInput,
            OrgItemState,
            io=True,
            with_error_handler=False,
        ),
        r("ticker", "assemble", ticker.assemble, ticker.TickerState, ticker.TickerState),
    )
