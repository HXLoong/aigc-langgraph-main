"""路由前置提取(DSL v2「交易对手、候选标的提取」1:1 移植)。

对照源:Dify 主干工作流同名 code 节点（Dify 资产已冻结于 tag dify-assets-frozen-20260917，ADR 0024 D1）。
- option/trs:后端预查对手 JSON 串 → 精简列表(ctptyId/shortName/longName/sort)
- quote_content:引用消息中的候选标的块 → [{orderId, orderSeq, candidates:[{seq,code,name}]}]

节点写入 state 字段(由 app/graph/state.py 统一声明):
option_counterparties / swap_counterparties / quote_ticker_candidates。
是否切标的的意图判断在「互换-选择标的」LLM 节点,本节点不做。
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.domain.order_ids import SWAP_ORDER_ID_RE
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry

ORDER_SEP = "-----场外收益互换详情-----"
CAND_BEGIN = "匹配到其他标的"
CAND_END = "如果以上"

_ORDER_ID_RE = SWAP_ORDER_ID_RE
_ORDER_SEQ_RE = re.compile(r"序号[：:]\s*(\d+)")
_CAND_START_RE = re.compile(r"(\d+)\s*\.\s*([A-Za-z0-9.]+)\s*-\s*")


def _pick_fields(item: dict[str, Any]) -> dict[str, Any]:
    """对手对象只保留 ctptyId/shortName/longName/sort(sort 供下游确定性选对手)。"""
    return {
        "ctptyId": item.get("ctptyId"),
        "shortName": item.get("shortName"),
        "longName": item.get("longName"),
        "sort": item.get("sort"),
    }


def parse_counterparties(raw_json: str | None) -> list[dict[str, Any]]:
    """后端预查的对手 JSON 串 → 精简列表;空/非法 → []。"""
    try:
        parsed = json.loads(raw_json or "[]")
    except (ValueError, TypeError):
        return []
    return [_pick_fields(x) for x in parsed] if isinstance(parsed, list) else []


def parse_candidates(quote: str | None) -> list[dict[str, Any]]:
    """引用消息候选标的块确定性解析。

    用"先找所有候选起始(序号. 代码 -),name 取相邻起始之间的文本"的写法,
    对单行引用消息也健壮,不会把后续候选并入前一个 name。
    """
    if not quote:
        return []
    result: list[dict[str, Any]] = []
    for block in str(quote).split(ORDER_SEP):
        if CAND_BEGIN not in block:
            continue
        order_id_match = _ORDER_ID_RE.search(block)
        order_seq_match = _ORDER_SEQ_RE.search(block)
        segment = block.split(CAND_BEGIN, 1)[1].split(CAND_END, 1)[0]
        starts = list(_CAND_START_RE.finditer(segment))
        candidates: list[dict[str, Any]] = []
        for i, m in enumerate(starts):
            name_end = starts[i + 1].start() if i + 1 < len(starts) else len(segment)
            name = segment[m.end():name_end]
            name = re.split(r"[（(]", name)[0].strip()  # 去掉"（已默认）"等修饰括号
            candidates.append({"seq": int(m.group(1)), "code": m.group(2), "name": name})
        if candidates:
            result.append(
                {
                    "orderId": order_id_match.group(0) if order_id_match else None,
                    "orderSeq": int(order_seq_match.group(1)) if order_seq_match else None,
                    "candidates": candidates,
                }
            )
    return result


@safe_node
async def pre_route(state: AgentState) -> dict[str, Any]:
    """路由前置节点:解析对手列表与引用候选标的,异常由 @safe_node 兜底。

    入参约定:API 入口 inputs_to_state 把 Java 侧原始 JSON 串透传进
    option_counterparties_raw / swap_counterparties_raw(见 app/api/turn_state.py)。
    """
    option_raw = state.get("option_counterparties_raw")
    swap_raw = state.get("swap_counterparties_raw")
    quote = state.get("quote_content")

    option_list = parse_counterparties(option_raw)
    swap_list = parse_counterparties(swap_raw)
    candidate_list = parse_candidates(quote)

    return {
        "option_counterparties": option_list,
        "swap_counterparties": swap_list,
        "quote_ticker_candidates": candidate_list,
        "trace": [
            TraceEntry(
                node="pre_route",
                decision=(
                    f"cp_option={len(option_list)} cp_swap={len(swap_list)} "
                    f"cand_blocks={len(candidate_list)}"
                ),
            )
        ],
    }


__all__ = ["pre_route", "parse_counterparties", "parse_candidates"]
