"""标的识别子图：固定拓扑 StateGraph。

替换掉 Dify 里的 24 + 7 = 31 个节点，收敛为一个固定图：tokenize → search → (optional) rank。

LLM 调用次数：1-3 次（vs ReAct Agent 的 5-7 次），大幅降低延迟。

执行约束：
1. 最终输出的每一个 ticker 必须经 search_securities_instrument 验证（from_goats=True）
2. search_securities_instrument 一次性传入所有关键词（批量，不分多次调）
3. 候选 > 6 → 必须调 rank_candidates（LLM 排序过滤）
4. 所有标的必须 from_goats=True

输入：AgentState（从 wechat_input.raw_content 读取用户消息）
输出：AgentState（写入 resolved_tickers / ticker_candidates）
"""
from __future__ import annotations

import logging
import re as _re
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.nodes.common import safe_node
from app.state import AgentState, TickerCandidate
from app.subgraphs.ticker_models import TokenizeOutput
from app.subgraphs.ticker_tools import search_securities_instrument

logger = logging.getLogger(__name__)


def _dict_to_ticker_candidate(d: dict) -> TickerCandidate:
    """将 search_securities_instrument 返回的 dict 转为 TickerCandidate。"""
    return TickerCandidate(
        keyword=d.get("keyword", ""),
        wind_code=d.get("windCode") or d.get("wind_code"),
        ins_sht_desc=d.get("insShtDesc") or d.get("ins_sht_desc"),
        ins_lng_desc=d.get("insLngDesc") or d.get("ins_lng_desc"),
        ins_family=d.get("insFamily") or d.get("ins_family"),
        currency=d.get("currency"),
        exchange=d.get("exchange"),
        is_complete=bool(d.get("windCode") or d.get("wind_code")),
        from_goats=d.get("from_goats", False),
    )


# ==================================================================
# 路由函数（纯函数，不做 IO）
# ==================================================================


def _route_cache_check(state: AgentState) -> str:
    """如果已解析过标的则跳过整个子图（同会话缓存）。"""
    existing = state.get("resolved_tickers", [])
    return END if existing else "tokenize_keywords"


def _route_after_tokenize(state: AgentState) -> str:
    """分词质量检查：质量不足 → 重新提取，否则 → 搜索。"""
    if state.get("_needs_refinement", False):
        return "retokenize"
    return "search_candidates"


def _route_after_search(state: AgentState) -> str:
    """候选 > 6 需要 LLM 排序，否则直接确认。"""
    candidates = state.get("ticker_candidates", [])
    if len(candidates) > 6:
        return "rank_candidates"
    return "finalize_tickers"


# ==================================================================
# 节点函数（@safe_node 装饰，返回 partial state update）
# ==================================================================


@safe_node
async def tokenize_keywords(state: AgentState) -> dict[str, Any]:
    """LLM 分词：从用户输入中提取标的关键词并自检质量。

    使用 load_prompt("ticker", "tokenize") 的 system prompt，
    LLM 通过 with_structured_output(TokenizeOutput) 返回结构化结果。
    """
    from app.llm.clients import get_qwen_standard
    from app.prompts import load_prompt

    prompt = load_prompt("ticker", "tokenize_v2")
    wx = state["wechat_input"]
    raw = wx.get("raw_content", "")

    llm = get_qwen_standard().with_structured_output(TokenizeOutput)
    result: TokenizeOutput = await llm.ainvoke([
        ("system", prompt.system),
        ("user", raw),
    ])

    logger.info(
        "tokenize_keywords(v2): extracted=%d needs_refinement=%s",
        len(result.keywords), result.needs_refinement,
    )
    return {
        "raw_tickers": result.keywords,
        "_needs_refinement": result.needs_refinement,
        "trace": [{
            "node": "tokenize_keywords",
            "decision": f"extracted {len(result.keywords)} keywords",
            "output_preview": ", ".join(result.keywords[:10]),
        }],
    }


@safe_node
async def retokenize(state: AgentState) -> dict[str, Any]:
    """重新分词：在 system prompt 前追加谨慎重试指令，再提取一次。"""
    from app.llm.clients import get_qwen_standard
    from app.prompts import load_prompt

    prompt = load_prompt("ticker", "tokenize_v2")
    wx = state["wechat_input"]
    raw = wx.get("raw_content", "")

    retry_instruction = (
        "## IMPORTANT: RETRY WITH MORE CARE\n"
        "Your previous extraction was marked as needing refinement. "
        "Please re-read the input more carefully and extract keywords more precisely.\n"
        "Pay extra attention to:\n"
        "- Code/name boundaries\n"
        "- Futures contract month codes (single letter + 2-digit year)\n"
        "- ETF/index name protection rules\n\n"
    )
    full_system = retry_instruction + prompt.system

    llm = get_qwen_standard().with_structured_output(TokenizeOutput)
    result: TokenizeOutput = await llm.ainvoke([
        ("system", full_system),
        ("user", raw),
    ])

    logger.info("retokenize: extracted=%d", len(result.keywords))
    return {
        "raw_tickers": result.keywords,
        "_needs_refinement": False,  # 不回退，只重试一次
        "trace": [{
            "node": "retokenize",
            "decision": f"re-extracted {len(result.keywords)} keywords",
            "output_preview": ", ".join(result.keywords[:10]),
        }],
    }


@safe_node
async def search_candidates(state: AgentState) -> dict[str, Any]:
    """直接调用 search_securities_instrument API 批量搜索，不经过 LLM。

    将 API 返回的 dict 列表转为 TickerCandidate 列表，
    检查 _error 标记处理 API 失败情况。
    """
    keywords = state.get("raw_tickers", [])

    if not keywords:
        logger.warning("search_candidates: 无关键词，跳过搜索")
        return {
            "resolved_tickers": [],
            "ticker_candidates": [],
            "trace": [{"node": "search_candidates", "decision": "no_keywords"}],
        }

    keyword_items = [{"isFull": False, "keyword": kw} for kw in keywords]
    result = await search_securities_instrument.ainvoke({"keyword_items": keyword_items})

    # 检查 API 错误（_error 标记来自 search_securities_instrument 的异常处理）
    if result and len(result) == 1 and result[0].get("_error"):
        error_msg = result[0]["_error"]
        logger.error("search_securities_instrument API 错误: %s", error_msg)
        return {
            "resolved_tickers": [],
            "ticker_candidates": [],
            "trace": [{"node": "search_candidates", "status": "error", "error": error_msg}],
        }

    candidates = [_dict_to_ticker_candidate(d) for d in result]

    logger.info(
        "search_candidates: found %d candidates from %d keywords",
        len(candidates), len(keywords),
    )
    return {
        "ticker_candidates": candidates,
        "trace": [{
            "node": "search_candidates",
            "decision": f"found {len(candidates)} candidates",
            "output_preview": ", ".join(
                c.wind_code or c.keyword for c in candidates[:5]
            ),
        }],
    }


@safe_node
async def rank_candidates(state: AgentState) -> dict[str, Any]:
    """LLM 排序过滤：候选 > 6 时用 rank 提示词过滤到 top-5。

    rank.md prompt 输出 <analysis>...</analysis><result>["CODE1", ...]</result>，
    不兼容 with_structured_output，使用自由文本 + 正则解析。
    """
    from app.llm.clients import get_qwen_standard
    from app.prompts import load_prompt

    candidates = state.get("ticker_candidates", [])
    if len(candidates) <= 6:
        return {
            "resolved_tickers": candidates,
            "trace": [{"node": "rank_candidates", "decision": "skip, <=6 candidates"}],
        }

    prompt = load_prompt("ticker", "rank")
    keyword = ", ".join(state.get("raw_tickers", []))

    candidate_dicts = [
        {
            "windCode": c.wind_code,
            "insShtDesc": c.ins_sht_desc,
            "insLngDesc": c.ins_lng_desc,
            "insFamily": c.ins_family,
            "currency": c.currency,
            "exchange": c.exchange,
        }
        for c in candidates
    ]

    user_message = f"关键字：{keyword}\n\n标的列表：{candidate_dicts}"

    try:
        llm = get_qwen_standard()
        resp = await llm.ainvoke([
            ("system", prompt.system),
            ("user", user_message),
        ])
        import json as _json

        content = resp.content if isinstance(resp.content, str) else str(resp.content)

        # 解析 <result> 标签中的 windCode 数组
        result_match = _re.search(
            r"<result>\s*(\[.*?\])\s*</result>", content, _re.DOTALL
        )
        if result_match:
            ranked_codes = _json.loads(result_match.group(1))
        else:
            # 兜底：尝试直接解析 JSON
            ranked_codes = _json.loads(content.strip())

        # 按排序后的 windCode 重建 TickerCandidate 列表
        code_to_candidate = {
            (c.wind_code or "").upper(): c for c in candidates
        }
        resolved: list[TickerCandidate] = []
        seen: set[str] = set()
        for code in ranked_codes:
            key = code.upper()
            if key in code_to_candidate and key not in seen:
                seen.add(key)
                resolved.append(code_to_candidate[key])

        logger.info(
            "rank_candidates: ranked %d -> %d resolved",
            len(candidates), len(resolved),
        )
        return {
            "resolved_tickers": resolved,
            "trace": [{
                "node": "rank_candidates",
                "decision": f"ranked {len(candidates)} -> {len(resolved)}",
                "output_preview": ", ".join(c.wind_code or "" for c in resolved[:5]),
            }],
        }
    except Exception as e:
        logger.warning("rank_candidates LLM 调用失败: %s，使用前 6 个候选", e)
        return {
            "resolved_tickers": candidates[:6],
            "trace": [{
                "node": "rank_candidates",
                "status": "error",
                "error": str(e),
                "decision": "fallback to top-6",
            }],
        }


@safe_node
async def finalize_tickers(state: AgentState) -> dict[str, Any]:
    """将候选直接确认为结果（候选 ≤ 6 时无需排序）。"""
    candidates = state.get("ticker_candidates", [])
    logger.info("finalize_tickers: %d candidates confirmed", len(candidates))
    return {
        "resolved_tickers": candidates,
        "trace": [{
            "node": "finalize_tickers",
            "decision": f"confirmed {len(candidates)} tickers",
            "output_preview": ", ".join(
                c.wind_code or c.keyword for c in candidates[:5]
            ),
        }],
    }


# ==================================================================
# 图构建
# ==================================================================


def build_ticker_graph():
    """构建标的识别子图（固定拓扑 StateGraph，替代 ReAct Agent）。

    拓扑：
        START ──→ [cache check] ──→ END（缓存命中）
                      │
                      ▼
                tokenize_keywords (LLM #1)
                      │
               [quality check]
              ┌───────┴───────┐
              ▼               ▼
        retokenize       search_candidates
        (LLM #2)         (直接 API，非 LLM)
              │               │
              └───────┬───────┘
                      ▼
               [candidate count]
              ┌───────┴───────┐
              ▼               ▼
        rank_candidates  finalize_tickers
        (LLM, >6)        (≤6, passthrough)
              │               │
              └───────┬───────┘
                      ▼
                     END

    LLM 调用次数：1-3 次（vs ReAct Agent 的 5-7 次）。
    """
    from app.prompts import load_prompt

    # 预热提示词缓存
    try:
        load_prompt("ticker", "tokenize_v2")
        load_prompt("ticker", "rank")
    except FileNotFoundError:
        logger.warning("标的识别提示词文件缺失")

    g = StateGraph(AgentState)

    g.add_node("tokenize_keywords", tokenize_keywords)
    g.add_node("retokenize", retokenize)
    g.add_node("search_candidates", search_candidates)
    g.add_node("rank_candidates", rank_candidates)
    g.add_node("finalize_tickers", finalize_tickers)

    g.add_conditional_edges(START, _route_cache_check, {
        "tokenize_keywords": "tokenize_keywords",
        END: END,
    })

    g.add_conditional_edges("tokenize_keywords", _route_after_tokenize, {
        "retokenize": "retokenize",
        "search_candidates": "search_candidates",
    })

    g.add_edge("retokenize", "search_candidates")

    g.add_conditional_edges("search_candidates", _route_after_search, {
        "rank_candidates": "rank_candidates",
        "finalize_tickers": "finalize_tickers",
    })

    g.add_edge("rank_candidates", END)
    g.add_edge("finalize_tickers", END)

    logger.info("标的识别 StateGraph 已构建（5 节点，固定拓扑）")
    return g
