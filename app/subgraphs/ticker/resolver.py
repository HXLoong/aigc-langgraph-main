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
import re
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


#: 完整 wind code 模式：纯数字代码 + 已知交易所后缀
import re as _re_wc

_EXPLICIT_WIND_CODE_RE = _re_wc.compile(r"^\d{4,6}\.(SH|SZ|BJ|HK|CFE|DCE|SHF|CZC|INE)$", _re_wc.IGNORECASE)


def _is_explicit_wind_code(keyword: str) -> bool:
    """判断 keyword 是否是完整 wind code 格式（用户输入了明确代码）。"""
    return bool(_EXPLICIT_WIND_CODE_RE.match((keyword or "").strip()))


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

    # 用户输入是完整 wind code（如 999999.SH / 99999.HK）→ 要求 GOATS 精确匹配
    # 否则不模糊回退到 GOATS 自动返回的近似结果，让上层走拒绝路径
    if _is_explicit_wind_code(keyword):
        kw_up = keyword.strip().upper()
        for r in results:
            if (r.windCode or "").upper() == kw_up:
                return r
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


#: 完整 windCode 模式（已带交易所后缀，无需 LLM 再推断）
_FULL_WIND_CODE_RE = re.compile(
    r"^\S+\.(SH|SZ|BJ|HK|HKEX|SHF|SHFE|DCE|CZC|CZCE|CFE|CFFEX|INE|"
    r"O|N|NYM|CME|COMEX|LME|CBOT|SGX|T|AX|DF|DY|P|OF|BO|SG)$",
    re.IGNORECASE,
)


def _should_consult_llm(kw: str, primary_count: int) -> bool:
    """判定是否值得调用 LLM 二次推断（**结构化判定，非业务字典**）。

    True 条件：
    - 含中文字符（infer_code 训练数据通常能覆盖中文名 → 标准 windCode 翻译）
    - 4-6 位裸数字代码 AND primary 非唯一命中（如 "000858" 同名 SH/SZ 两市，需 LLM 选）

    False 条件：
    - 已是完整 windCode（如 "600519.SH" 不必再问）
    - 数字代码且 primary 唯一命中（无需消歧）
    """
    if not kw or _FULL_WIND_CODE_RE.match(kw):
        return False
    has_chinese = bool(re.search(r"[一-鿿]", kw))
    if has_chinese:
        return True
    is_digit_code = kw.isdigit() and 4 <= len(kw) <= 6
    return is_digit_code and primary_count != 1


async def _search_goats(client, keyword: str) -> list:
    """单次 GOATS 查询，封装异常。"""
    try:
        req = SecuritiesInstrumentReqVO(
            keywordItems=[KeywordItem(keyword=keyword, isFull=False)]
        )
        return await client.search_securities_instrument(req)
    except Exception as exc:  # noqa: BLE001
        logger.debug("securities-instrument/select keyword=%r 失败: %s", keyword, exc)
        return []


#: A 股指数代码模式（000xxx.SH = SSE 指数；399xxx.SZ = SZSE 指数）。
#: 场外期权后端标的池**只接受可交易 ETF**，不收指数代码（指数不可买卖）。
_INDEX_CODE_PATTERN = re.compile(r"^(000|399)\d{3}\.(SH|SZ)$", re.IGNORECASE)


async def _try_etf_fallback(client, keyword: str, winner) -> object:
    """winner 是指数代码 + keyword 含中文 → 触发 ETF 后备搜索。

    流程（结构化规则，非业务字典）：
    1. 检查 winner.windCode 是否匹配指数代码 numeric 范围
    2. 去掉常见指数后缀（"指数"/"指"），拼上 "ETF" 重查 GOATS
    3. GOATS 命中 → 用 ETF 替换；未命中 → 保留原指数代码
    """
    if winner is None:
        return winner
    wc = (getattr(winner, "windCode", "") or "").upper()
    if not _INDEX_CODE_PATTERN.match(wc):
        return winner
    if not re.search(r"[一-鿿]", keyword):
        return winner

    # 关键词去掉"指数"/"指"，拼 "ETF"。如 创业板指 → 创业板ETF；上证50 → 上证50ETF
    base = keyword.replace("指数", "").rstrip("指").strip()
    if not base:
        return winner
    etf_query = f"{base}ETF"
    etf_results = await _search_goats(client, etf_query)
    if not etf_results:
        return winner
    return etf_results[0]


async def _resolve_one_keyword(client, keyword: str) -> object | None:
    """单 keyword 解析：GOATS 主查询 + LLM 推断 + GOATS 二次校验 + 指数→ETF 后备。

    流程：
    1. GOATS 主查询 → primary_winner
    2. 名称类 keyword（中文 / 裸数字代码）→ 调 infer_code LLM 推断 windCode
    3. LLM 推断的 windCode：
       - 已在 primary 结果里 → 直接用该候选
       - 不在 primary 结果里 → GOATS 二次校验存在性 → 用校验结果
       - 不存在 → 回退 primary_winner
    4. winner 落在指数代码范围（000xxx.SH/399xxx.SZ）且 keyword 含中文 →
       追加 "ETF" 后备搜索（场外期权后端不收指数代码）
    """
    primary = await _search_goats(client, keyword)
    primary_winner = _pick_winner(keyword, primary) if primary else None

    if not _should_consult_llm(keyword, len(primary)):
        return await _try_etf_fallback(client, keyword, primary_winner)

    try:
        llm_code_raw = infer_code.invoke({"keyword": keyword})
    except Exception as exc:  # noqa: BLE001
        logger.debug("infer_code 失败 keyword=%r: %s", keyword, exc)
        return await _try_etf_fallback(client, keyword, primary_winner)

    llm_code = (llm_code_raw or "").strip()
    if not llm_code or llm_code.upper() == keyword.upper():
        return await _try_etf_fallback(client, keyword, primary_winner)

    final_winner: object | None = primary_winner

    # LLM 答案已在 primary 结果里 → 直接用该候选
    for r in primary:
        if (r.windCode or "").upper() == llm_code.upper():
            final_winner = r
            return await _try_etf_fallback(client, keyword, final_winner)

    # LLM 答案不在 primary → 二次 GOATS 校验
    retry_results = await _search_goats(client, llm_code)
    for r in retry_results:
        if (r.windCode or "").upper() == llm_code.upper():
            final_winner = r
            return await _try_etf_fallback(client, keyword, final_winner)

    # LLM 答案 GOATS 也找不到 → 回退 primary
    return await _try_etf_fallback(client, keyword, primary_winner)


async def _resolve_via_react_full(raw_text: str) -> TickerResolution:
    """tokenize 拆词 → 每个 keyword 查 securities-instrument/select → pick_best 选优。

    流程：
    1. tokenize(raw_text) → list[str] keywords
    2. 对每个 keyword 调 _resolve_one_keyword（GOATS 主查询 + LLM 二次校验）
    3. 单命中 → 直接选入 resolved
    4. 0 命中 → 跳过该 keyword
    """
    keywords = tokenize.invoke({"raw_text": raw_text})
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

    # 收集本批 keyword 里"完整 wind code 但 resolver 拒绝"的数字前缀，
    # 后续相同前缀的裸数字 keyword 不再走模糊匹配（避免 999999.SH→None 但 999999→002001.SZ 这种回退）
    rejected_digit_prefixes: set[str] = set()

    for kw in keywords:
        # 裸数字 keyword + 同前缀已被完整 wind code 形式拒绝 → 跳过，不模糊匹配
        if kw.isdigit() and kw in rejected_digit_prefixes:
            continue

        winner = await _resolve_one_keyword(client, kw)

        # 完整 wind code 拒绝 → 记录数字前缀供后续裸数字 keyword 检查
        if winner is None and _is_explicit_wind_code(kw):
            digit_prefix = kw.split(".")[0]
            rejected_digit_prefixes.add(digit_prefix.lstrip("0") or digit_prefix)
            rejected_digit_prefixes.add(digit_prefix)

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
