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


#: A 股交易所（沪/深/京）
_A_SHARE_EXCHANGES = (".SH", ".SZ", ".BJ")
#: 港股交易所
_HK_EXCHANGES = (".HK",)
#: 期货交易所（仅作为兜底，避免误把期货当作 cash market 标的）
_FUTURES_EXCHANGES = (".CFE", ".DCE", ".SHFE", ".CZCE", ".INE", ".SHF", ".CZC")
#: 兼容旧引用（其他模块可能 import 此符号）
_CN_EXCHANGES = set(_A_SHARE_EXCHANGES + _HK_EXCHANGES + _FUTURES_EXCHANGES)


def _ends_with_any(wind: str, suffixes: tuple[str, ...]) -> bool:
    upper = (wind or "").upper()
    return any(upper.endswith(s) for s in suffixes)


def _pick_winner(
    keyword: str,
    results: list,
) -> object | None:
    """从 GOATS 返回列表中选出最优标的，返回 None 表示无可用结果。

    GOATS 按 windCode 字典序返回，但最优标的未必排第一（例如同主题的 SZ 联接基金代码
    小于 SH 主 ETF）。选优规则（分层）：

    1. A 股交易所（.SH/.SZ/.BJ）优先：若存在 A 股候选则只在 A 股内选优；
    2. 港股交易所（.HK）次之：若无 A 股候选则在港股内选优；
    3. 期货交易所（.CFE/.DCE/...）保守返回 None：避免在 typo / 关键词
       匹配失败时把期货代码当作 cash market 标的（会触发后端"不在标的池内"）。

    同层多候选选优：
       a. 单条 → 直接返回；
       b. A 股层混合 SH+其他 → 取最小 SH windCode；
       c. 全为同一交易所 → 调用 infer_code LLM 推断最匹配的 windCode；
       d. 兜底取第一个。
    """
    if not results:
        return None

    # 优先 A 股
    a_results = [r for r in results if _ends_with_any(r.windCode, _A_SHARE_EXCHANGES)]
    if a_results:
        return _pick_within_a_share(keyword, a_results)

    # 退而求其次：港股
    hk_results = [r for r in results if _ends_with_any(r.windCode, _HK_EXCHANGES)]
    if hk_results:
        if len(hk_results) == 1:
            return hk_results[0]
        # 同港股多个 → LLM 推断 / 兜底
        try:
            inferred = infer_code.invoke({"keyword": keyword})
            inferred = (inferred or "").strip().upper()
            if inferred:
                for r in hk_results:
                    if (r.windCode or "").upper() == inferred:
                        return r
        except Exception:  # noqa: BLE001
            pass
        return hk_results[0]

    # 仅命中期货 → 保守不选（避免误用期货代码触发后端"不在标的池内"）
    return None


def _pick_within_a_share(keyword: str, a_results: list) -> object | None:
    """A 股候选内部选优（原 _pick_winner 主逻辑剥离）。"""
    if len(a_results) == 1:
        return a_results[0]

    sh = [r for r in a_results if (r.windCode or "").upper().endswith(".SH")]
    if sh and len(sh) < len(a_results):
        return min(sh, key=lambda r: r.windCode)

    # 全为同一交易所（多只同主题 ETF）→ LLM 推断
    try:
        inferred = infer_code.invoke({"keyword": keyword})
        inferred = (inferred or "").strip().upper()
        if inferred:
            for r in a_results:
                if (r.windCode or "").upper() == inferred:
                    return r
    except Exception:  # noqa: BLE001
        pass

    return a_results[0]


#: 命名指数 → 可交易 ETF 代码（场外期权 backend 标的池只收 ETF，不收指数）。
#: 在 tokenize 之后把对应 ETF 代码**前置**到 keywords 队列首位，让 GOATS 先查 ETF
#: → resolved[0] = ETF → option/swap 子图的 order[0].stockCode 取 tickers[0].windCode
#: → 通过后端校验。
_NAMED_INDEX_TO_ETF: dict[str, str] = {
    "创业板指": "159915.SZ",       # 创业板 ETF
    "上证50": "510050.SH",          # 上证50 ETF
    "中证500": "510500.SH",         # 中证500 ETF
    "中证1000": "512100.SH",        # 中证1000 ETF
    "沪深300": "510300.SH",         # 沪深300 ETF
    "科创50": "588000.SH",          # 科创50 ETF
    "深证成指": "159901.SZ",        # 深证成指 ETF
}


async def _resolve_via_react_full(raw_text: str) -> TickerResolution:
    """tokenize 拆词 → 每个 keyword 查 securities-instrument/select → pick_best 选优。

    流程：
    1. tokenize(raw_text) → list[str] keywords
    2. 命名指数前置：raw_text 含已知指数名（创业板指/上证50/中证500/中证1000/沪深300/...） →
       把对应 ETF 代码插入 keywords 首位（绕过 GOATS 对指数关键词的"返回指数代码"行为）
    3. 对每个 keyword 调 client.search_securities_instrument()（async HTTP）
    4. 单命中 → 直接选入 resolved
    5. 多命中 → pick_best 启发式选优（精确匹配 > 前缀最短 > A 股优先）
    6. 0 命中 → 跳过该 keyword
    """
    keywords = tokenize.invoke({"raw_text": raw_text})

    # 命名指数 → ETF 代码前置（保留原 keywords 但去重）
    _extra_etfs: list[str] = []
    for _index_name, _etf in _NAMED_INDEX_TO_ETF.items():
        if _index_name in raw_text and _etf not in _extra_etfs:
            _extra_etfs.append(_etf)
    if _extra_etfs:
        keywords = _extra_etfs + [k for k in keywords if k not in _extra_etfs]

    if not keywords:
        return TickerResolution(resolved=[], hitl_pending=[])

    # 过滤噪音关键词：单字符、纯数字非股票代码格式（4-6位数字是股票代码，保留）
    # 同时过滤订单号前缀（OPT-/CO-/H-/OPTG-/Q-），这些是业务单号不是标的代码
    _ORDER_PREFIXES = ("OPT-", "CO-", "H-", "OPTG-", "Q-")
    keywords = [
        kw for kw in keywords
        if len(kw) > 1
        and not (kw.isdigit() and not (4 <= len(kw) <= 6))
        and not any(kw.upper().startswith(p) for p in _ORDER_PREFIXES)
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
