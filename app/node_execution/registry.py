"""固定节点目录；名称来自现役图，不接受请求指定的 Python 导入路径。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, get_type_hints

from pydantic import BaseModel
from typing_extensions import is_typeddict

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
from app.tools.bot_context import REQUIRED_FIELDS
from app.tools.message_client import MessageClient


class OrgItemState(ticker.OrgItemInput, total=False):
    """单条 ticker 调用承载输入与输出；不包含 fan-out 或 assemble。"""

    winners: list[ticker.OrgWinner]


@dataclass(frozen=True)
class NodeRegistration:
    product: str
    name: str
    action: Any
    input_fields: tuple[str, ...] = field(kw_only=True)
    input_schema: Any = AgentState
    state_schema: Any = AgentState
    required: tuple[str, ...] = ()
    backend_context: bool = False
    io: bool = False
    with_error_handler: bool = True
    factory: bool = False

    def __post_init__(self) -> None:
        if len(self.input_fields) != len(set(self.input_fields)):
            raise ValueError(f"Duplicate input field declaration: {self.product}/{self.name}")
        schema_fields = _schema_fields(self.input_schema)
        unknown = set(self.effective_input_fields) - schema_fields
        if unknown:
            raise ValueError(
                f"Unknown input fields for {self.product}/{self.name}: {sorted(unknown)}"
            )
        required = _schema_required_fields(self.input_schema) | set(self.required)
        missing = required - set(self.effective_input_fields)
        if missing:
            raise ValueError(
                f"Required fields not declared for {self.product}/{self.name}: {sorted(missing)}"
            )

    @property
    def effective_input_fields(self) -> tuple[str, ...]:
        fields = self.input_fields + (REQUIRED_FIELDS if self.backend_context else ())
        return tuple(dict.fromkeys(fields))


def _schema_fields(schema: Any) -> set[str]:
    if is_typeddict(schema):
        return set(get_type_hints(schema, include_extras=True))
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return set(schema.model_fields)
    raise TypeError(f"Unsupported node input schema: {schema!r}")


def _schema_required_fields(schema: Any) -> set[str]:
    if is_typeddict(schema):
        return set(schema.__required_keys__)
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return {name for name, info in schema.model_fields.items() if info.is_required()}
    raise TypeError(f"Unsupported node input schema: {schema!r}")


_BOT_CONTEXT_OPTIONAL: tuple[str, ...] = (
    "guid",
    "operator_user_id",
    "raw_text",
    "quote_content",
    "quote_appinfo",
)


def build_registry(
    message_client_factory: Callable[[], MessageClient] | None = None,
) -> tuple[NodeRegistration, ...]:
    """与主图共用注入的 MessageClient 工厂；仅编译子图时调用 factory。"""
    r = NodeRegistration
    return (
        r("main", "ingest", ingest, input_fields=("room_id", "trace_id")),
        r(
            "main",
            "quick_inquiry",
            quick_inquiry,
            input_fields=("raw_text", "quote_content", "quote_appinfo", "guid"),
            backend_context=True,
        ),
        r(
            "main",
            "existing_command_query",
            existing_command_query,
            input_fields=("raw_text", "room_id", "operator_user_id", "user_id"),
            io=True,
        ),
        r(
            "main",
            "pre_route",
            pre_route,
            input_fields=(
                "option_counterparties_raw",
                "swap_counterparties_raw",
                "quote_content",
            ),
        ),
        r(
            "main",
            "intent_route",
            intent_route,
            input_fields=("raw_text", "quote_content", "input_files", "product_type"),
            io=True,
        ),
        r(
            "main",
            "swap",
            swap_graph.build_swap_graph,
            input_fields=(
                "swap_input_mode",
                "error",
                "intent",
                "input_files",
                "place_params",
                "tickers",
                "swap_counterparty_picks",
                "swap_ticker_picks",
                "quote_ticker_candidates",
                "last_confirmed_params",
                "swap_counterparties",
                *_BOT_CONTEXT_OPTIONAL,
            ),
            backend_context=True,
            factory=True,
        ),
        r(
            "main",
            "option",
            option_graph.build_option_graph,
            input_fields=(
                "error",
                "intent",
                "history_messages",
                "bot_name",
                "option_counterparties",
                "last_confirmed_params",
                "tickers",
                *_BOT_CONTEXT_OPTIONAL,
            ),
            backend_context=True,
            factory=True,
        ),
        r(
            "main",
            "option_close",
            close_graph.build_close_graph,
            input_fields=(
                "error",
                "intent",
                "history_messages",
                "option_counterparties",
                "last_confirmed_params",
                "conversation_orders",
                *_BOT_CONTEXT_OPTIONAL,
            ),
            backend_context=True,
            factory=True,
        ),
        r("main", "fallback", fallback, input_fields=("error",)),
        r(
            "main",
            "persist_intent",
            make_persist_intent(message_client_factory),
            input_fields=("conversation_id", "message_id", "intent", "product_type"),
            required=("conversation_id", "message_id") if message_client_factory else (),
        ),
        r(
            "main",
            "persist",
            persist,
            input_fields=(
                "trace",
                "message_id",
                "conversation_id",
                "trace_id",
                "product_type",
                "intent",
            ),
        ),
        r(
            "main",
            "render",
            render,
            input_fields=(
                "reply_text",
                "product_type",
                "api_result",
                "error",
                "ticker_hitl_candidates",
                "tickers",
                "place_params",
                "raw_text",
                "intent",
                "quote_content",
                "close_params",
                "cancel_params",
                "confirm",
                "expected_action",
            ),
        ),
        r(
            "main",
            "remember_confirmed_params",
            remember_confirmed_params,
            input_fields=(
                "product_type",
                "expected_action",
                "error",
                "api_code",
                "intent",
                "message_id",
                "place_params",
                "confirm",
                "cancel_params",
                "close_params",
                "api_result",
            ),
        ),
        r(
            "main",
            "record_history",
            record_history,
            input_fields=("raw_text", "reply_text"),
        ),
        r(
            "option",
            "option_intent",
            option_intent,
            input_fields=(
                "raw_text",
                "quote_content",
                "history_messages",
                "bot_name",
                "option_counterparties",
            ),
            io=True,
        ),
        r(
            "option",
            "option_extract_inquiry",
            iq.build_inquiry_graph,
            input_fields=(
                "error",
                "history_messages",
                "tickers",
                *_BOT_CONTEXT_OPTIONAL,
            ),
            backend_context=True,
            factory=True,
        ),
        r(
            "option",
            "option_extract_place",
            option_extract_place,
            input_fields=("history_messages", *_BOT_CONTEXT_OPTIONAL),
            backend_context=True,
        ),
        r(
            "option",
            "option_extract_confirm_place",
            option_extract_confirm_place,
            input_fields=("history_messages", "last_confirmed_params", *_BOT_CONTEXT_OPTIONAL),
            backend_context=True,
        ),
        r(
            "option",
            "option_extract_cancel_place",
            option_extract_cancel_place,
            input_fields=_BOT_CONTEXT_OPTIONAL,
            backend_context=True,
        ),
        r(
            "option",
            "option_extract_cancel",
            option_extract_cancel,
            input_fields=_BOT_CONTEXT_OPTIONAL,
            backend_context=True,
        ),
        r(
            "option",
            "option_extract_confirm_cancel",
            option_extract_confirm_cancel,
            input_fields=("last_confirmed_params", *_BOT_CONTEXT_OPTIONAL),
            backend_context=True,
        ),
        r(
            "option",
            "option_extract_query",
            option_extract_query,
            input_fields=_BOT_CONTEXT_OPTIONAL,
            backend_context=True,
            io=True,
        ),
        r("option", "option_unknown", option_graph.option_unknown, input_fields=("intent",)),
        r(
            "option",
            "inquiry_fast_parse",
            iq.inquiry_fast_parse,
            iq.InquiryState,
            iq.InquiryState,
            input_fields=("raw_text",),
            io=True,
        ),
        r(
            "option",
            "inquiry_fast_submit",
            iq.inquiry_fast_submit,
            iq.InquiryState,
            iq.InquiryState,
            input_fields=("iq_rfq_data", *_BOT_CONTEXT_OPTIONAL),
            backend_context=True,
        ),
        r(
            "option",
            "inquiry_precheck",
            iq.inquiry_precheck,
            iq.InquiryState,
            iq.InquiryState,
            input_fields=("raw_text",),
            io=True,
        ),
        r(
            "option",
            "inquiry_reject",
            iq.inquiry_reject,
            iq.InquiryState,
            iq.InquiryState,
            input_fields=("iq_reject_reply",),
        ),
        r(
            "option",
            "inquiry_extract",
            iq.inquiry_extract,
            iq.InquiryState,
            iq.InquiryState,
            input_fields=("raw_text", "quote_content", "history_messages"),
            io=True,
        ),
        r(
            "option",
            "inquiry_resolve",
            iq.inquiry_resolve,
            iq.InquiryState,
            iq.InquiryState,
            input_fields=("raw_text", "iq_order_list"),
            io=True,
        ),
        r(
            "option",
            "inquiry_submit",
            iq.inquiry_submit,
            iq.InquiryState,
            iq.InquiryState,
            input_fields=(
                "iq_order_list",
                "tickers",
                "iq_hitl",
                "iq_backend_order_list",
                "iq_types",
                "iq_raw_params",
                "iq_bindings",
                *_BOT_CONTEXT_OPTIONAL,
            ),
            backend_context=True,
        ),
        r(
            "swap",
            "swap_intent",
            swap_intent,
            input_fields=("raw_text", "quote_content", "swap_counterparties", "conversation_id"),
            io=True,
        ),
        r(
            "swap",
            "swap_place_order",
            swap_place_order,
            input_fields=("raw_text", "quote_content", "swap_counterparties", "conversation_id"),
            io=True,
        ),
        r(
            "swap",
            "swap_recognize_fresh_counterparty",
            swap_recognize_fresh_counterparty,
            input_fields=("raw_text", "swap_counterparties", "place_params"),
        ),
        r(
            "swap",
            "swap_select_counterparty",
            swap_select_counterparty,
            input_fields=("raw_text", "swap_counterparties", "quote_content"),
            io=True,
        ),
        r(
            "swap",
            "swap_select_ticker",
            swap_select_ticker,
            input_fields=("raw_text", "quote_content", "quote_ticker_candidates"),
            io=True,
        ),
        r(
            "swap",
            "swap_apply_picks",
            swap_apply_picks,
            input_fields=(
                "place_params",
                "swap_counterparty_picks",
                "swap_counterparties",
                "swap_ticker_picks",
                "quote_ticker_candidates",
            ),
        ),
        r(
            "swap",
            "swap_place_order_submit",
            swap_place_order_submit,
            input_fields=("place_params", *_BOT_CONTEXT_OPTIONAL),
            backend_context=True,
        ),
        r(
            "swap",
            "swap_confirm",
            swap_confirm,
            input_fields=("intent", "last_confirmed_params", *_BOT_CONTEXT_OPTIONAL),
            backend_context=True,
        ),
        r(
            "swap",
            "swap_cancel",
            swap_cancel,
            input_fields=_BOT_CONTEXT_OPTIONAL,
            backend_context=True,
        ),
        r(
            "swap",
            "swap_query_order",
            swap_query_order,
            input_fields=_BOT_CONTEXT_OPTIONAL,
            backend_context=True,
            io=True,
        ),
        r("swap", "swap_unknown", swap_graph.swap_unknown, input_fields=("intent",)),
        r(
            "swap",
            "swap_image_order",
            swap_image_order,
            input_fields=("input_files", "conversation_id", "swap_counterparties", "raw_text"),
            required=("input_files",),
            io=True,
        ),
        r(
            "swap",
            "swap_excel_order",
            swap_excel_order,
            input_fields=("input_files", "conversation_id", "raw_text"),
            required=("input_files",),
            io=True,
        ),
        r(
            "option_close",
            "close_intent",
            close_intent,
            input_fields=("raw_text", "quote_content", "history_messages"),
            io=True,
        ),
        r(
            "option_close",
            "close_holding_query",
            close_holding_query,
            input_fields=("option_counterparties", *_BOT_CONTEXT_OPTIONAL),
            backend_context=True,
            io=True,
        ),
        r(
            "option_close",
            "close_place_close",
            pc.build_place_close_graph,
            input_fields=("error", *_BOT_CONTEXT_OPTIONAL),
            backend_context=True,
            factory=True,
        ),
        r(
            "option_close",
            "close_confirm_close",
            close_confirm_close,
            input_fields=("last_confirmed_params", *_BOT_CONTEXT_OPTIONAL),
            backend_context=True,
        ),
        r(
            "option_close",
            "close_cancel_close",
            close_cancel_close,
            input_fields=("conversation_orders", *_BOT_CONTEXT_OPTIONAL),
            backend_context=True,
        ),
        r(
            "option_close",
            "close_confirm_cancel",
            close_confirm_cancel,
            input_fields=("last_confirmed_params", *_BOT_CONTEXT_OPTIONAL),
            backend_context=True,
        ),
        r(
            "option_close",
            "close_query_status",
            close_query_status,
            input_fields=_BOT_CONTEXT_OPTIONAL,
            backend_context=True,
            io=True,
        ),
        r("option_close", "close_unknown", close_graph.close_unknown, input_fields=("intent",)),
        r(
            "option_close",
            "place_close_parse",
            pc.place_close_parse,
            pc.PlaceCloseState,
            pc.PlaceCloseState,
            input_fields=("raw_text", "quote_content"),
        ),
        r(
            "option_close",
            "place_close_fetch_orders",
            pc.place_close_fetch_orders,
            pc.PlaceCloseState,
            pc.PlaceCloseState,
            input_fields=("pc_parsed", "room_id", "message_id"),
            required=("pc_parsed",),
            io=True,
        ),
        r(
            "option_close",
            "place_close_extract",
            pc.place_close_extract,
            pc.PlaceCloseState,
            pc.PlaceCloseState,
            input_fields=("raw_text", "quote_content", "pc_parsed", "pc_order_data"),
            required=("pc_parsed",),
            io=True,
        ),
        r(
            "option_close",
            "place_close_normalize",
            pc.place_close_normalize,
            pc.PlaceCloseState,
            pc.PlaceCloseState,
            input_fields=(
                "pc_parsed",
                "pc_llm_orders",
                "raw_text",
                "quote_content",
                "pc_order_data",
            ),
            required=("pc_parsed",),
        ),
        r(
            "option_close",
            "place_close_validate",
            pc.place_close_validate,
            pc.PlaceCloseState,
            pc.PlaceCloseState,
            input_fields=("pc_close_orders",),
        ),
        r(
            "option_close",
            "place_close_submit",
            pc.place_close_submit,
            pc.PlaceCloseState,
            pc.PlaceCloseState,
            input_fields=("pc_close_orders", "pc_llm_output", *_BOT_CONTEXT_OPTIONAL),
            backend_context=True,
        ),
        r(
            "option_close",
            "place_close_reject",
            pc.place_close_reject,
            pc.PlaceCloseState,
            pc.PlaceCloseState,
            input_fields=(
                "pc_close_orders",
                "pc_reject_reply",
                "pc_reject_decision",
                "pc_llm_output",
            ),
        ),
        r(
            "ticker",
            "extract_candidates",
            ticker.extract_candidates,
            ticker.TickerState,
            ticker.TickerState,
            input_fields=("raw_text",),
            required=("raw_text",),
        ),
        r(
            "ticker",
            "infer_codes",
            ticker.infer_codes,
            ticker.TickerState,
            ticker.TickerState,
            input_fields=("candidates",),
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
            input_fields=("candidates",),
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
            input_fields=("candidates",),
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
            input_fields=("raw_text", "infer_codes", "split_codes", "ins_family"),
            required=("raw_text",),
        ),
        r(
            "ticker",
            "resolve_org_item",
            ticker.resolve_org_item,
            ticker.OrgItemInput,
            OrgItemState,
            input_fields=("index", "org_str", "keywords", "predicted_family"),
            io=True,
            with_error_handler=False,
        ),
        r(
            "ticker",
            "assemble",
            ticker.assemble,
            ticker.TickerState,
            ticker.TickerState,
            input_fields=("candidates", "winners"),
        ),
    )
