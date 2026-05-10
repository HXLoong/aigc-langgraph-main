"""ticker resolver · 业务子图调用的标准接口。

设计：
- 业务子图节点（swap.place_order / option.extract_place_or_modify / close.place_close）
  通过 `await resolve_ticker(raw_text)` 拿 list[TickerCandidate]，不直接调 ReAct Agent
- 骨架阶段（M2 Day 5）：白名单关键词匹配实现，无 LLM 调用
- 后续 PR：默认走真 ReAct Agent + GOATS 库；harness `--mock-ticker` 开关切回白名单
  （grill-with-docs 第 3 决策"双轨 ticker"）

接口契约：
- 输入 raw_text，遍历 `TICKER_WHITELIST` 关键词
- 命中关键词 → 构造 TickerCandidate（from_goats=True，relevanceScore=100）
- 同一 windCode 出现多次（如"腾讯"和"腾讯控股"两个关键词指向 00700.HK）只保留一条
- 0 命中 → 返回空 list（业务子图 cascade 防御走 fallback，ADR 0008 b）
"""
from __future__ import annotations

from app.graph.state import TickerCandidate
from app.subgraphs.ticker.whitelist import TICKER_WHITELIST


async def resolve_ticker(raw_text: str) -> list[TickerCandidate]:
    """标的识别接口（骨架阶段：白名单实现）。

    Args:
        raw_text: 用户原话

    Returns:
        list[TickerCandidate]，按出现顺序，去重 windCode。0 命中返回 []。
    """
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


__all__ = ["resolve_ticker"]
