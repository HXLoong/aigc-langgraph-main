"""close.holding_query 节点 · 持仓查询参数提取。

输入：raw_text（用户原话）+ 交易对手列表（M2 后续 PR 接入 TickerClient.list_counterparty）
输出：state['close_params'] = HoldingQueryParams.model_dump()

骨架阶段范围：
- LLM 提取 7 个查询字段（写 state['close_params']）
- 不调真后端 query_close_orders（留给后续 PR）
- 交易对手列表用空 stub（不影响 keyCtptyIdList 提取的 LLM 推理；真接入时通过
  TickerClient.list_counterparty 拉取并替换）

LLM：standard 模型 + with_structured_output（ADR 0010）。
prompt：app/prompts/option_close/holding_query.md。
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_close_params
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts import load_prompt
from app.subgraphs.close.aggregate import build_close_order_req_vo
from app.subgraphs.close.backend import call_close_backend
from app.subgraphs.close.models import HoldingQueryParams


def _build_user_message(state: AgentState) -> str:
    """组装 user message。

    Dify 原 prompt 用 `{{#1755072621769.raw_content#}}` 占位符。骨架阶段
    我们直接把 raw_content 作为 user message——LLM 已被 system prompt 训练
    理解原始输入，不需要 Dify 占位符严格替换。
    """
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
            ("system", prompt.system),
            ("user", user_message),
        ]
    )

    decision = (
        f"closeable_only={result.closeable_only},"
        f" tickers={len(result.underlyingInsNameList) + len(result.underlyingInsIdList)},"
        f" trades={len(result.internalTradeIdList)}"
    )

    # close_order_query 是 read 类语义（持仓查询），过滤条件走 closeOrderReqVO.contractQuery
    # （对齐 Dify 期权平仓-参数聚合），不是 orderList（那是 option 域字段）。
    req_vo = build_close_order_req_vo(
        ins_family_list=result.insFamilyList,
        contract_type_list=result.contractTypeList,
        closeable_only=result.closeable_only,
        internal_trade_id_list=result.internalTradeIdList,
        key_ctpty_id_list=result.keyCtptyIdList,
        underlying_ins_id_list=result.underlyingInsIdList,
        underlying_ins_name_list=result.underlyingInsNameList,
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
