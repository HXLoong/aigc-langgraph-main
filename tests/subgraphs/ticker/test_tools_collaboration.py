"""ticker 4 工具协作单测（#20 部分 · 不调真 LLM / 真 backend）。

验证 4 工具按典型业务流串联能拿到正确结果，覆盖 5 种核心场景：

| Scenario | tokenize → completeness → 后续 |
| --- | --- |
| 完整标准代码 | "00700.HK" → tokenize → completeness(true) → 直接用 |
| 中文简称推断 | "腾讯" → tokenize → completeness(false) → infer_code → 完整代码 |
| 多命中分差大 | "0700" → tokenize → completeness(false) → rank → 自动选 top1 |
| 多命中分差小 | "700" → tokenize → completeness(false) → rank → needs_hitl |
| 0 命中 | "不存在的标的" → tokenize → completeness(false) → rank/infer 都失败 → fallback |

实际 ReAct Agent 的 think 层决策由 LLM 做（见 #20 真 LLM 集成测试）；本测试
直接调工具验证"工具组合能完成业务"——降低对 LLM 推理质量的耦合。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.subgraphs.ticker import tools as tools_mod
from app.subgraphs.ticker.tools import (
    completeness,
    infer_code,
    rank,
    tokenize,
)
from app.tools.ticker_client import SecuritiesInstrumentRespVO


def _resp(wind: str, score: int = 0) -> SecuritiesInstrumentRespVO:
    return SecuritiesInstrumentRespVO(
        windCode=wind, insShtDesc=wind, relevanceScore=score
    )


def _mock_select(monkeypatch: pytest.MonkeyPatch, by_keyword: dict) -> None:
    """让 _make_client 返回的 client 按 keyword 路由不同响应。

    by_keyword: {"keyword": [resp_list], ...}
    缺省 keyword 返回 []。
    """
    client = MagicMock()

    async def _search(req):
        kw = req.keywordItems[0].keyword if req.keywordItems else ""
        return by_keyword.get(kw, [])

    client.search_securities_instrument = AsyncMock(side_effect=_search)
    monkeypatch.setattr(tools_mod, "_make_client", lambda: client)


# ============================================================
# 场景 1：完整标准代码 — 一步到位
# ============================================================


def test_scenario_complete_code_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """业务流：用户原话即标准代码 → tokenize 拿出 + completeness=true → 直接用。"""
    raw = "00700.HK"

    # Step 1: tokenize
    tokens = tokenize.invoke({"raw_text": raw})
    assert "00700.HK" in tokens
    assert "00700" in tokens  # 后缀剥离同时输出

    # Step 2: completeness — 完整代码命中 1
    _mock_select(monkeypatch, {"00700.HK": [_resp("00700.HK")]})
    result = completeness.invoke({"keyword": "00700.HK"})
    assert result["is_complete"] is True

    # 完整 → 流程终止，无需 rank/infer_code


# ============================================================
# 场景 2：中文简称 → infer_code 推断
# ============================================================


def test_scenario_short_name_via_infer_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """业务流：用户给中文简称 → tokenize → completeness=false → infer_code 推断完整码。"""
    raw = "腾讯"

    tokens = tokenize.invoke({"raw_text": raw})
    assert tokens == ["腾讯"]

    # completeness=false（"腾讯" 不是 isFull=true 的代码）
    _mock_select(monkeypatch, {})
    res_complete = completeness.invoke({"keyword": "腾讯"})
    assert res_complete["is_complete"] is False

    # infer_code → mock LLM 返回完整代码
    client = MagicMock()
    client.get_inference_prompt = AsyncMock(return_value="")
    monkeypatch.setattr(tools_mod, "_make_client", lambda: client)
    with patch.object(tools_mod, "_llm_infer", return_value="00700.HK"):
        inferred = infer_code.invoke({"keyword": "腾讯"})
    assert inferred == "00700.HK"


# ============================================================
# 场景 3：多命中分差大 → rank 自动选
# ============================================================


def test_scenario_multi_match_pick_best(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """业务流：多命中 → pick_best 自动选优，always 返回 winner。"""
    _mock_select(
        monkeypatch,
        {"0700": [_resp("00700.HK", 0), _resp("OTHER.HK", 10)]},
    )
    result = rank.invoke({"keyword": "0700"})
    assert result["winner"] == "00700.HK"
    assert result["needs_hitl"] is False
    assert result["reason"] == "goats_top1"


# ============================================================
# 场景 4：多命中分差小 → 仍由 pick_best 选优
# ============================================================


def test_scenario_multi_match_small_gap_still_picks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """分差小也不触发 HITL，pick_best 选出第一个 A股/前缀最短候选。"""
    _mock_select(
        monkeypatch,
        {"700": [_resp("00700.HK", 5), _resp("OTHER.HK", 8)]},
    )
    result = rank.invoke({"keyword": "700"})
    assert result["winner"] is not None
    assert result["needs_hitl"] is False
    assert len(result["candidates"]) == 2
    assert result["reason"] == "goats_top1"


# ============================================================
# 场景 5：0 命中 — fallback
# ============================================================


def test_scenario_zero_match_full_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """业务流：无任何匹配 → rank 返回 no_match + infer_code 失败 → fallback。

    业务侧响应："无法识别 <原话>，能用更标准的名称吗"
    """
    raw = "完全不存在的标的xyz"

    tokens = tokenize.invoke({"raw_text": raw})
    assert tokens == ["完全不存在的标的xyz"]

    # rank: 0 命中
    _mock_select(monkeypatch, {})
    rank_result = rank.invoke({"keyword": tokens[0]})
    assert rank_result["winner"] is None
    assert rank_result["reason"] == "no_match"

    # infer_code: LLM 也无能为力 → 原样返回
    client = MagicMock()
    client.get_inference_prompt = AsyncMock(return_value="")
    monkeypatch.setattr(tools_mod, "_make_client", lambda: client)
    with patch.object(
        tools_mod, "_llm_infer", side_effect=RuntimeError("LLM 无解")
    ):
        inferred = infer_code.invoke({"keyword": tokens[0]})
    assert inferred == tokens[0]  # 保守降级原样返回


# ============================================================
# 场景 6（额外）：复合输入 — 多 ticker 分别处理
# ============================================================


def test_scenario_multiple_tickers_in_one_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """业务流：用户一条原话含多支标的（"600519/000858"）→ tokenize 拆分 → 各自走 rank。"""
    raw = "600519/000858"

    tokens = tokenize.invoke({"raw_text": raw})
    assert tokens == ["600519", "000858"]

    # 两个都模糊命中
    _mock_select(
        monkeypatch,
        {
            "600519": [_resp("600519.SH", 0)],
            "000858": [_resp("000858.SZ", 0)],
        },
    )

    winners = []
    for tok in tokens:
        r = rank.invoke({"keyword": tok})
        winners.append(r["winner"])

    assert winners == ["600519.SH", "000858.SZ"]


# ============================================================
# 场景 7（额外）：嵌入数字代码 — tokenize 拆出后 rank 优先用数字
# ============================================================


def test_scenario_embedded_code_in_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """业务流：用户写 "02513智谱"（数字 + 中文）→ tokenize 拆分 → 两个 keyword 均查 rank。"""
    raw = "02513智谱"

    tokens = tokenize.invoke({"raw_text": raw})
    assert tokens == ["02513", "智谱"]

    # 02513 精确命中代码；智谱模糊命中相同代码
    _mock_select(
        monkeypatch,
        {
            "02513": [_resp("02513.HK", 0)],
            "智谱": [_resp("02513.HK", 1)],
        },
    )

    # 数字 keyword 优先（精确命中 score=0）
    r1 = rank.invoke({"keyword": "02513"})
    r2 = rank.invoke({"keyword": "智谱"})

    assert r1["winner"] == "02513.HK"
    assert r2["winner"] == "02513.HK"
    # 两个 keyword 指向同一 windCode → 业务侧应去重
