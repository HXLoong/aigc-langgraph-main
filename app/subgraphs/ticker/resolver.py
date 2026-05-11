"""ticker resolver · 业务子图调用的标准接口。

设计（ADR 0008 + grill-with-docs 第 3 决策"双轨 ticker"）：

- 业务子图节点（swap.place_order / option.extract_inquiry / close.place_close）
  通过 `await resolve_ticker_full(raw_text)` 拿 TickerResolution，对底层实现无感
- **双轨**：env `TICKER_RESOLVER_MODE` 切换
  - `react`（默认）：tokenize → 真 GOATS via Java 后端 securities-instrument/select 编排
  - `whitelist`：50 条白名单（harness `--mock-ticker` / 紧急回滚 / 网络不通 fallback）
- ReAct 0 命中或异常 → 自动降级白名单（保证业务不挂）

接口契约：
- 输入 raw_text
- 命中关键词 → 构造 TickerCandidate（from_goats=True）进入 resolved
- 多命中分差 < GAP → 进 hitl_pending（待用户消歧），不进 resolved
- 0 命中 → resolved=[]; hitl_pending=[]
- 旧接口 resolve_ticker() 保持向后兼容（返回 list[TickerCandidate]）
"""
from __future__ import annotations

import logging
import os
from typing import Any, NamedTuple

from app.graph.state import TickerCandidate
from app.subgraphs.ticker.tools import RANK_AUTO_PICK_GAP, _make_client, tokenize
from app.subgraphs.ticker.whitelist import TICKER_WHITELIST
from app.tools.ticker_client import KeywordItem, SecuritiesInstrumentReqVO

logger = logging.getLogger(__name__)

#: 模式选择（env 覆盖；测试可 monkeypatch 此模块属性）
DEFAULT_MODE = os.environ.get("TICKER_RESOLVER_MODE", "react").lower()


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
    hitl_pending: list[dict[str, Any]]


# ============================================================
# 公开接口
# ============================================================


async def resolve_ticker_full(raw_text: str) -> TickerResolution:
    """标的识别（双轨入口，含 HITL 信号，Issue #20）。

    Returns:
        TickerResolution(resolved, hitl_pending)
    """
    if not raw_text:
        return TickerResolution(resolved=[], hitl_pending=[])

    if DEFAULT_MODE == "whitelist":
        return TickerResolution(
            resolved=_resolve_via_whitelist(raw_text),
            hitl_pending=[],
        )

    try:
        resolution = await _resolve_via_react_full(raw_text)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "ticker react resolver 异常，降级白名单: %s (raw=%r)", exc, raw_text[:60]
        )
        return TickerResolution(
            resolved=_resolve_via_whitelist(raw_text),
            hitl_pending=[],
        )

    if resolution.resolved:
        return resolution

    # 有 HITL pending → 保留 pending 信号，不用白名单覆盖消歧候选
    if resolution.hitl_pending:
        return resolution

    # ReAct 0 命中且无 HITL → 白名单兜底（覆盖未在 GOATS 但在白名单的常用标的）
    fallback = _resolve_via_whitelist(raw_text)
    if fallback:
        logger.info("ticker react 0 命中 → 白名单兜底命中 %d 条", len(fallback))
    return TickerResolution(resolved=fallback, hitl_pending=[])


async def resolve_ticker(raw_text: str) -> list[TickerCandidate]:
    """向后兼容接口（返回 list[TickerCandidate]）。

    业务节点应优先使用 resolve_ticker_full() 以获取 HITL 信号。
    """
    resolution = await resolve_ticker_full(raw_text)
    return resolution.resolved


# ============================================================
# 实现 1：白名单（旧版保留 · harness mock / 紧急回滚 / 兜底）
# ============================================================


def _resolve_via_whitelist(raw_text: str) -> list[TickerCandidate]:
    """50 条白名单关键词匹配。无 LLM、无 HTTP。"""
    if not raw_text:
        return []
    seen: set[str] = set()
    candidates: list[TickerCandidate] = []
    for keyword, (wind_code, sht_desc) in TICKER_WHITELIST.items():
        if keyword in raw_text and wind_code not in seen:
            candidates.append(
                TickerCandidate(
                    windCode=wind_code,
                    insShtDesc=sht_desc,
                    relevanceScore=100,
                    from_goats=True,
                )
            )
            seen.add(wind_code)
    return candidates


# ============================================================
# 实现 2：ReAct 编排（tokenize → securities-instrument/select 真后端）
# ============================================================


async def _resolve_via_react_full(raw_text: str) -> TickerResolution:
    """tokenize 拆词 → 每个 keyword 查 securities-instrument/select → 分差判定。

    流程：
    1. tokenize(raw_text) → list[str] keywords
    2. 对每个 keyword 调 client.search_securities_instrument()（async HTTP）
    3. 单命中 → 直接选入 resolved
    4. 多命中分差 ≥ RANK_AUTO_PICK_GAP → 选 top1 入 resolved
    5. 多命中分差 < RANK_AUTO_PICK_GAP → 收集候选入 hitl_pending（Issue #20）
    6. 0 命中 → 跳过该 keyword
    """
    keywords = tokenize.invoke({"raw_text": raw_text})
    if not keywords:
        return TickerResolution(resolved=[], hitl_pending=[])

    client = _make_client()
    resolved: list[TickerCandidate] = []
    hitl_pending: list[dict[str, Any]] = []
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

        if len(results) == 1:
            winner = results[0]
        else:
            # 多命中：按 relevanceScore 升序（小分数 = 强相关）
            top1, top2 = results[0], results[1]
            gap = (top2.relevanceScore or 0) - (top1.relevanceScore or 0)
            if gap < RANK_AUTO_PICK_GAP:
                # 分差不足 → 收集到 HITL 候选（不静默跳过，Issue #20）
                hitl_pending.append({
                    "keyword": kw,
                    "candidates": [
                        {
                            "windCode": r.windCode,
                            "insShtDesc": r.insShtDesc,
                            "relevanceScore": r.relevanceScore,
                        }
                        for r in results
                    ],
                })
                logger.info(
                    "ticker keyword=%r 多命中分差 %d < %d，进入 HITL pending",
                    kw, gap, RANK_AUTO_PICK_GAP,
                )
                continue
            winner = top1

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

    return TickerResolution(resolved=resolved, hitl_pending=hitl_pending)


__all__ = ["TickerResolution", "resolve_ticker", "resolve_ticker_full"]
