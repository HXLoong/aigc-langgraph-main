"""D2.4 真后端联调发现：tokenize 时间词/业务术语过滤（Issue #76）。"""
from __future__ import annotations

import pytest

from app.subgraphs.ticker.tools import tokenize


@pytest.mark.parametrize("tenors", ["1M/2M", "1d/2W/3m/0.5y", "1.5M/2.25W", "1个月/2个月"])
def test_compact_tenors_are_not_ticker_candidates(tenors) -> None:
    assert tokenize.invoke({"raw_text": f"600519.SH,{tenors},80%"}) == ["600519.SH", "600519"]


@pytest.mark.parametrize("ticker", ["600519.SH", "MMM.N", "AAPL.O", "M2409.DCE", "3M.N", "Moutai"])
def test_tenor_filter_preserves_instrument_tokens(ticker) -> None:
    assert ticker in tokenize.invoke({"raw_text": ticker})


def test_tenor_filter_preserves_existing_bare_future_tokenization() -> None:
    assert tokenize.invoke({"raw_text": "M2409"}) == ["2409", "M"]


def test_tenor_words_excluded() -> None:
    """1个月 / 3个月 / 6个月 / 1年 等时间词不进 GOATS 查询。"""
    assert "1个月" not in tokenize.invoke({"raw_text": "贵州茅台 1个月 1800"})
    assert "3个月" not in tokenize.invoke({"raw_text": "阿里巴巴 3个月 70"})
    assert "6个月" not in tokenize.invoke({"raw_text": "腾讯 6个月 雪球"})
    assert "1年" not in tokenize.invoke({"raw_text": "贵州茅台 1年"})


def test_business_terms_excluded() -> None:
    """行权价 / 执行价 / 敲入 / 敲出 等期权术语不进 GOATS 查询。"""
    for term in ("行权价", "执行价", "敲入", "敲出", "期限", "名义本金", "参与率"):
        result = tokenize.invoke({"raw_text": f"贵州茅台 {term} 1800"})
        assert term not in result, f"term {term!r} should be filtered"


def test_valid_tickers_still_extracted() -> None:
    """过滤层不影响正常 ticker keyword：标的名/代码仍正确输出。"""
    r = tokenize.invoke({"raw_text": "贵州茅台 欧式看涨期权 1个月 行权价 1800"})
    assert "贵州茅台" in r
    assert "欧式看涨期权" in r  # 不在黑名单（实际是业务术语，但为保守起见保留）
    assert "1800" in r           # 数字仍输出（LLM 推断会用）
    assert "1个月" not in r
    assert "行权价" not in r


def test_partial_match_keeps_ticker_name() -> None:
    """"1个月" 这种完全匹配过滤；"嘉实1个月理财"这种合成 token → 保留（不是纯时间词）。"""
    r = tokenize.invoke({"raw_text": "嘉实1个月理财"})
    # 当前 tokenize 不切分，整个保留为一个 token
    assert "嘉实1个月理财" in r


def test_short_digits_pure_number_still_passes() -> None:
    """4-6 位数字代码仍正常通过（行权价 1800 这种短数字交给 LLM 判定）。"""
    r = tokenize.invoke({"raw_text": "600519 1800"})
    assert "600519" in r
    assert "1800" in r  # 4 位数字虽可能是代码也可能是价格，保留交给 GOATS 判定


def test_existing_cases_still_pass() -> None:
    """旧 tokenize 主要 case 不能破坏（含"买"等动词目前仍输出）。"""
    r = tokenize.invoke({"raw_text": "买 02513智谱 1000 股"})
    assert "02513" in r
    assert "智谱" in r
    assert "1000" in r

    r = tokenize.invoke({"raw_text": "0700.HK"})
    assert r == ["0700.HK", "0700"]

    r = tokenize.invoke({"raw_text": "600519/000858"})
    assert r == ["600519", "000858"]
