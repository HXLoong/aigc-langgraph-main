"""ticker resolver · 业务子图调用的标准接口。

设计（ADR 0008 + grill-with-docs 第 3 决策"双轨 ticker" + Dify DSL v2 迁移）：

- 业务子图节点（swap.place_order / option.extract_inquiry / close.place_close）
  通过 `await resolve_ticker_full(raw_text)` 拿 TickerResolution，对底层实现无感
- 默认解析行为与返回类型不变；互换可通过 keyword-only 参数启用订单上下文过滤。
- 内部管线是一张 LangGraph 子图（`app/subgraphs/ticker/graph.py`，ADR 0024 D3）：
    extract_candidates(tokenize + 过滤 + 格式化) -> 空短路
    -> 三路并行分支 infer_codes / split_keywords / judge_type -> merge_candidates
    -> Send fan-out：逐 orgStr resolve_org_item（GOATS search + rank LLM）并行
    -> assemble：按输入顺序汇总、去重、组装 TickerCandidate
  节点函数留在本模块（测试按 `resolver.<name>` monkeypatch 边界），graph.py 只负责拓扑
- `from_goats=True` 是 CLAUDE.md 硬约束（ADR 0008）：凡进入输出的标的必须经 GOATS
  校验存在性，这是本项目对 Dify 行为的有意增强（新 DSL 的"标的智能化推断和分词
  工具"本身不含 GOATS 校验步骤），不因 DSL 无此步而删除
- 0 命中 / 候选为空 → resolved=[]; hitl_pending=[]（当前无真实 HITL 中断实现，
  与迁移前行为一致，保留字段供未来接入 interrupt）
"""
from __future__ import annotations

import logging
import operator
import re
from typing import Annotated, Any, NamedTuple, TypedDict

from langgraph.types import Send

from app.graph.state import TickerCandidate
from app.subgraphs.ticker.context import mask_order_context
from app.subgraphs.ticker.tools import (
    _filter_noise_candidates,
    _make_client,
    format_candidate_list,
    infer_code_batch,
    judge_ticker_type,
    merge_and_validate,
    rank_candidates,
    split_ticker_keywords,
    tokenize,
)
from app.tools.ticker_client import (
    KeywordItem,
    SecuritiesInstrumentReqVO,
    SecuritiesInstrumentRespVO,
    TickerClient,
)

logger = logging.getLogger(__name__)

_EXPLICIT_CODE_RE = re.compile(
    r"(?<![A-Za-z0-9_.])([A-Za-z0-9][A-Za-z0-9_-]*\.[A-Za-z][A-Za-z0-9]*)(?![A-Za-z0-9_.])"
)


def _code_identity(code: str) -> str:
    """数字代码允许前导零格式差异，交易所后缀必须一致。"""
    root, suffix = code.strip().upper().rsplit(".", 1)
    return f"{root.lstrip('0') or '0'}.{suffix}" if root.isdigit() else f"{root}.{suffix}"


# ============================================================
# 返回类型
# ============================================================


class TickerResolution(NamedTuple):
    """ticker 解析结果。

    resolved:     已自动确认的候选（from_goats=True）
    hitl_pending: 多命中且无法自动确认、需用户消歧的 keyword 列表
                  每项 {"keyword": str, "candidates": [{"windCode", "insShtDesc", "relevanceScore"}, ...]}
                  （当前管线不产生该字段，rank 步骤总是给出确定性排序结果；保留字段
                  供未来真正接入 LangGraph interrupt 的 HITL 场景）
    """

    resolved: list[TickerCandidate]
    hitl_pending: list[dict[str, Any]]


# ============================================================
# 公开接口
# ============================================================


async def resolve_ticker_full(
    raw_text: str,
    *,
    filter_order_context: bool = False,
    counterparty_shortnames: list[str] | None = None,
) -> TickerResolution:
    """标的识别（新管线入口，含 HITL 信号占位，Issue #20）。

    filter_order_context 默认关闭；互换显式启用，仅清洗标的识别文本副本。
    counterparty_shortnames 是本轮候选短名，供完整片段匹配。

    Returns:
        TickerResolution(resolved, hitl_pending)
    """
    if not raw_text:
        return TickerResolution(resolved=[], hitl_pending=[])

    try:
        if filter_order_context:
            raw_text = mask_order_context(raw_text, counterparty_shortnames or [])
        return await _resolve_pipeline(raw_text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ticker resolver 异常: %s (raw=%r)", exc, raw_text[:60])
        return TickerResolution(resolved=[], hitl_pending=[])


async def resolve_ticker(raw_text: str) -> list[TickerCandidate]:
    """向后兼容接口（返回 list[TickerCandidate]）。

    业务节点应优先使用 resolve_ticker_full() 以获取 HITL 信号。
    """
    resolution = await resolve_ticker_full(raw_text)
    return resolution.resolved


# ============================================================
# 实现：LangGraph 子图（节点函数 + 私有 State；拓扑见 graph.py）
# ============================================================


class OrgWinner(TypedDict):
    """单个 orgStr 的解析结果；index 保证 Send 并行后按输入顺序汇总。"""

    index: int
    org_str: str
    winner: Any  # SecuritiesInstrumentRespVO | None


class TickerState(TypedDict, total=False):
    """ticker 子图私有 State（不与 AgentState 共享）。"""

    raw_text: str
    candidates: list[str]
    infer_codes: dict[str, Any]
    split_codes: dict[str, Any]
    ins_family: dict[str, Any]
    # merge_candidates 产物：待并行解析的 org 条目 + 已确定的 winner
    pending_items: list[dict[str, Any]]
    winners: Annotated[list[OrgWinner], operator.add]
    resolved: list[TickerCandidate]


class OrgItemInput(TypedDict):
    """Send 给 resolve_org_item 的载荷。"""

    index: int
    org_str: str
    keywords: list[dict[str, Any]]
    predicted_family: str


async def _search_goats(
    client: TickerClient, keyword_items: list[dict[str, Any]]
) -> list[SecuritiesInstrumentRespVO]:
    """单次 GOATS 批量查询（一个 orgStr 下全部 keyword 合并成一次请求），封装异常。"""
    try:
        req = SecuritiesInstrumentReqVO(
            keywordItems=[
                KeywordItem(keyword=k["keyword"], isFull=k["isFull"])
                for k in keyword_items
            ]
        )
        return await client.search_securities_instrument(req)
    except Exception as exc:  # noqa: BLE001
        logger.debug("securities-instrument/select 失败: %s", exc)
        return []


async def _resolve_one_org_item(
    client: TickerClient,
    org_str: str,
    keywords: list[dict[str, Any]],
    predicted_family: str,
) -> SecuritiesInstrumentRespVO | None:
    """单个 orgStr：GOATS 批量查询 + rank LLM 排序过滤 → winner（GOATS 候选对象）或 None。

    - 0 命中 → None
    - 1 命中 → 直接作为 winner（无需 LLM 排序）
    - ≥2 命中 → 调 rank_candidates 让 LLM 过滤 + 排序，取过滤后第 0 位
    """
    if not keywords:
        return None

    results = await _search_goats(client, keywords)
    if not results:
        return None
    if len(results) == 1:
        return results[0]

    ranked_codes = await rank_candidates(
        keyword=org_str,
        results=results,
        predicted_ins_family=predicted_family,
    )
    if not ranked_codes:
        return None

    by_code = {(r.wind_code or "").upper(): r for r in results}
    for code in ranked_codes:
        hit = by_code.get((code or "").upper())
        if hit is not None:
            return hit
    return None


# ---------- 节点 ----------


async def extract_candidates(state: TickerState) -> dict[str, Any]:
    """tokenize 提取候选 → 过滤噪音（单字符 / 非 4-6 位纯数字 / 订单号前缀）→ 格式化去重。"""
    raw_candidates = tokenize.invoke({"raw_text": state["raw_text"]})
    filtered = _filter_noise_candidates(raw_candidates)
    return {"candidates": format_candidate_list(filtered)}


def route_after_extract(state: TickerState) -> list[str] | str:
    """无候选 → 直接汇总（空结果）；否则三路 LLM 并行。"""
    if not state.get("candidates"):
        return "assemble"
    return ["infer_codes", "split_keywords", "judge_type"]


async def infer_codes(state: TickerState) -> dict[str, Any]:
    return {"infer_codes": await infer_code_batch(state["candidates"])}


async def split_keywords(state: TickerState) -> dict[str, Any]:
    return {"split_codes": await split_ticker_keywords(state["candidates"])}


async def judge_type(state: TickerState) -> dict[str, Any]:
    return {"ins_family": await judge_ticker_type(state["candidates"])}


async def merge_candidates(state: TickerState) -> dict[str, Any]:
    """merge_and_validate + 完整代码权威校验；产出待并行解析条目与已确定 winner。

    - 输入中的完整代码（600519.SH 形态）先独立走 GOATS 精确校验，不与 LLM 派生的
      裸数字 / 名称混在同一请求；即使 LLM 漏掉也照常校验，顺序不由 LLM 决定
    - 裸数字候选只能补充已验证成功的来源词，不再发起模糊查询
    """
    raw_text = state["raw_text"]
    ins_family = state.get("ins_family") or {}
    merged = merge_and_validate(
        state.get("infer_codes") or {}, state.get("split_codes") or {}, ins_family
    )
    client = _make_client()

    explicit = list(dict.fromkeys(_EXPLICIT_CODE_RE.findall(raw_text)))
    exact_results: dict[str, SecuritiesInstrumentRespVO | None] = {}
    guarded_roots: dict[str, list[SecuritiesInstrumentRespVO]] = {}
    for code in explicit:
        identity = _code_identity(code)
        results = await _search_goats(client, [
            {"keyword": keyword, "isFull": True}
            for keyword in dict.fromkeys([code.upper(), identity])
        ])
        winner = next((item for item in results if _code_identity(item.wind_code) == identity), None)
        exact_results[identity] = winner
        root = code.split(".")[0]
        if root.isdigit():
            matches = guarded_roots.setdefault(root.lstrip("0") or "0", [])
            if winner is not None:
                matches.append(winner)
    explicit_keys = {code.upper() for code in explicit}
    merged = [{"orgStr": code, "keywords": []} for code in explicit] + [
        item for item in merged if item["orgStr"].upper() not in explicit_keys
    ]

    known: list[OrgWinner] = []
    pending: list[dict[str, Any]] = []
    for index, item in enumerate(merged):
        org_str = item["orgStr"]
        keywords = item["keywords"]
        if _EXPLICIT_CODE_RE.fullmatch(org_str) and _code_identity(org_str) in exact_results:
            known.append({"index": index, "org_str": org_str,
                          "winner": exact_results[_code_identity(org_str)]})
        elif org_str.isdigit() and (org_str.lstrip("0") or "0") in guarded_roots:
            matches = guarded_roots[org_str.lstrip("0") or "0"]
            known.append({"index": index, "org_str": org_str,
                          "winner": matches[0] if len(matches) == 1 else None})
        else:
            keywords = [k for k in keywords if not (
                k["keyword"].isdigit() and (k["keyword"].lstrip("0") or "0") in guarded_roots
            )]
            pending.append({
                "index": index, "org_str": org_str, "keywords": keywords,
                "predicted_family": str(ins_family.get(org_str) or ""),
            })
    return {"pending_items": pending, "winners": known}


def fan_out_org_items(state: TickerState) -> list[Send] | str:
    """按 orgStr Send 并行解析；无待解析条目 → 直接汇总。"""
    pending = state.get("pending_items") or []
    if not pending:
        return "assemble"
    return [Send("resolve_org_item", item) for item in pending]


async def resolve_org_item(item: OrgItemInput) -> dict[str, Any]:
    """Send 目标：单个 orgStr 的 GOATS 查询 + rank。"""
    winner = await _resolve_one_org_item(
        _make_client(), item["org_str"], item["keywords"], item["predicted_family"]
    )
    return {"winners": [{"index": item["index"], "org_str": item["org_str"], "winner": winner}]}


async def assemble(state: TickerState) -> dict[str, Any]:
    """按输入顺序汇总 winner，按 windCode 去重，组装 TickerCandidate（from_goats=True 硬约束）。"""
    input_candidates = set(state.get("candidates") or [])
    resolved: list[TickerCandidate] = []
    by_code: dict[str, TickerCandidate] = {}
    for entry in sorted(state.get("winners") or [], key=lambda w: w["index"]):
        winner = entry["winner"]
        if winner is None:
            continue
        org_str = entry["org_str"]
        code_key = winner.wind_code.strip().upper()
        source_keywords = [org_str] if org_str in input_candidates else []
        if code_key in by_code:
            existing = by_code[code_key]
            for keyword in source_keywords:
                if keyword not in existing.source_keywords:
                    existing.source_keywords.append(keyword)
            continue
        resolved.append(
            TickerCandidate(
                windCode=winner.wind_code,
                insShtDesc=winner.ins_sht_desc,
                insLngDesc=winner.ins_lng_desc,
                relevanceScore=winner.relevance_score,
                transactionTypeLists=winner.transaction_type_lists,
                sourceKeywords=source_keywords,
                from_goats=True,
            )
        )
        by_code[code_key] = resolved[-1]
    return {"resolved": resolved}


async def _resolve_pipeline(raw_text: str) -> TickerResolution:
    """跑 ticker 子图（拓扑见 graph.py）。"""
    from app.subgraphs.ticker.graph import get_ticker_graph

    final = await get_ticker_graph().ainvoke({"raw_text": raw_text})
    return TickerResolution(resolved=list(final.get("resolved") or []), hitl_pending=[])


__all__ = ["TickerResolution", "TickerState", "resolve_ticker", "resolve_ticker_full"]
