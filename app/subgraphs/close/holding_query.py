"""close.holding_query 节点 · 持仓查询参数提取。

输入：raw_text（用户原话）+ 交易对手列表（state["option_counterparties"]，由 pre_route
从 Java 侧预查 JSON 解析，字段 ctptyId/shortName/longName/sort）
输出：state['close_params'] = HoldingQueryParams.model_dump() → 调真后端 query 接口

交易对手列表注入：Dify 原 system 里的 `{{#1772773805306.optionListStr#}}` 对应 Dify code
节点 `json.dumps(option_list, ensure_ascii=False)`；本节点在送 LLM 前做同样的确定性渲染
（ADR 0022 D5：占位符只允许出现在代码确实注入了值的位置）。此前占位符原样发给 LLM，
keyCtptyIdList 的模糊匹配规则整段悬空，任何"对手XX"都会命中哨兵 99999999（评估 OC-01）。

LLM：thinking 模型 + with_structured_output。
prompt：app/prompts/option_close/holding_query.md。
"""
from __future__ import annotations

import json
from typing import Any

from app.graph.business_params import validated_close_params
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts import load_prompt
from app.subgraphs.close.aggregate import build_close_order_req_vo
from app.subgraphs.close.backend import call_close_backend
from app.subgraphs.close.models import HoldingQueryParams

_COUNTERPARTY_PLACEHOLDER = "{{#1772773805306.optionListStr#}}"


def _render_system(system: str, state: AgentState) -> str:
    """把交易对手列表占位符渲染为 JSON（与 Dify code 节点 optionListStr 同口径）。"""
    option_list = state.get("option_counterparties") or []
    return system.replace(
        _COUNTERPARTY_PLACEHOLDER, json.dumps(option_list, ensure_ascii=False)
    )


def _build_user_message(state: AgentState) -> str:
    """组装 user message（raw_content 一个变量；对手列表走 system 渲染）。"""
    raw_content = state.get("raw_text", "") or ""
    return f"用户输入：{raw_content}"


@safe_node
async def close_holding_query(state: AgentState) -> dict[str, Any]:
    """close.holding_query 节点。

    出参约定：
    - close_params: dict（HoldingQueryParams.model_dump()）
    - trace: 单条 TraceEntry，记录 closeable_only + 提取到的关键字段计数
    """
    prompt = load_prompt("option_close", "holding_query")
    llm = get_qwen_thinking().with_structured_output(HoldingQueryParams)

    user_message = _build_user_message(state)
    result: Any = await llm.ainvoke(
        [
            ("system", _render_system(prompt.system, state)),
            ("user", user_message),
        ]
    )

    decision = (
        f"closeable_only={result.closeable_only},"
        f" tickers={len(result.underlying_ins_name_list) + len(result.underlying_ins_id_list)},"
        f" trades={len(result.internal_trade_id_list)}"
    )

    # close_order_query 是 read 类语义（持仓查询），过滤条件走 closeOrderReqVO.contractQuery
    # （对齐 Dify 期权平仓-参数聚合），不是 orderList（那是 option 域字段）。
    req_vo = build_close_order_req_vo(
        ins_family_list=result.ins_family_list,
        contract_type_list=result.contract_type_list,
        closeable_only=result.closeable_only,
        internal_trade_id_list=result.internal_trade_id_list,
        key_ctpty_id_list=result.key_ctpty_id_list,
        underlying_ins_id_list=result.underlying_ins_id_list,
        underlying_ins_name_list=result.underlying_ins_name_list,
    )
    backend = await call_close_backend(
        state,
        intent="close_order_query",
        close_order_req_vo=req_vo,
    )

    return {
        "close_params": validated_close_params(**result.model_dump()),
        **backend,
        "trace": [
            TraceEntry(
                node="close_holding_query",
                decision=decision,
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["close_holding_query"]
