"""ticker-only golden fixture 测试（#20 部分）。

读 `tests/fixtures/golden_ticker_2026-05.jsonl`，验证：
- tokenize 输出符合 expected.tokens
- 单独可校验的 case 也校验对应字段（is_complete / winner / needs_hitl 等）

注：ticker 子图当前未集成到主图（生产用 ticker_resolver 白名单），
本 fixture 不被 harness CLI 消费，仅作为单元测试 + 设计契约文档。
真 LLM ReAct E2E 留给 #M3 shadow 阶段。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.subgraphs.ticker.tools import tokenize
from app.subgraphs.ticker.whitelist import TICKER_WHITELIST

GOLDEN_PATH = (
    Path(__file__).parent.parent.parent
    / "fixtures"
    / "golden_ticker_2026-05.jsonl"
)


def _load_cases() -> list[dict]:
    return [
        json.loads(line)
        for line in GOLDEN_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_fixture_loads_and_has_minimum_30_cases() -> None:
    """#20 P0 退出门 + 路线图 B1.1：ticker-only golden ≥ 30 条。"""
    cases = _load_cases()
    assert len(cases) >= 30, f"实际 {len(cases)} 条，少于 #20 P0 退出门要求的 30 条"


def test_fixture_unique_ids() -> None:
    cases = _load_cases()
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "case id 重复"


def test_fixture_all_have_required_fields() -> None:
    """每条 case 必须含 id / category / raw_content / expected / source。"""
    cases = _load_cases()
    for c in cases:
        for field in ("id", "category", "raw_content", "expected", "source"):
            assert field in c, f"{c.get('id')} 缺字段 {field}"
        assert c["source"] == "ticker_unit"


def test_fixture_categories_cover_core_scenarios() -> None:
    """覆盖 #20 P0 + 路线图 B1.1 要求的核心场景类别。"""
    cases = _load_cases()
    categories = {c["category"].split("/")[1] for c in cases}
    expected_scenarios = {
        # #20 原核心 6 类
        "complete_code",       # 完整代码一步到位
        "short_name",          # 简称推断
        "multi_match_large_gap",  # 自动选
        "multi_match_small_gap",  # HITL
        "zero_match",          # fallback
        "multi_input",         # 多 ticker
        # 路线图 B1.1 新增 5 类（2026-05-12）
        "etf",                 # 复合标的 - ETF
        "index",               # 复合标的 - 指数
        "us_stock",            # 美股中文俗称
        "commodity_alias",     # 商品/期货俗称（缩写）
        "hk_index",            # 港股指数俗称
    }
    missing = expected_scenarios - categories
    assert not missing, f"缺场景覆盖: {missing}"


@pytest.mark.parametrize("case", _load_cases(), ids=lambda c: c["id"])
def test_tokenize_matches_expected(case: dict) -> None:
    """每条 case 的 tokenize 输出必须与 expected.tokens 完全一致。"""
    expected_tokens = case["expected"].get("tokens")
    if expected_tokens is None:
        pytest.skip(f"{case['id']} 无 expected.tokens 字段")
    actual = tokenize.invoke({"raw_text": case["raw_content"]})
    assert actual == expected_tokens, (
        f"{case['id']} tokenize 不匹配:\n"
        f"  raw: {case['raw_content']!r}\n"
        f"  expected: {expected_tokens}\n"
        f"  actual:   {actual}"
    )


@pytest.mark.parametrize("case", _load_cases(), ids=lambda c: c["id"])
def test_winner_is_known_wind_code(case: dict) -> None:
    """对于 expected.winner 非 null 的 case，winner 必须是白名单中某个有效的
    windCode（防止 expected.winner 字段拼写错误，如把 "00700.HK" 写成 "0700.HK"）。

    注意：本测试不强求 winner 必须从 token 直接命中——resolver 内部有
    4 位港股代码 → .HK 规范化、ReAct LLM 推断等多种解析路径，winner
    只要是白名单里存在的合法 windCode 就 OK。"""
    expected = case["expected"]
    winner = expected.get("winner")
    if winner is None:
        pytest.skip(f"{case['id']} 无 winner 字段")
    valid_wind_codes = {v[0] for v in TICKER_WHITELIST.values()}
    assert winner in valid_wind_codes, (
        f"{case['id']} winner={winner!r} 不是白名单中任何条目的 windCode（可能拼写错误）"
    )
