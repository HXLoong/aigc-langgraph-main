"""ticker resolver · 业务子图调用的标准接口。

设计（ADR 0008 + grill-with-docs 第 3 决策"双轨 ticker"）：

- 业务子图节点（swap.place_order / option.extract_inquiry / close.place_close）
  通过 `await resolve_ticker(raw_text)` 拿 list[TickerCandidate]，对底层实现无感
- **双轨**：env `TICKER_RESOLVER_MODE` 切换
  - `react`（默认）：tokenize → 真 GOATS via Java 后端 securities-instrument/select 编排
  - `whitelist`：50 条白名单（harness `--mock-ticker` / 紧急回滚 / 网络不通 fallback）
- ReAct 0 命中或异常 → 自动降级白名单（保证业务不挂）

接口契约：
- 输入 raw_text
- 命中关键词 → 构造 TickerCandidate（from_goats=True）
- 同一 windCode 出现多次只保留第一条
- 0 命中 → 返回空 list（业务子图 cascade 防御走 fallback，ADR 0008 b）
"""
from __future__ import annotations

import logging
import os

from app.graph.state import TickerCandidate
from app.subgraphs.ticker.tools import RANK_AUTO_PICK_GAP, _make_client, tokenize
from app.subgraphs.ticker.whitelist import TICKER_WHITELIST
from app.tools.ticker_client import KeywordItem, SecuritiesInstrumentReqVO

logger = logging.getLogger(__name__)

#: 模式选择（env 覆盖；测试可 monkeypatch 此模块属性）
DEFAULT_MODE = os.environ.get("TICKER_RESOLVER_MODE", "react").lower()


async def resolve_ticker(raw_text: str) -> list[TickerCandidate]:
    """标的识别（双轨入口）。

    Args:
        raw_text: 用户原话

    Returns:
        list[TickerCandidate]，按出现顺序，去重 windCode。0 命中返回 []。

    模式：
        - react: 调 tokenize + 真 GOATS 编排（默认）
        - whitelist: 旧白名单 50 条（env TICKER_RESOLVER_MODE=whitelist）

    React 模式异常或 0 命中 → 自动降级白名单（保证业务不挂）。
    """
    if not raw_text:
        return []

    if DEFAULT_MODE == "whitelist":
        return _resolve_via_whitelist(raw_text)

    try:
        candidates = await _resolve_via_react(raw_text)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "ticker react resolver 异常，降级白名单: %s (raw=%r)", exc, raw_text[:60]
        )
        return _resolve_via_whitelist(raw_text)

    if candidates:
        return candidates

    # ReAct 0 命中 → 白名单兜底（覆盖未在 GOATS 但在白名单的常用标的）
    fallback = _resolve_via_whitelist(raw_text)
    if fallback:
        logger.info("ticker react 0 命中 → 白名单兜底命中 %d 条", len(fallback))
    return fallback


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


async def _resolve_via_react(raw_text: str) -> list[TickerCandidate]:
    """tokenize 拆词 → 每个 keyword 查 securities-instrument/select → 分差判定。

    流程：
    1. tokenize(raw_text) → list[str] keywords
    2. 对每个 keyword 调 client.search_securities_instrument()（async HTTP）
    3. 单命中 → 直接选
    4. 多命中分差 ≥ RANK_AUTO_PICK_GAP → 选 top1
    5. 多命中分差 < RANK_AUTO_PICK_GAP → 暂跳过（HITL 留 M3 后期，ADR 0006）
    6. 0 命中 → 跳过该 keyword

    异常单 keyword 调用错误时跳过该 keyword，继续下一个（不让单点失败拖垮全集）。
    """
    keywords = tokenize.invoke({"raw_text": raw_text})
    if not keywords:
        return []

    client = _make_client()
    candidates: list[TickerCandidate] = []
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

        # 单命中 → 选
        if len(results) == 1:
            winner = results[0]
        else:
            # 多命中：mock_api 已按 relevanceScore 升序返回（小分数 = 强相关）
            top1, top2 = results[0], results[1]
            gap = (top2.relevanceScore or 0) - (top1.relevanceScore or 0)
            if gap < RANK_AUTO_PICK_GAP:
                # HITL 场景，暂跳过（M3 后期接入 LangGraph interrupt）
                logger.info(
                    "ticker keyword=%r 多命中分差 %d < %d，HITL 跳过",
                    kw, gap, RANK_AUTO_PICK_GAP,
                )
                continue
            winner = top1

        if winner.windCode in seen:
            continue

        candidates.append(
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

    return candidates


__all__ = ["resolve_ticker"]
