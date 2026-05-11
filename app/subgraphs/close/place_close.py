"""close.place_close 节点 · 平仓下单参数提取（P0 核心）。

输入：raw_text + quote_content + 上游数据（holding map / error order ids /
order list / full-close confirmation list）
输出：state['close_params'] = ClosePlaceParams.model_dump()

骨架阶段范围（M2 Day 11）：
- LLM 提取 closeOrderList（9 字段 × N 订单）
- 上游数据（holding map / orderList 等）暂留空——后续 PR 接入：
  · holding map 来自 close.holding_query 的输出
  · orderList 来自 OptionClient.query_close_orders（M3 联调阶段）

注：close.place_close **不依赖 ticker resolver**——平仓基于订单号
（CO- / OPT- / OPTG-），标的代码已在订单中确定。

LLM：standard 模型 + with_structured_output（ADR 0010）。
prompt：app/prompts/option_close/place_close.md（1036 行，最大平仓 prompt）。
"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_structured
from app.prompts import load_prompt
from app.subgraphs.close.models import ClosePlaceParams


def _build_user_message(state: AgentState) -> str:
    """组装 user message。

    骨架阶段：仅传 raw_text + quote_content。后续 PR 加上：
    - holding map: 从 state['holding_map'] 或上游 holding_query 输出读
    - error order id list / full-close confirmation list / orderList
      （来自 OptionClient.query_close_orders 响应）
    """
    raw_content = state.get("raw_text", "") or ""
    quote_content = state.get("quote_content") or ""
    return (
        f"用户发送消息：{raw_content}\n"
        f"用户引用消息：{quote_content}"
    )


@safe_node
async def close_place_close(state: AgentState) -> dict[str, Any]:
    """close.place_close 节点。

    出参约定：
    - close_params: dict（ClosePlaceParams.model_dump()）
    - trace: 单条 TraceEntry，记录提取的订单数 + 类型分布
    """
    prompt = load_prompt("option_close", "place_close")
    llm = get_qwen_structured().with_structured_output(ClosePlaceParams)

    user_message = _build_user_message(state)
    result: Any = await llm.ainvoke(
        [
            ("system", prompt.system),
            ("user", user_message),
        ]
    )

    # === 确定性后处理 ===
    raw = state.get("raw_text", "") or ""
    quote = state.get("quote_content") or ""
    combined = f"{raw} {quote}"
    close_list = result.closeOrderList

    # "不用跟量"/"不跟量" → 跳过 POV，设市价单
    _no_tracking = any(kw in combined for kw in ("不用跟量", "不跟量", "不要跟量"))
    _has_explicit_type = any(kw in combined for kw in ("限价", "市价", "POV", "pov", "TWAP"))
    if "正常挂单" in combined and not _has_explicit_type:
        for leg in close_list:
            leg.closeOrderType = "市价单" if _no_tracking else "POV"

    # "最大跟量"/"拉满跟量" → POV 25%
    _pov_max_kw = ("最大跟量", "拉满跟量", "全跟量", "跟量拉满", "全部最大")
    if any(k in combined for k in _pov_max_kw):
        for leg in close_list:
            if not leg.closeOrderType:
                leg.closeOrderType = "POV"
            leg.closeOrderPovRatio = 25

    # trace 决策摘要：订单数 + 价格类型分布
    types = [
        item.closeOrderType
        for item in close_list
        if item.closeOrderType
    ]
    full_closes = sum(1 for item in close_list if item.confirmFullClose)
    decision = (
        f"orders={len(close_list)},"
        f" types={types},"
        f" full_close={full_closes}"
    )

    return {
        "close_params": result.model_dump(),
        "trace": [
            TraceEntry(
                node="close_place_close",
                decision=decision,
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["close_place_close"]
