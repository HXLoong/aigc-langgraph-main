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
    "main_graph": NodeLabel("交易指令处理", "graph"),
    "ingest": NodeLabel("消息接收与状态初始化"),
    "entry_route": NodeLabel("业务入口分流"),
    "quick_inquiry": NodeLabel("期权快速询价", "io"),
    "existing_command_query": NodeLabel("存量交易指令查询", "io"),
    "pre_route": NodeLabel("交易对手与候选信息整理"),
    "intent_route": NodeLabel("业务类型识别", "hybrid"),
    "swap": NodeLabel("互换业务", "graph"),
    "option": NodeLabel("期权开仓与订单操作", "graph"),
    "option_close": NodeLabel("期权平仓", "graph"),
    "fallback": NodeLabel("异常与未知指令处理"),
    "render": NodeLabel("业务结果回复"),
    "persist_intent": NodeLabel("消息会话与意图写回", "io"),
    "persist": NodeLabel("节点执行记录入库", "io"),
    "remember_confirmed_params": NodeLabel("保存已确认订单信息"),
    "record_history": NodeLabel("记录会话历史"),
    "swap_intent": NodeLabel("互换意图识别", "hybrid"),
    "swap_place_order": NodeLabel("互换下单处理", "graph"),
    "swap_extract_candidates": NodeLabel("互换订单候选抽取", "llm"),
    "swap_normalize": NodeLabel("互换订单参数归一化"),
    "swap_place_result": NodeLabel("互换下单参数汇总"),
    "swap_recognize_fresh_counterparty": NodeLabel("互换新单交易对手识别", "hybrid"),
    "swap_select_counterparty": NodeLabel("互换交易对手选择", "hybrid"),
    "swap_select_ticker": NodeLabel("互换标的选择", "hybrid"),
    "swap_apply_picks": NodeLabel("互换候选选择结果合并"),
    "swap_place_order_submit": NodeLabel("互换订单提交", "io"),
    "swap_confirm": NodeLabel("互换确认协议处理", "io"),
    "swap_cancel": NodeLabel("互换撤单", "io"),
    "swap_query_order": NodeLabel("互换订单查询", "io"),
    "swap_unknown": NodeLabel("互换未知意图与错误出口"),
    "swap_image_order": NodeLabel("互换图片订单识别", "llm"),
    "swap_excel_order": NodeLabel("互换Excel订单识别", "llm"),
    "option_intent": NodeLabel("期权意图识别", "hybrid"),
    "option_extract_inquiry": NodeLabel("期权询价处理", "graph"),
    "option_extract_place": NodeLabel("期权开仓补参与下单", "io"),
    "option_extract_confirm_place": NodeLabel("期权确认下单", "io"),
    "option_extract_cancel_place": NodeLabel("期权取消下单", "io"),
    "option_extract_cancel": NodeLabel("期权撤单申请", "io"),
    "option_extract_confirm_cancel": NodeLabel("期权确认撤单", "io"),
    "option_extract_query": NodeLabel("期权订单查询", "io"),
    "option_unknown": NodeLabel("期权未知意图与错误出口"),
    "inquiry_fast_parse": NodeLabel("期权快速询价参数解析", "io"),
    "inquiry_fast_submit": NodeLabel("期权快速询价提交", "io"),
    "inquiry_extract": NodeLabel("期权询价要素抽取", "llm"),
    "inquiry_normalize": NodeLabel("期权询价参数归一化"),
    "inquiry_submit": NodeLabel("期权询价提交", "io"),
    "close_intent": NodeLabel("期权平仓意图识别", "hybrid"),
    "close_holding_query": NodeLabel("期权持仓查询要素处理", "llm"),
    "close_place_close": NodeLabel("期权平仓申请", "graph"),
    "close_confirm_close": NodeLabel("期权确认平仓", "io"),
    "close_cancel_close": NodeLabel("期权平仓撤单申请", "io"),
    "close_confirm_cancel": NodeLabel("期权平仓确认撤单", "io"),
    "close_query_status": NodeLabel("期权平仓订单查询", "io"),
    "close_unknown": NodeLabel("期权平仓未知意图与错误出口"),
    "place_close_parse": NodeLabel("期权平仓引用解析"),
    "place_close_fetch_orders": NodeLabel("查询平仓关联订单", "io"),
    "place_close_extract": NodeLabel("期权平仓要素抽取", "llm"),
    "place_close_normalize": NodeLabel("期权平仓参数归一化"),
    "place_close_validate": NodeLabel("期权平仓参数校验"),
    "place_close_submit": NodeLabel("期权平仓申请提交", "io"),
    "place_close_reject": NodeLabel("期权平仓拒绝处理"),
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
        original_name.startswith(("_route", "route_", "fan_out_", "dispatch_"))
        or original_name in {"route", "select_entry_branch"}
    ):
        name = stage("路由判断", original_name)

    projected.update(otc_node_id=node, otc_node_label_zh=zh or None,
                     otc_original_run_name=original_name)
    return ObservationLabel(name=name, node_id=node, metadata=projected)
