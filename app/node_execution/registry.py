"""从共享目录构建固定执行节点；State schema、重试和客户端注入由执行平台负责。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from importlib import import_module
from typing import Any, get_type_hints

from pydantic import BaseModel
from typing_extensions import is_typeddict

from app.config import get_settings
from app.graph.instructions import build_instructions_graph, plan_instructions
from app.graph.main import build_main_graph
from app.graph.state import AgentState
from app.node_execution.catalog import NODE_CATALOG
from app.tools.bot_context import REQUIRED_FIELDS
from app.tools.message_client import MessageClient


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


# 执行策略与回放权限独立；IO 重试资格不代表允许回放写操作。
_EXECUTION_OPTIONS: dict[str, dict[str, Any]] = {
    "quick_inquiry": {"backend_context": True},
    "existing_command_query": {"io": True},
    "intent_route": {"io": True},
    "swap": {"backend_context": True, "factory": True},
    "option": {"backend_context": True, "factory": True},
    "option_close": {"backend_context": True, "factory": True},
    "option_intent": {"io": True},
    "option_extract_inquiry": {"backend_context": True, "factory": True},
    "option_extract_place": {"backend_context": True},
    "option_extract_confirm_place": {"backend_context": True},
    "option_extract_cancel_place": {"backend_context": True},
    "option_extract_cancel": {"backend_context": True},
    "option_extract_confirm_cancel": {"backend_context": True},
    "option_extract_query": {"backend_context": True, "io": True},
    "inquiry_extract": {
        "io": True,
        "input_schema": "app.subgraphs.option.extract_inquiry:InquiryState",
        "state_schema": "app.subgraphs.option.extract_inquiry:InquiryState",
    },
    "inquiry_normalize": {
        "input_schema": "app.subgraphs.option.extract_inquiry:InquiryState",
        "state_schema": "app.subgraphs.option.extract_inquiry:InquiryState",
    },
    "inquiry_submit": {
        "backend_context": True,
        "input_schema": "app.subgraphs.option.extract_inquiry:InquiryState",
        "state_schema": "app.subgraphs.option.extract_inquiry:InquiryState",
    },
    "swap_intent": {"io": True},
    "swap_recognize_fresh_counterparty": {"io": True},
    "swap_select_counterparty": {"io": True},
    "swap_select_ticker": {"io": True},
    "swap_place_order_submit": {"backend_context": True},
    "swap_confirm": {"backend_context": True},
    "swap_cancel": {"backend_context": True},
    "swap_query_order": {"backend_context": True, "io": True},
    "swap_image_order": {"io": True, "required": ("input_files",)},
    "swap_excel_order": {"io": True, "required": ("input_files",)},
    "close_intent": {"io": True},
    "close_holding_query": {"backend_context": True, "io": True},
    "close_place_close": {"backend_context": True, "factory": True},
    "close_confirm_close": {"backend_context": True},
    "close_cancel_close": {"backend_context": True},
    "close_confirm_cancel": {"backend_context": True},
    "close_query_status": {"backend_context": True, "io": True},
    "place_close_parse": {
        "input_schema": "app.subgraphs.close.place_close:PlaceCloseState",
        "state_schema": "app.subgraphs.close.place_close:PlaceCloseState",
    },
    "place_close_fetch_orders": {
        "io": True,
        "required": ("pc_parsed",),
        "input_schema": "app.subgraphs.close.place_close:PlaceCloseState",
        "state_schema": "app.subgraphs.close.place_close:PlaceCloseState",
    },
    "place_close_extract": {
        "io": True,
        "required": ("pc_parsed",),
        "input_schema": "app.subgraphs.close.place_close:PlaceCloseState",
        "state_schema": "app.subgraphs.close.place_close:PlaceCloseState",
    },
    "place_close_normalize": {
        "required": ("pc_parsed",),
        "input_schema": "app.subgraphs.close.place_close:PlaceCloseState",
        "state_schema": "app.subgraphs.close.place_close:PlaceCloseState",
    },
    "place_close_validate": {
        "input_schema": "app.subgraphs.close.place_close:PlaceCloseState",
        "state_schema": "app.subgraphs.close.place_close:PlaceCloseState",
    },
    "place_close_submit": {
        "backend_context": True,
        "input_schema": "app.subgraphs.close.place_close:PlaceCloseState",
        "state_schema": "app.subgraphs.close.place_close:PlaceCloseState",
    },
    "place_close_reject": {
        "input_schema": "app.subgraphs.close.place_close:PlaceCloseState",
        "state_schema": "app.subgraphs.close.place_close:PlaceCloseState",
    },
}


def _load(path: str) -> Any:
    module, attribute = path.split(":", 1)
    return getattr(import_module(module), attribute)


def build_registry(
    message_client_factory: Callable[[], MessageClient] | None = None,
) -> tuple[NodeRegistration, ...]:
    """保留执行面暴露范围；复合图在 NodeExecutor 构造时才编译。"""
    registrations = []
    for spec in NODE_CATALOG.values():
        if "execution" not in spec.surfaces:
            continue
        options = dict(_EXECUTION_OPTIONS.get(spec.name, {}))
        for key in ("input_schema", "state_schema"):
            if key in options:
                options[key] = _load(options[key])
        action = _load(spec.callable_path)
        if spec.name == "persist_intent":
            action = action(message_client_factory)
            options["required"] = (
                ("conversation_id", "message_id") if message_client_factory else ()
            )
        registrations.append(
            NodeRegistration(
                product=spec.product,
                name=spec.name,
                action=action,
                input_fields=spec.input_fields,
                **options,
            )
        )
    return tuple(registrations)
