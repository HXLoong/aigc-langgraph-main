"""持仓查询：LLM 提取原文候选，代码绑定授权对手与过滤条件后查询后端。"""
from __future__ import annotations

from typing import Any

from app.extraction.candidates import candidate_model, evidence_sources
from app.graph.business_params import validated_close_params
from app.graph.retry import io_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts import blocks
from app.prompts.spec import PromptSpec, register
from app.subgraphs.close.aggregate import build_close_order_req_vo
from app.subgraphs.close.backend import call_close_backend
from app.subgraphs.close.models import HoldingQueryParams
from app.subgraphs.close.normalization import normalize_holding_candidates


def _build_user_message(state: AgentState) -> str:
    return f"用户输入：{state.get('raw_text', '') or ''}"


CANDIDATE_MODEL = candidate_model(HoldingQueryParams)
SPEC = register(PromptSpec(
    category="option_close",
    name="holding_query",
    output_model=CANDIDATE_MODEL,
    inputs=("raw_text", "option_counterparties"),
    user_builder=_build_user_message,
    injects={
        # 后端预查的期权对手列表，JSON 渲染进 system（keyCtptyIdList 模糊匹配规则依赖它）
        "{{counterparty_list}}": lambda s: blocks.json_list(s.get("option_counterparties")),
    },
))


@io_node
async def close_holding_query(state: AgentState) -> dict[str, Any]:
    """close.holding_query 节点。

    出参约定：
    - close_params: dict（HoldingQueryParams.model_dump()）
    - trace: 单条 TraceEntry，记录 closeable_only + 提取到的关键字段计数
    """
    messages, _prompt_name = SPEC.build_messages(state)
    llm = get_qwen_thinking().with_structured_output(CANDIDATE_MODEL)
    candidates = CANDIDATE_MODEL.model_validate(await llm.ainvoke(messages))
    result, records = normalize_holding_candidates(
        candidates, evidence_sources(state), state.get("option_counterparties") or [],
    )

    decision = (
        f"closeable_only={result.closeable_only},"
        f" tickers={len(result.underlying_ins_name_list) + len(result.underlying_ins_id_list)},"
        f" trades={len(result.internal_trade_id_list)}"
    )

    # close_order_query 是 read 类语义（持仓查询），过滤条件走 closeOrderReqVO.contractQuery
    # （对齐 Dify 期权平仓-参数聚合），不是 orderList（那是 option 域字段）。
    req_vo = build_close_order_req_vo(
        ins_family_list=list(result.ins_family_list),
        contract_type_list=list(result.contract_type_list),
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
        "field_records": records,
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
