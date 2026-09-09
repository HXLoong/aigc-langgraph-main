"""ticker resolver · 业务子图调用的标准接口。

设计（ADR 0008 + grill-with-docs 第 3 决策"双轨 ticker" + Dify DSL v2 迁移）：

- 业务子图节点（swap.place_order / option.extract_inquiry / close.place_close）
  通过 `await resolve_ticker_full(raw_text)` 拿 TickerResolution，对底层实现无感
- **对外签名与返回类型保持不变**：`resolve_ticker_full(raw_text: str) -> TickerResolution`
  / `resolve_ticker(raw_text: str) -> list[TickerCandidate]`
- 内部管线已切换为新 DSL 12 节点版本（见 tools.py 顶部说明）：
    候选提取(tokenize) -> 格式化(format_candidate_list) -> 空短路
    -> asyncio.gather(infer_code_batch, split_ticker_keywords, judge_ticker_type)
    -> merge_and_validate（确定性）
    -> 逐 orgStr：GOATS search_securities_instrument + rank_candidates(LLM 排序过滤)
    -> 取 top1 windCode 作为 winner
- `from_goats=True` 是 CLAUDE.md 硬约束（ADR 0008）：凡进入输出的标的必须经 GOATS
  校验存在性，这是本项目对 Dify 行为的有意增强（新 DSL 的"标的智能化推断和分词
  工具"本身不含 GOATS 校验步骤），不因 DSL 无此步而删除
- 0 命中 / 候选为空 → resolved=[]; hitl_pending=[]（当前无真实 HITL 中断实现，
  与迁移前行为一致，保留字段供未来接入 interrupt）
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, NamedTuple

from app.graph.state import TickerCandidate
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


async def resolve_ticker_full(raw_text: str) -> TickerResolution:
    """标的识别（新管线入口，含 HITL 信号占位，Issue #20）。

    Returns:
        TickerResolution(resolved, hitl_pending)
    """
    if not raw_text:
        return TickerResolution(resolved=[], hitl_pending=[])

    try:
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
# 实现：新管线编排（tokenize 候选提取 -> 并行 LLM -> 合并校验 -> GOATS + rank）
# ============================================================


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


async def _resolve_pipeline(raw_text: str) -> TickerResolution:
    """新 12 节点管线的本地编排实现。

    流程：
    1. tokenize(raw_text) 提取候选（P1 范围内本地替代"候选标的提取"，见 tools.py 说明）
    2. 过滤噪音候选（单字符 / 非 4-6 位纯数字 / 订单号前缀）
    3. format_candidate_list 格式化去重
    4. 空 → 短路返回空结果
    5. asyncio.gather 并行调 3 个 LLM：infer_code_batch / split_ticker_keywords /
       judge_ticker_type
    6. merge_and_validate 合并 + 确定性校验完整标的
    7. 逐 orgStr：GOATS 查询 + rank LLM 排序过滤 → winner
    8. winner 去重后组装 TickerCandidate（from_goats=True 硬约束）
    """
    raw_candidates = tokenize.invoke({"raw_text": raw_text})
    filtered = _filter_noise_candidates(raw_candidates)
    candidates = format_candidate_list(filtered)
    if not candidates:
        return TickerResolution(resolved=[], hitl_pending=[])

    infer_codes: dict[str, Any]
    split_codes: dict[str, Any]
    ins_family: dict[str, Any]
    infer_codes, split_codes, ins_family = await asyncio.gather(
        infer_code_batch(candidates),
        split_ticker_keywords(candidates),
        judge_ticker_type(candidates),
    )

    merged = merge_and_validate(infer_codes, split_codes, ins_family)

    client = _make_client()
    resolved: list[TickerCandidate] = []
    by_code: dict[str, TickerCandidate] = {}
    input_candidates = set(candidates)

    for item in merged:
        org_str = item["orgStr"]
        keywords = item["keywords"]
        predicted_family = str(ins_family.get(org_str) or "")

        winner = await _resolve_one_org_item(client, org_str, keywords, predicted_family)
        if winner is None:
            continue
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

    return TickerResolution(resolved=resolved, hitl_pending=[])


__all__ = ["TickerResolution", "resolve_ticker", "resolve_ticker_full"]
