"""节点标注数据获取与持久化。"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import get_settings


@dataclass(frozen=True, slots=True)
class NodeDefinition:
    """一个可展示、可选回归的 LangGraph 业务节点定义。"""

    name: str
    product_type: str
    category: str
    replayable: bool
    side_effect: str
    annotatable: bool = True
    annotation_reason: str = ""
    input_fields: tuple[str, ...] = ()
    output_fields: tuple[str, ...] = ()
    callable_path: str = ""


@dataclass(frozen=True, slots=True)
class NodeObservation:
    """供工作台展示和标注的标准节点 observation。"""

    observation_id: str
    trace_id: str
    turn: int
    name: str
    product_type: str
    category: str
    replayable: bool
    side_effect: str
    annotatable: bool = True
    annotation_reason: str = ""
    output_fields: tuple[str, ...] = ()
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    start_time: str = ""


_AUTO_DISCOVERY_VIEW_ONLY_REASON = "自动发现节点仅输出动态 trace 或内部字段，无稳定公共输出"


def _infer_product_type(name: str, metadata: Mapping[str, Any]) -> str:
    declared = metadata.get("product_type")
    if isinstance(declared, str) and declared:
        return declared
    if name.startswith(("close_", "place_close_")):
        return "option_close"
    if name.startswith(("option_", "inquiry_")):
        return "option"
    if name.startswith("swap_"):
        return "swap"
    return "common"


def _auto_discovered_definition(
    name: str,
    *,
    node_input: Mapping[str, Any],
    node_output: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> NodeDefinition:
    """为注册表尚未知晓的新节点生成 fail-closed 契约。"""
    output_fields = tuple(
        key
        for key in node_output
        if key != "trace" and not str(key).startswith("_")
    )
    annotatable = bool(output_fields)
    return NodeDefinition(
        name=name,
        product_type=_infer_product_type(name, metadata),
        category="自动发现",
        replayable=False,
        side_effect="unknown",
        annotatable=annotatable,
        annotation_reason=("" if annotatable else _AUTO_DISCOVERY_VIEW_ONLY_REASON),
        input_fields=tuple(
            key for key in node_input if not str(key).startswith("_")
        ),
        output_fields=output_fields,
    )


def definition_for_observation(
    observation: NodeObservation,
    registry: Mapping[str, NodeDefinition],
) -> NodeDefinition:
    """返回已声明契约；未知节点沿用读取时生成的安全契约。"""
    definition = registry.get(observation.name)
    if definition is not None:
        return definition
    return NodeDefinition(
        name=observation.name,
        product_type=observation.product_type,
        category=observation.category,
        replayable=False,
        side_effect="unknown",
        annotatable=observation.annotatable,
        annotation_reason=observation.annotation_reason,
        input_fields=tuple(
            key for key in observation.input if not str(key).startswith("_")
        ),
        output_fields=observation.output_fields,
    )


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {"_raw": value}
    return dict(parsed) if isinstance(parsed, Mapping) else {"_value": parsed}


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        return dict(dumped) if isinstance(dumped, Mapping) else {}
    return {}


def _canonical_graph_node_name(display_name: str, metadata: Mapping[str, Any]) -> str:
    """从原始或带中文标签的 Langfuse observation 中提取稳定节点名。"""
    declared = metadata.get("langgraph_node")
    if not isinstance(declared, str) or not declared:
        return ""
    if display_name == declared or display_name.endswith(f"[{declared}]"):
        return declared
    return ""


def read_trace_observations(api: Any, trace_id: str) -> list[dict[str, Any]]:
    """读取一个 Trace 的全部 observation，并处理 v2 cursor 分页。"""
    observations: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        attempts = 0
        while True:
            try:
                page = api.observations.get_many(
                    trace_id=trace_id,
                    fields="core,basic,metadata,io",
                    limit=1000,
                    cursor=cursor,
                )
                break
            except httpx.ConnectTimeout:
                attempts += 1
                if attempts >= 3:
                    raise
        observations.extend(_as_mapping(item) for item in getattr(page, "data", []) or [])
        meta = getattr(page, "meta", None)
        next_cursor = (
            meta.get("cursor")
            if isinstance(meta, Mapping)
            else getattr(meta, "cursor", None)
        )
        if not isinstance(next_cursor, str) or not next_cursor:
            return observations
        cursor = next_cursor


def normalize_node_observations(
    observations: Sequence[Mapping[str, Any]],
    *,
    trace_id: str,
    turn: int,
    registry: Mapping[str, NodeDefinition],
) -> list[NodeObservation]:
    """把 Langfuse rows 归一化，并移除 LLM/Parser/Router 等内部 observation。"""
    nodes: list[NodeObservation] = []
    for raw in observations:
        display_name = str(raw.get("name") or "")
        metadata = _json_object(raw.get("metadata"))
        name = _canonical_graph_node_name(display_name, metadata)
        if not name:
            continue
        node_input = _json_object(raw.get("input"))
        node_output = _json_object(raw.get("output"))
        definition = registry.get(name) or _auto_discovered_definition(
            name,
            node_input=node_input,
            node_output=node_output,
            metadata=metadata,
        )
        nodes.append(
            NodeObservation(
                observation_id=str(raw.get("id") or ""),
                trace_id=trace_id,
                turn=turn,
                name=name,
                product_type=definition.product_type,
                category=definition.category,
                replayable=definition.replayable,
                side_effect=definition.side_effect,
                annotatable=definition.annotatable,
                annotation_reason=definition.annotation_reason,
                output_fields=definition.output_fields,
                input=node_input,
                output=node_output,
                metadata=metadata,
                start_time=str(raw.get("start_time") or raw.get("startTime") or ""),
            )
        )
    return sorted(nodes, key=lambda node: (node.start_time, node.observation_id))


def collect_case_nodes(
    case_result: dict[str, Any],
    api: Any,
    *,
    registry: Mapping[str, NodeDefinition],
) -> list[NodeObservation]:
    """聚合一条多轮测试用例在 Langfuse 中的业务节点。"""
    nodes: list[NodeObservation] = []
    for reference in extract_trace_references(case_result):
        trace_id = str(reference["trace_id"])
        turn = int(reference["turn"])
        nodes.extend(
            normalize_node_observations(
                read_trace_observations(api, trace_id),
                trace_id=trace_id,
                turn=turn,
                registry=registry,
            )
        )
    return sorted(nodes, key=lambda node: (node.turn, node.start_time, node.observation_id))


def load_case_nodes_from_langfuse(
    case_result: dict[str, Any],
    *,
    client_factory: Callable[..., Any] | None = None,
    registry: Mapping[str, NodeDefinition] | None = None,
) -> list[NodeObservation]:
    """使用项目配置从 Langfuse 读取一条用例的节点数据。"""
    if not extract_trace_references(case_result):
        raise ValueError("该运行没有可用的 Langfuse Trace，请重新执行用例后再标注")
    settings = get_settings()
    if not (
        settings.enable_langfuse
        and settings.langfuse_public_key
        and settings.langfuse_secret_key
    ):
        raise RuntimeError("Langfuse 未启用或项目密钥未配置")
    if client_factory is None:
        from langfuse import Langfuse

        client_factory = Langfuse
    if registry is None:
        from harness.node_registry import DEFAULT_NODE_REGISTRY

        registry = DEFAULT_NODE_REGISTRY
    client = client_factory(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        base_url=settings.langfuse_base_url,
        timeout=15,
    )
    # Langfuse 按 public key 复用进程级资源，单次读取后 shutdown 会关闭共享后台线程；
    # 后续请求再次复用该资源时可能永远阻塞在队列 join。SDK 已注册 atexit 统一回收。
    return collect_case_nodes(case_result, client.api, registry=registry)


def extract_trace_references(case_result: dict[str, Any]) -> list[dict[str, Any]]:
    """提取用例每轮真正承载 LangGraph 节点的 Langfuse Trace。"""
    references: list[dict[str, Any]] = []
    seen: set[str] = set()
    for turn, turn_result in enumerate(case_result.get("turns") or [], start=1):
        outputs = turn_result.get("outputs") if isinstance(turn_result, dict) else None
        trace_id = None
        if isinstance(outputs, dict):
            trace_id = outputs.get("langfuse_trace_id")
        if isinstance(trace_id, str) and trace_id and trace_id not in seen:
            seen.add(trace_id)
            references.append({"turn": turn, "trace_id": trace_id})
    if references:
        return references

    parent_trace_id = case_result.get("trace_id")
    if isinstance(parent_trace_id, str) and parent_trace_id:
        return [{"turn": 1, "trace_id": parent_trace_id}]
    return []


__all__ = [
    "NodeDefinition",
    "NodeObservation",
    "collect_case_nodes",
    "definition_for_observation",
    "extract_trace_references",
    "load_case_nodes_from_langfuse",
    "normalize_node_observations",
    "read_trace_observations",
]
