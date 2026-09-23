"""评测台展示与回放策略；共享节点契约来自应用的轻量目录。"""

from __future__ import annotations

from app.node_execution.catalog import NODE_CATALOG
from harness.node_annotations import NodeDefinition


def _view(
    name: str,
    category: str,
    *,
    replayable: bool,
    annotatable: bool = True,
    annotation_reason: str = "",
) -> NodeDefinition:
    spec = NODE_CATALOG[name]
    if "evaluation" not in spec.surfaces:
        raise ValueError(f"Node not available for evaluation: {name}")
    if replayable and spec.side_effect == "write":
        raise ValueError(f"Write node cannot be replayed: {name}")
    return NodeDefinition(
        name=spec.name,
        product_type="common" if spec.product == "main" else spec.product,
        category=category,
        replayable=replayable,
        side_effect=spec.side_effect,
        annotatable=annotatable,
        annotation_reason=annotation_reason,
        input_fields=spec.input_fields,
        output_fields=spec.output_fields,
        callable_path=spec.callable_path,
    )


_VIEWS = (
    _view("ingest", "输入处理", replayable=True),
    _view("pre_route", "一级路由", replayable=True),
    _view("intent_route", "一级路由", replayable=True),
    _view("quick_inquiry", "快速询价", replayable=False),
    _view("existing_command_query", "存量指令", replayable=True),
    _view(
        "fallback",
        "输出处理",
        replayable=False,
        annotatable=False,
        annotation_reason="仅输出动态 trace 或空对象，无稳定业务输出",
    ),
    _view("render", "输出处理", replayable=True),
    _view("remember_confirmed_params", "会话记忆", replayable=True),
    _view("record_history", "会话记忆", replayable=True),
    _view(
        "persist_intent",
        "持久化",
        replayable=False,
        annotatable=False,
        annotation_reason="仅输出动态 trace 或空对象，无稳定业务输出",
    ),
    _view(
        "persist",
        "持久化",
        replayable=False,
        annotatable=False,
        annotation_reason="仅输出动态 trace 或空对象，无稳定业务输出",
    ),
    _view("swap_intent", "意图识别", replayable=True),
    _view("swap_place_order", "参数提取", replayable=True),
    _view("swap_extract_candidates", "参数候选提取", replayable=True),
    _view("swap_normalize", "参数归一化", replayable=True),
    _view("swap_place_result", "参数汇总", replayable=True),
    _view("swap_recognize_fresh_counterparty", "交易对手识别", replayable=True),
    _view("swap_select_counterparty", "交易对手选择", replayable=True),
    _view("swap_select_ticker", "标的选择", replayable=True),
    _view("swap_apply_picks", "参数合并", replayable=True),
    _view("swap_place_order_submit", "后端写入", replayable=False),
    _view("swap_confirm", "后端写入", replayable=False),
    _view("swap_cancel", "后端写入", replayable=False),
    _view("swap_query_order", "后端查询", replayable=True),
    _view(
        "swap_unknown",
        "兜底",
        replayable=False,
        annotatable=False,
        annotation_reason="仅输出动态 trace 或空对象，无稳定业务输出",
    ),
    _view(
        "swap_image_order",
        "多模态",
        replayable=False,
        annotation_reason="外部文件 URL 存在网络访问风险，仅保留标注",
    ),
    _view(
        "swap_excel_order",
        "多模态",
        replayable=False,
        annotation_reason="外部文件 URL 存在网络访问风险，仅保留标注",
    ),
    _view("option_intent", "意图识别", replayable=True),
    _view("option_extract_inquiry", "询价子图", replayable=False),
    _view("inquiry_extract", "参数提取", replayable=True),
    _view("inquiry_normalize", "参数归一化", replayable=True),
    _view("inquiry_submit", "后端写入", replayable=False),
    _view("option_extract_place", "后端写入", replayable=False),
    _view("option_extract_confirm_place", "后端写入", replayable=False),
    _view("option_extract_cancel_place", "后端写入", replayable=False),
    _view("option_extract_cancel", "后端写入", replayable=False),
    _view("option_extract_confirm_cancel", "后端写入", replayable=False),
    _view("option_extract_query", "后端查询", replayable=True),
    _view(
        "option_unknown",
        "兜底",
        replayable=False,
        annotatable=False,
        annotation_reason="仅输出动态 trace 或空对象，无稳定业务输出",
    ),
    _view("close_intent", "意图识别", replayable=True),
    _view("close_holding_query", "后端查询", replayable=True),
    _view("close_place_close", "平仓申请子图", replayable=False),
    _view("close_confirm_close", "后端写入", replayable=False),
    _view("close_cancel_close", "后端写入", replayable=False),
    _view("close_confirm_cancel", "后端写入", replayable=False),
    _view("close_query_status", "后端查询", replayable=True),
    _view(
        "close_unknown",
        "兜底",
        replayable=False,
        annotatable=False,
        annotation_reason="仅输出动态 trace 或空对象，无稳定业务输出",
    ),
    _view("place_close_parse", "引用解析", replayable=True),
    _view("place_close_fetch_orders", "后端查询", replayable=True),
    _view("place_close_extract", "参数提取", replayable=True),
    _view("place_close_normalize", "参数归一化", replayable=True),
    _view("place_close_validate", "参数校验", replayable=True),
    _view("place_close_submit", "后端写入", replayable=False),
    _view("place_close_reject", "请求拒绝", replayable=True),
)

DEFAULT_NODE_REGISTRY: dict[str, NodeDefinition] = {view.name: view for view in _VIEWS}
if DEFAULT_NODE_REGISTRY.keys() != {
    spec.name for spec in NODE_CATALOG.values() if "evaluation" in spec.surfaces
}:
    raise ValueError("Evaluation policies do not cover the shared catalogue")

__all__ = ["DEFAULT_NODE_REGISTRY"]
