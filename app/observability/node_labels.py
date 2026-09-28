"""Stable display labels for technical graph nodes, independent of business data."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

NodeKind = Literal["code", "llm", "hybrid", "io", "graph"]


@dataclass(frozen=True)
class NodeLabel:
    zh: str
    kind: NodeKind = "code"


NODE_LABELS: dict[str, NodeLabel] = {
    "close_clean_request": NodeLabel("平仓请求参数清洗"),
    "close_submit": NodeLabel("平仓业务请求提交", "io"),
    "close_query_backend": NodeLabel("平仓只读请求提交", "io"),
    "swap_clean_request": NodeLabel("互换请求参数清洗"),
    "swap_submit": NodeLabel("互换业务请求提交", "io"),
    "swap_query_backend": NodeLabel("互换只读请求提交", "io"),
    "option_clean_request": NodeLabel("期权请求参数清洗"),
    "option_submit": NodeLabel("期权业务请求提交", "io"),
    "option_query_backend": NodeLabel("期权只读请求提交", "io"),
    "parse_instruction": NodeLabel("业务指令联合解析", "llm"),
    "prepare_input": NodeLabel("文本与Excel输入准备", "io"),
    "prepare_parse_context": NodeLabel("解析前只读上下文", "io"),
    "main_graph": NodeLabel("交易指令处理", "graph"),
    "ingest": NodeLabel("消息接收与状态初始化"),
    "entry_route": NodeLabel("业务入口分流"),
    "quick_inquiry": NodeLabel("期权快速询价", "io"),
    "existing_command_query": NodeLabel("存量交易指令查询", "io"),
    "pre_route": NodeLabel("交易对手与候选信息整理"),
    "intent_route": NodeLabel("业务类型规则判断"),
    "swap": NodeLabel("互换业务", "graph"),
    "option": NodeLabel("期权开仓与订单操作", "graph"),
    "option_close": NodeLabel("期权平仓", "graph"),
    "fallback": NodeLabel("异常与未知指令处理"),
    "render": NodeLabel("业务结果回复"),
    "persist_intent": NodeLabel("消息会话与意图写回", "io"),
    "persist": NodeLabel("节点执行记录入库", "io"),
    "remember_confirmed_params": NodeLabel("保存已确认订单信息"),
    "record_history": NodeLabel("记录会话历史"),
    "swap_intent": NodeLabel("互换解析结果检查"),
    "swap_place_order": NodeLabel("互换下单处理", "graph"),
    "swap_prepare": NodeLabel("互换参数准备"),
    "swap_validate": NodeLabel("互换来源检查"),
    "swap_place_result": NodeLabel("互换下单参数汇总"),
    "swap_apply_picks": NodeLabel("互换候选选择结果合并"),
    "swap_place_order_submit": NodeLabel("互换原始请求准备"),
    "swap_confirm": NodeLabel("互换确认协议处理"),
    "swap_cancel": NodeLabel("互换撤单"),
    "swap_query_order": NodeLabel("互换订单查询"),
    "swap_unknown": NodeLabel("互换未知意图与错误出口"),
    "option_intent": NodeLabel("期权解析结果检查"),
    "option_extract_inquiry": NodeLabel("期权询价处理", "graph"),
    "option_extract_place": NodeLabel("期权开仓补参与下单"),
    "option_extract_confirm_place": NodeLabel("期权确认下单"),
    "option_extract_cancel_place": NodeLabel("期权取消下单"),
    "option_extract_cancel": NodeLabel("期权撤单申请"),
    "option_extract_confirm_cancel": NodeLabel("期权确认撤单"),
    "option_extract_query": NodeLabel("期权订单查询"),
    "option_unknown": NodeLabel("期权未知意图与错误出口"),
    "inquiry_prepare": NodeLabel("期权询价参数准备"),
    "inquiry_validate": NodeLabel("期权询价来源检查"),
    "inquiry_submit": NodeLabel("期权询价请求准备"),
    "close_intent": NodeLabel("期权平仓解析结果检查"),
    "close_holding_query": NodeLabel("期权持仓查询"),
    "close_place_close": NodeLabel("期权平仓申请", "graph"),
    "close_confirm_close": NodeLabel("期权确认平仓"),
    "close_cancel_close": NodeLabel("期权平仓撤单申请"),
    "close_confirm_cancel": NodeLabel("期权平仓确认撤单"),
    "close_query_status": NodeLabel("期权平仓订单查询"),
    "close_unknown": NodeLabel("期权平仓未知意图与错误出口"),
    "place_close_prepare": NodeLabel("期权平仓参数准备"),
    "place_close_validate": NodeLabel("期权平仓参数校验"),
    "place_close_submit": NodeLabel("期权平仓请求准备"),
}

_FRAMEWORK_STEPS = {
    "RunnableSequence": ("结构化处理链", "chain"),
    "RunnableParallel": ("并行处理", "parallel"),
    "RunnableLambda": ("函数调用", "function"),
    "PydanticToolsParser": ("输出校验", "parser"),
    "PydanticOutputParser": ("输出校验", "parser"),
    "JsonOutputKeyToolsParser": ("输出解析", "parser"),
    "StrOutputParser": ("文本输出解析", "parser"),
    "__start__": ("子图输入准备", "__start__"),
    "__end__": ("子图结果返回", "__end__"),
}


@dataclass(frozen=True)
class ObservationLabel:
    name: str
    node_id: str | None
    metadata: dict[str, Any]


def label_observation(
    original_name: str, *, kind: str, metadata: Mapping[str, Any] | None = None,
    parent_node: str | None = None,
) -> ObservationLabel:
    """Project callback names only; keep graph identity and model metadata untouched."""
    projected = dict(metadata or {})
    raw_node = projected.get("langgraph_node")
    node = raw_node if isinstance(raw_node, str) and raw_node not in {"__start__", "__end__"} else parent_node
    error_node = original_name.removeprefix("__error_handler__")
    if original_name.startswith("__error_handler__"):
        node = error_node
    elif kind == "chain" and original_name in NODE_LABELS:
        node = original_name
    elif original_name == "LangGraph":
        node = node or "main_graph"
    label = NODE_LABELS.get(node or "")
    zh = label.zh if label else ""
    name = original_name

    def stage(title: str, suffix: str, *, llm: bool = False) -> str:
        """将框架步骤映射为中文展示名，保留原始节点身份。"""
        description = f"{zh} · {title}" if zh else title
        identity = f"{node}/{suffix}" if node else original_name
        return f"{'[LLM] ' if llm else ''}{description} [{identity}]"

    if kind == "llm":
        name = stage("模型调用", "llm", llm=True)
    elif original_name.startswith("__error_handler__") and label:
        name = stage("重试耗尽处理", "error_handler")
    elif original_name == "LangGraph" and label:
        name = f"{zh} [main_graph]" if node == "main_graph" else f"{zh}子图 [{node}/graph]"
    elif original_name in NODE_LABELS:
        if label and label.kind == "graph" and node == parent_node:
            name = f"{zh}子图 [{node}/graph]"
        else:
            prefix = {"llm": "[LLM] ", "hybrid": "[Code/LLM] "}.get(label.kind if label else "", "")
            name = f"{prefix}{zh} [{node}]"
    elif original_name in _FRAMEWORK_STEPS:
        name = stage(*_FRAMEWORK_STEPS[original_name])
    elif (
        original_name.startswith(("_route", "_after_", "route_", "fan_out_", "dispatch_"))
        or original_name in {"route", "select_entry_branch", "after_prepare", "after_clean"}
    ):
        name = stage("路由判断", original_name)

    projected.update(otc_node_id=node, otc_node_label_zh=zh or None,
                     otc_original_run_name=original_name)
    return ObservationLabel(name=name, node_id=node, metadata=projected)
