"""普通期权询价：原文证据提取 → 参数归一化 → Java 处理 orderList。

快速询价仅由主图 fast_query 标志选择 quick_inquiry，不根据产品关键词改换链路。
"""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any, TypedDict, get_args

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.extraction.candidates import (
    candidate_model,
    evidence_sources,
    unpack_candidates,
)
from app.extraction.fields import EvidenceError, FieldRecord, merge_fields
from app.graph.business_params import validated_place_params
from app.graph.cascade import has_error
from app.graph.retry import add_io_node, io_node
from app.graph.safe_node import safe_node
from app.graph.state import (
    AgentState,
    ErrorInfo,
    ExpectedAction,
    TraceEntry,
    merge_by_id,
)
from app.llm.clients import get_qwen_thinking
from app.prompts import blocks
from app.prompts.spec import PromptSpec, register
from app.subgraphs.option.backend import call_option_backend
from app.subgraphs.option.models import (
    OptionContractType,
    OptionInquiryParams,
    OptionInquiryRawParams,
    OptionOrderItem,
)
from app.subgraphs.option.normalize import compound_call_strike, expand_inquiry_items
from app.subgraphs.option.prompting import EXTRACT_INPUTS
from app.subgraphs.option.sanitize import sanitize_order_list

#: 询价支持的期权类型（枚举唯一真源：models.OptionContractType）
_SUPPORTED_OPTION_TYPES: tuple[str, ...] = get_args(OptionContractType)
#: 用户给出原文后必须解析成功的字段（原文字段名 = 展开后字段名）→ 回复用标签
_PARSED_FIELDS = (
    ("strike_percentage", "执行价格"),
    ("notional_amount", "名义本金"),
    ("participation_rate", "参与率"),
)

CANDIDATE_MODEL = candidate_model(OptionInquiryRawParams)
SPEC = register(PromptSpec(
    category="option",
    name="extract_inquiry",
    output_model=CANDIDATE_MODEL,
    inputs=EXTRACT_INPUTS,
    user_builder=blocks.source_payload,
))


class InquiryState(AgentState, total=False):
    """询价子图私有 State：AgentState + `iq_*` 中间态。"""

    iq_raw_params: dict[str, Any]
    iq_field_records: dict[str, FieldRecord]
    iq_order_list: list[dict[str, Any]]
    iq_types: list[str]


class InquiryOutput(TypedDict, total=False):
    """子图对 option 图 / 父图的写回面。"""

    expected_action: ExpectedAction | None
    place_params: dict[str, Any] | None
    reply_text: str | None
    api_result: str | dict[str, Any] | list[Any] | None
    api_code: int | None
    trace: Annotated[list[TraceEntry], merge_by_id]
    error: ErrorInfo | None
    field_records: Annotated[dict[str, FieldRecord], merge_fields]


# ============================================================
# 阶段节点
# ============================================================


@io_node
async def inquiry_extract(state: InquiryState) -> dict[str, Any]:
    """LLM 只产出候选与证据；未验证的输出不能进入归一化或后端。"""
    messages, _prompt_name = SPEC.build_messages(state)
    llm = get_qwen_thinking().with_structured_output(CANDIDATE_MODEL)
    candidates = CANDIDATE_MODEL.model_validate(await llm.ainvoke(messages))
    raw_params, records = unpack_candidates(
        OptionInquiryRawParams, candidates, evidence_sources(state), scope="option/inquiry",
    )
    return {
        "iq_raw_params": raw_params.model_dump(), "iq_field_records": records,
        "trace": [TraceEntry(node="inquiry_extract", decision=f"verified_fields={len(records)}")],
    }


@safe_node
async def inquiry_normalize(state: InquiryState) -> dict[str, Any]:
    """代码归一化与多值展开，并把证据绑定到展开后的每笔订单。"""
    raw_params = OptionInquiryRawParams.model_validate(state.get("iq_raw_params") or {})
    expanded: list[dict[str, Any]] = []
    records: dict[str, FieldRecord] = {}
    for index, raw_item in enumerate(raw_params.order_list):
        prefix = f"option/inquiry.orderList.{index}."
        source_records = state.get("iq_field_records") or {}
        derived_strike = (
            compound_call_strike(raw_item.option_type) is not None
            and not (raw_item.strike_percentage or "").strip()
        )
        type_record = source_records.get(prefix + "optionType")
        if derived_strike and (
            type_record is None or type_record.value != raw_item.option_type
            or not raw_item.option_type or raw_item.option_type not in type_record.evidence
        ):
            raise EvidenceError("复合期权表达缺少已验证的原文证据，不能派生执行价。")
        items = expand_inquiry_items([raw_item])
        if raw_item.tenor and any(item["tenor"] is None for item in items):
            return {"reply_text": "期限无法转换为正整数月份，请明确所有期限后重新提交。",
                    "trace": [TraceEntry(node="inquiry_normalize", decision="invalid_tenor")]}
        # 用户明确给出却无法解析的参数与期限同口径：提示修正，不静默置空后询价
        for field, label in _PARSED_FIELDS:
            if getattr(raw_item, field) and any(item[field] is None for item in items):
                return {"reply_text": f"{label}无法识别，请明确{label}后重新提交。",
                        "trace": [TraceEntry(node="inquiry_normalize", decision=f"invalid_{field}")]}
        unsupported = [item["option_type"] for item in items
                       if item["option_type"] and item["option_type"] not in _SUPPORTED_OPTION_TYPES]
        if unsupported:
            return {"reply_text": f"暂不支持期权类型「{unsupported[0]}」，目前支持："
                                  f"{'、'.join(_SUPPORTED_OPTION_TYPES)}。请修改后重新询价。",
                    "trace": [TraceEntry(node="inquiry_normalize", decision="unsupported_option_type")]}
        for item in items:
            canonical_item = OptionOrderItem.model_validate(item).model_dump()
            target = f"option/inquiry.orderList.{len(expanded)}."
            for path, record in source_records.items():
                if path.startswith(prefix):
                    alias = path[len(prefix):]
                    records[target + alias] = record.model_copy(update={
                        "value": canonical_item.get(alias), "locked": alias not in {"stockCode", "shortName"},
                    })
            if derived_strike and type_record is not None:
                # 关联到本笔订单的类型证据；多期限展开后仍保留各自原文来源。
                records[target + "strikePercentage"] = type_record.model_copy(update={
                    "value": canonical_item["strikePercentage"], "locked": True,
                    "derived_from": [target + "optionType"],
                })
            expanded.append(item)
    params = OptionInquiryParams.model_validate({"orderList": expanded})
    order_list = sanitize_order_list([item.model_dump() for item in params.order_list])
    return {
        "iq_order_list": order_list,
        "iq_types": [item.option_type for item in params.order_list if item.option_type],
        "field_records": records,
        "trace": [TraceEntry(node="inquiry_normalize", decision=f"orders={len(order_list)}")],
    }


@safe_node
async def inquiry_submit(state: InquiryState) -> dict[str, Any]:
    """调真后端询价（建单，不重试）；汇总条目沿用 option_extract_inquiry 名。"""
    order_list = state.get("iq_order_list") or []
    backend = await call_option_backend(
        state, intent="new_inquiry", order_list=order_list
    )
    decision = (
        f"action=inquiry,"
        f" orders={len(order_list)},"
        f" types={state.get('iq_types') or []},"
        " instrument_resolution=backend"
    )
    out: dict[str, Any] = {
        "expected_action": "inquiry",
        "place_params": validated_place_params(orderList=order_list),
        **backend,
        "trace": [
            TraceEntry(node="inquiry_submit", decision=f"api_code={backend.get('api_code')}"),
            TraceEntry(
                node="option_extract_inquiry",
                decision=decision,
                llm_output={
                    "raw_params": state.get("iq_raw_params"),
                },
            ),
        ],
    }
    return out


# ============================================================
# 拓扑
# ============================================================


def _route_or_end(next_node: str):  # type: ignore[no-untyped-def]
    def _router(state: InquiryState) -> str:
        return END if has_error(state) or state.get("reply_text") else next_node

    return _router


def build_inquiry_graph() -> CompiledStateGraph[InquiryState, None, AgentState, InquiryOutput]:
    g: StateGraph[InquiryState, None, AgentState, InquiryOutput] = StateGraph(InquiryState, input_schema=AgentState, output_schema=InquiryOutput)
    add_io_node(g, "inquiry_extract", inquiry_extract)
    g.add_node("inquiry_normalize", inquiry_normalize)
    g.add_node("inquiry_submit", inquiry_submit)

    g.add_edge(START, "inquiry_extract")
    g.add_conditional_edges("inquiry_extract", _route_or_end("inquiry_normalize"), ["inquiry_normalize", END])
    g.add_conditional_edges("inquiry_normalize", _route_or_end("inquiry_submit"), ["inquiry_submit", END])
    g.add_edge("inquiry_submit", END)
    return g.compile(name="option_extract_inquiry")


@lru_cache(maxsize=1)
def get_inquiry_graph() -> CompiledStateGraph[InquiryState, None, AgentState, InquiryOutput]:
    return build_inquiry_graph()


async def option_extract_inquiry(state: AgentState) -> dict[str, Any]:
    """façade：跑询价子图并返回写回面（供直接调用 / 测试；option 图原生嵌入编译图）。"""
    return await get_inquiry_graph().ainvoke(state)


__all__ = [
    "InquiryOutput",
    "InquiryState",
    "build_inquiry_graph",
    "get_inquiry_graph",
    "option_extract_inquiry",
]
