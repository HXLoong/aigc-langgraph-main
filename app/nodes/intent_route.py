"""一级路由节点(DSL v2 版,ADR 0015 修订)。

两层处理(对照 dify/yaml/主干工作流.yml):
1. 规则层:「脚本判断期权、互换、其他查询指令」1:1 移植(app/nodes/route_rules.py)
   —— 订单号正则、口语化平仓、互换系统引用、下单特征、平仓查询关键词、关键词计数
2. LLM 兜底:「unknown意图兜底识别」(app/prompts/router/unknown_intent.md)
   —— 仅规则层返回 unknown 且为文本输入时触发

标签 → product_type 映射:
互换-文本/图片/Excel → swap(swap_input_mode 区分三链)
期权-文本 → option;期权平仓-文本 → option_close
无法识别文件类型 → unknown(直接 fallback,不走 LLM;DSL 同语义)

注:DSL 的「兜底意图识别到意图」条件写的是 not contains "unkown"(拼写笔误),
由于 "unknown" 不含子串 "unkown" 该条件恒真,unknown 最终仍经一级分支落 fallback。
本实现按正确语义直接以 unknown → cascade fallback,行为等价。
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, ProductType, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.nodes.route_rules import is_swap_transaction
from app.prompts import load_prompt

logger = logging.getLogger(__name__)


#: DSL 标签 → (product_type, swap_input_mode)
_LABEL_MAP: dict[str, tuple[ProductType, str | None]] = {
    "互换-文本": ("swap", "text"),
    "互换-图片": ("swap", "image"),
    "互换-Excel": ("swap", "excel"),
    "期权-文本": ("option", "text"),
    "期权平仓-文本": ("option_close", "text"),
}


class UnknownIntentOutput(BaseModel):
    """LLM 兜底输出 schema(枚举值与提示词「只输出 1 行枚举值」约定一致)。"""

    label: Literal["互换-文本", "期权-文本", "期权平仓-文本", "unknown"]


async def _classify_with_llm(text: str, quote_content: str | None) -> str:
    """LLM 兜底(unknown意图兜底识别):规则未命中的模糊样本分类。"""
    prompt = load_prompt("router", "unknown_intent")
    llm = get_qwen_thinking().with_structured_output(UnknownIntentOutput)
    user_text = f"query: {text}\n\nquote_content: {quote_content or ''}"
    result: Any = await llm.ainvoke(
        [
            ("system", prompt.system),
            ("user", user_text),
        ]
    )
    return result.label


@safe_node
async def intent_route(state: AgentState) -> dict[str, Any]:
    """一级路由节点。

    出参:
    - product_type: swap / option / option_close / unknown
    - swap_input_mode: text / image / excel(仅 swap;其余产品恒 text)
    - trace.decision: `rule→<label>` 或 `llm→<label>`
    """
    text = state.get("raw_text", "") or ""
    quote = state.get("quote_content")
    files = state.get("input_files") or []

    # 第 1 层:规则(含文件分类)
    label = is_swap_transaction(text, files=files, quote_content=quote)
    source = "rule"

    # 第 2 层:LLM 兜底(仅文本 unknown;文件无法识别按 DSL 直接 fallback)
    if label == "unknown" and not files:
        label = await _classify_with_llm(text, quote)
        source = "llm"

    pt, mode = _LABEL_MAP.get(label, ("unknown", None))

    # 第 3 层:多轮粘性(#167 P1-3,ADR 0015 工程增强)——规则与 LLM 双 unknown 且
    # checkpoint 携带上一轮 product_type 时继承之,避免"确认下单"裸发落 fallback
    if pt == "unknown" and not files:
        prev = state.get("product_type")
        if prev in ("swap", "option", "option_close"):
            pt, mode = prev, "text"
            source, label = "sticky", prev
    update: dict[str, Any] = {
        "product_type": pt,
        "trace": [TraceEntry(node="intent_route", decision=f"{source}→{label}")],
    }
    if pt == "swap":
        update["swap_input_mode"] = mode
    return update


__all__ = ["intent_route", "UnknownIntentOutput"]
