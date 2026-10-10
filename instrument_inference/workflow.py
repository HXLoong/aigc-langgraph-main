"""推断、字面分词与类型判断并行；每次运行使用全新的独立 State。"""

from __future__ import annotations

import json
import operator
import re
import uuid
from datetime import datetime
from typing import Annotated, Any, TypedDict
from zoneinfo import ZoneInfo

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.safe_node import safe_node
from app.graph.state import ErrorInfo, TraceEntry
from app.parsing.tool_workflow import invoke_tool_model, merge_tool_errors, parse_list
from app.prompts.spec import PromptSpec
from instrument_inference.models import CodeInference, InstrumentFamilies, LiteralKeywords


class InferenceState(TypedDict, total=False):
    raw_list: str
    transaction_types: str
    inference_prompt: str
    items: list[str]
    current_date: str
    inferred: dict[str, list[str]]
    split: dict[str, list[str]]
    families: dict[str, str]
    error: Annotated[ErrorInfo | None, merge_tool_errors]
    trace: Annotated[list[TraceEntry], operator.add]
    trace_id: str
    outputs: dict[str, Any]


def _user(state: InferenceState) -> str:
    return json.dumps(state["items"], ensure_ascii=False)


CODE_SPEC = PromptSpec(
    category="instrument",
    name="infer_codes",
    output_model=CodeInference,
    inputs=("items", "current_date", "transaction_types", "inference_prompt"),
    state_schema=InferenceState,
    user_builder=_user,
    injects={
        "{{current_date}}": lambda s: s["current_date"],
        "{{transaction_types}}": lambda s: s["transaction_types"],
        "{{inference_prompt}}": lambda s: s.get("inference_prompt", ""),
    },
)
SPLIT_SPEC = PromptSpec(
    category="instrument",
    name="split_keywords",
    output_model=LiteralKeywords,
    inputs=("items",),
    state_schema=InferenceState,
    user_builder=_user,
)
FAMILY_SPEC = PromptSpec(
    category="instrument",
    name="classify_family",
    output_model=InstrumentFamilies,
    inputs=("items",),
    state_schema=InferenceState,
    user_builder=_user,
)

# 原 YAML 的后缀识别集合，仅保留后缀，不引入证券名称到代码的映射。
FULL_CODE_REGEX = re.compile(
    r"\.(TWO|SH|SZ|BJ|HK|TW|KS|KQ|SG|KL|BK|JK|PS|VN|AX|NZ|NS|BO|KA|CM|TO|CN|MX|DE|PA|AS|BR|LS|SW|MI|MA|ST|OL|CO|HE|IC|WA|PR|BD|VI|AT|IS|IR|MC|TL|RG|VS|BE|DU|MU|HM|HA|SR|AE|QA|KW|TA|BH|AM|JO|CA|NR|CS|LG|SA|BA|SN|LM|T|J|N|O|V|L|F)$"
)
MARKET_WORDS = frozenset(
    [
        "A股",
        "沪市",
        "深市",
        "沪股",
        "深股",
        "北交所",
        "新三板",
        "科创板",
        "创业板",
        "主板",
        "港股",
        "美股",
        "日股",
        "英股",
    ]
)
FUTURE_DATE_PREFIX = re.compile(r"^(\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])?)([^\d].*)$")


@safe_node
async def parse_inputs(state: InferenceState) -> dict[str, Any]:
    values = parse_list(state["raw_list"])
    items: list[str] = []
    for value in values:
        if value is None or value == "":
            continue
        if not isinstance(value, str):
            raise ValueError("list 内的标的表达必须是字符串")
        if value not in items:
            items.append(value)
    return {
        "items": items,
        "transaction_types": json.dumps(
            parse_list(state.get("transaction_types", "[]")),
            ensure_ascii=False,
        ),
        "outputs": {"result": []},
    }


@safe_node
async def prepare_time(state: InferenceState) -> dict[str, Any]:
    return {"current_date": datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y/%m/%d %H:%M:%S")}


def _check_keys(result: dict[str, Any], items: list[str]) -> None:
    if set(result) != set(items):
        raise ValueError("模型结果未逐项覆盖原始输入，或包含输入之外的项")


@safe_node
async def infer_codes(state: InferenceState, config: RunnableConfig) -> dict[str, Any]:
    result = await invoke_tool_model(CODE_SPEC, state, CodeInference, config)
    _check_keys(result.result, state["items"])
    return {"inferred": result.result}


@safe_node
async def split_keywords(state: InferenceState, config: RunnableConfig) -> dict[str, Any]:
    result = await invoke_tool_model(SPLIT_SPEC, state, LiteralKeywords, config)
    _check_keys(result.result, state["items"])
    return {"split": result.result}


@safe_node
async def classify_family(state: InferenceState, config: RunnableConfig) -> dict[str, Any]:
    result = await invoke_tool_model(FAMILY_SPEC, state, InstrumentFamilies, config)
    _check_keys(result.result, state["items"])
    return {"families": result.result}


@safe_node
async def merge_keywords(state: InferenceState) -> dict[str, Any]:
    # fan-in barrier 已等待三个分支；任一失败都禁止部分结果成功。
    if state.get("error"):
        return {"outputs": {}}
    groups: list[dict[str, Any]] = []
    for original in dict.fromkeys([*state["inferred"], *state["split"]]):
        words = list(
            dict.fromkeys(
                w
                for w in [
                    *state["inferred"][original],
                    *state["split"][original],
                    original,
                ]
                if w
            )
        )
        match = FUTURE_DATE_PREFIX.match(original)
        if match and state["families"].get(original, "").upper().strip() == "FUTURE":
            normalized = match[2] + match[1]
            if normalized not in words:
                words.append(normalized)
        keywords: list[dict[str, Any]] = []
        for word in words:
            if word in MARKET_WORDS:
                continue
            full = FULL_CODE_REGEX.search(word) is not None
            ident = uuid.uuid4().hex
            keywords.append({"id": ident, "keyword": word, "isFull": full})
            stripped = word.lstrip("0")
            if full and stripped != word:
                keywords.append({"id": ident, "keyword": stripped, "isFull": full})
        groups.append({"orgStr": original, "keywords": keywords})
    return {
        "outputs": {
            "result": groups,
            "insFamily": json.dumps(state["families"], ensure_ascii=False),
        }
    }


def _after_parse(state: InferenceState) -> str:
    return END if state.get("error") or not state.get("items") else "prepare_time"


def _after_time(state: InferenceState) -> str | list[str]:
    return END if state.get("error") else ["infer_codes", "split_keywords", "classify_family"]


def build_graph() -> CompiledStateGraph[InferenceState, None, InferenceState, InferenceState]:
    graph = StateGraph(InferenceState)
    for node in (
        parse_inputs,
        prepare_time,
        infer_codes,
        split_keywords,
        classify_family,
        merge_keywords,
    ):
        graph.add_node(node.__name__, node)
    graph.add_edge(START, "parse_inputs")
    graph.add_conditional_edges("parse_inputs", _after_parse)
    graph.add_conditional_edges("prepare_time", _after_time)
    graph.add_edge(["infer_codes", "split_keywords", "classify_family"], "merge_keywords")
    graph.add_edge("merge_keywords", END)
    return graph.compile()
