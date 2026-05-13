"""ticker resolver · 业务子图调用的标准接口。

设计（ADR 0008 + grill-with-docs 第 3 决策"双轨 ticker"）：

- 业务子图节点（swap.place_order / option.extract_inquiry / close.place_close）
  通过 `await resolve_ticker_full(raw_text)` 拿 TickerResolution，对底层实现无感
- tokenize → 真 GOATS via Java 后端 securities-instrument/select 编排
- ReAct 0 命中或异常 → resolved=[]; hitl_pending=[]

接口契约：
- 输入 raw_text
- 命中关键词 → pick_best 选优 → 构造 TickerCandidate（from_goats=True）进入 resolved
- 0 命中 → resolved=[]; hitl_pending=[]
- 旧接口 resolve_ticker() 保持向后兼容（返回 list[TickerCandidate]）
"""
from __future__ import annotations

import logging
from typing import NamedTuple

from app.graph.state import TickerCandidate
from app.subgraphs.ticker.tools import _make_client, infer_code, tokenize
from app.tools.ticker_client import KeywordItem, SecuritiesInstrumentReqVO

logger = logging.getLogger(__name__)


# ============================================================
# 返回类型
# ============================================================


class TickerResolution(NamedTuple):
    """ticker 解析结果。

    resolved:     已自动确认的候选（from_goats=True）
    hitl_pending: 多命中分差过小、需用户消歧的 keyword 列表
                  每项 {"keyword": str, "candidates": [{"windCode", "insShtDesc", "relevanceScore"}, ...]}
    """

    resolved: list[TickerCandidate]
    hitl_pending: list[dict]


# ============================================================
# 公开接口
# ============================================================


async def resolve_ticker_full(raw_text: str) -> TickerResolution:
    """标的识别（ReAct 入口，含 HITL 信号，Issue #20）。

    Returns:
        TickerResolution(resolved, hitl_pending)
    """
    if not raw_text:
        return TickerResolution(resolved=[], hitl_pending=[])

    try:
        return await _resolve_via_react_full(raw_text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ticker react resolver 异常: %s (raw=%r)", exc, raw_text[:60])
        return TickerResolution(resolved=[], hitl_pending=[])


async def resolve_ticker(raw_text: str) -> list[TickerCandidate]:
    """向后兼容接口（返回 list[TickerCandidate]）。

    业务节点应优先使用 resolve_ticker_full() 以获取 HITL 信号。
    """
    resolution = await resolve_ticker_full(raw_text)
    return resolution.resolved


# ============================================================
# 实现：ReAct 编排（tokenize → securities-instrument/select 真后端）
# ============================================================


_CN_EXCHANGES = {".SH", ".SZ", ".BJ", ".HK", ".CFE", ".DCE", ".SHFE", ".CZCE", ".INE"}


def _pick_winner(
    keyword: str,
    results: list,
) -> object | None:
    """从 GOATS 返回列表中选出最优标的，返回 None 表示无可用结果。

    GOATS 按 windCode 字典序返回，但最优标的未必排第一（例如同主题的 SZ 联接基金代码
    小于 SH 主 ETF）。选优规则：
    1. 过滤掉非 A 股市场（非 .SH/.SZ/.BJ）的结果，避免误入外股（如 3M0.DF）。
    2. 单条 A 股结果直接返回。
    3. 混合 SH+SZ：SH 交易所优先（主要指数 ETF 通常为 SH 上市），取最小 SH windCode。
    4. 全为同一交易所（多只同主题 ETF）：调用 infer_code LLM 推断最匹配的 windCode，
       在结果列表中查找；找不到则退化为 a_results[0]。
    """
    a_results = [r for r in results if any(r.windCode.upper().endswith(e) for e in _CN_EXCHANGES)]
    if not a_results:
        return None

    if len(a_results) == 1:
        return a_results[0]

    sh = [r for r in a_results if r.windCode.upper().endswith(".SH")]
    if sh and len(sh) < len(a_results):
        return min(sh, key=lambda r: r.windCode)

    # 全为同一交易所（多只同主题 ETF）→ LLM 推断
    try:
        inferred = infer_code.invoke({"keyword": keyword})
        inferred = (inferred or "").strip().upper()
        if inferred:
            for r in a_results:
                if r.windCode.upper() == inferred:
                    return r
    except Exception:  # noqa: BLE001
        pass

    return a_results[0]


async def _resolve_via_react_full(raw_text: str) -> TickerResolution:
    """tokenize 拆词 → 每个 keyword 查 securities-instrument/select → pick_best 选优。

    流程：
    1. tokenize(raw_text) → list[str] keywords
    2. 对每个 keyword 调 client.search_securities_instrument()（async HTTP）
    3. 单命中 → 直接选入 resolved
    4. 多命中 → pick_best 启发式选优（精确匹配 > 前缀最短 > A 股优先）
    5. 0 命中 → 跳过该 keyword
    """
    keywords = tokenize.invoke({"raw_text": raw_text})
    if not keywords:
        return TickerResolution(resolved=[], hitl_pending=[])

    # 过滤噪音关键词：单字符、纯数字非股票代码格式（4-6位数字是股票代码，保留）
    keywords = [
        kw for kw in keywords
        if len(kw) > 1
        and not (kw.isdigit() and not (4 <= len(kw) <= 6))
    ]
    if not keywords:
        return TickerResolution(resolved=[], hitl_pending=[])

    client = _make_client()
    resolved: list[TickerCandidate] = []
    seen: set[str] = set()

    for kw in keywords:
        try:
            req = SecuritiesInstrumentReqVO(
                keywordItems=[KeywordItem(keyword=kw, isFull=False)]
            )
            results = await client.search_securities_instrument(req)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "securities-instrument/select keyword=%r 失败: %s", kw, exc
            )
            continue

        if not results:
            continue

        winner = _pick_winner(kw, results)
        if winner is None:
            continue

        if winner.windCode in seen:
            continue

        resolved.append(
            TickerCandidate(
                windCode=winner.windCode,
                insShtDesc=winner.insShtDesc,
                insLngDesc=winner.insLngDesc,
                relevanceScore=winner.relevanceScore,
                transactionTypeLists=winner.transactionTypeLists,
                from_goats=True,
            )
        )
        seen.add(winner.windCode)

    return TickerResolution(resolved=resolved, hitl_pending=[])


__all__ = ["TickerResolution", "resolve_ticker", "resolve_ticker_full"]
