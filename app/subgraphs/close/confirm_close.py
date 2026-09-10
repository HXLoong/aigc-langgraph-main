"""close.confirm_close 节点 · 确认平仓订单号提取。

输入：raw_text + quote_content（引用消息含订单列表）
输出：state['confirm'] = {"confirmOrderNoList": [...], "action": "close"}

LLM：standard 模型 + with_structured_output（ADR 0010 强制规则；
Dify 原 prompt 标 thinking，工程层覆盖为 standard 满足 structured output）。
prompt：app/prompts/option_close/confirm_close.md。
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_confirm
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts import load_prompt
from app.subgraphs.close.aggregate import build_close_order_req_vo
from app.subgraphs.close.backend import call_close_backend
from app.subgraphs.close.models import ConfirmCloseParams


def _build_user_message(state: AgentState) -> str:
    """组装与 Dify confirm_close.md user template 一致的格式。"""
    raw_content = state.get("raw_text", "") or ""
    quote_content = state.get("quote_content") or ""
    return (
        f"用户发送消息：{raw_content}\n"
        f"用户引用消息：{quote_content}"
    )


@safe_node
async def close_confirm_close(state: AgentState) -> dict[str, Any]:
    """close.confirm_close 节点。

    出参约定：
    - confirm: dict 含 confirmOrderNoList + action="close"（与 swap.confirm
      合并版同款 action 字段约定）
    - trace: 单条 TraceEntry，记录提取的订单号数量
    """
    prompt = load_prompt("option_close", "confirm_close")
    llm = get_qwen_thinking().with_structured_output(ConfirmCloseParams)

    user_message = _build_user_message(state)
    result: Any = await llm.ainvoke(
        [
            ("system", prompt.system),
            ("user", user_message),
        ]
    )

    # regex 兜底：LLM 抽不到时直接从 raw_text + quote_content 抠 CO-YYYYMMDD-XXX 单号
    # （结构化字符串抽取,与 swap.place_order 抠 H-YYYYMMDD-N 同款思路）
    confirm_ids = list(result.confirm_order_no_list)
    if not confirm_ids:
        import re as _re_co
        raw = (state.get("raw_text") or "") + "\n" + (state.get("quote_content") or "")
        confirm_ids = list(dict.fromkeys(_re_co.findall(r"CO-\d{8}-[A-Z0-9]+", raw)))

    # 真后端调用：confirmOrderNoList 进 closeOrderReqVO（不是 option 域的 orderList）
    req_vo = build_close_order_req_vo(confirm_order_no_list=confirm_ids)
    backend = await call_close_backend(
        state,
        intent="close_order_confirm",
        close_order_req_vo=req_vo,
    )

    return {
        "confirm": validated_confirm(action="close", confirmOrderNoList=confirm_ids),
        **backend,
        "trace": [
            TraceEntry(
                node="close_confirm_close",
                decision=f"orders={len(confirm_ids)}",
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["close_confirm_close"]
