"""LLM 成本监控单元测试。"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.observability import metrics
from scripts.llm_cost_report import (
    TokenBucket,
    _parse_labels,
    aggregate_by_model,
    aggregate_by_node,
    build_report,
    compute_growth,
    estimate_cost_usd,
    load_prices,
    parse_token_buckets,
)


@pytest.fixture(autouse=True)
def reset_collector() -> None:
    metrics.get_collector().reset()
    yield
    metrics.get_collector().reset()


# ============================================================
# emit_llm_tokens
# ============================================================


def test_emit_llm_tokens_basic() -> None:
    metrics.emit_llm_tokens("deepseek-v4-pro", prompt_tokens=1500, completion_tokens=800)
    coll = metrics.get_collector()
    assert coll.get_counter(metrics.METRIC_LLM_TOKENS, {"direction": "prompt", "model": "deepseek-v4-pro"}) == 1500
    assert coll.get_counter(metrics.METRIC_LLM_TOKENS, {"direction": "completion", "model": "deepseek-v4-pro"}) == 800


def test_emit_llm_tokens_with_node() -> None:
    metrics.emit_llm_tokens(
        "qwen3-30b-a3b",
        prompt_tokens=500,
        completion_tokens=200,
        node="swap.intent",
    )
    coll = metrics.get_collector()
    assert coll.get_counter(
        metrics.METRIC_LLM_TOKENS,
        {"direction": "prompt", "model": "qwen3-30b-a3b", "node": "swap.intent"},
    ) == 500


def test_emit_llm_tokens_ignores_negative() -> None:
    """负数 token 应被忽略，不污染计数器。"""
    metrics.emit_llm_tokens("deepseek-v4-pro", -100, 50)
    coll = metrics.get_collector()
    # 计数器应该为 0（不应被任何值写入）
    assert coll.get_counter(
        metrics.METRIC_LLM_TOKENS, {"direction": "prompt", "model": "deepseek-v4-pro"}
    ) == 0


def test_emit_llm_tokens_zero_ok() -> None:
    """0 token 是合法的（如纯 system prompt）。"""
    metrics.emit_llm_tokens("deepseek-v4-pro", 0, 100)
    coll = metrics.get_collector()
    assert coll.get_counter(
        metrics.METRIC_LLM_TOKENS, {"direction": "completion", "model": "deepseek-v4-pro"}
    ) == 100


def test_emit_llm_tokens_renders_to_prometheus() -> None:
    """渲染到 /metrics 端点格式正确。"""
    metrics.emit_llm_tokens("deepseek-v4-pro", 1000, 500, node="render")
    output = metrics.get_collector().render_prometheus()
    assert "otc_agent_llm_tokens_total" in output
    assert 'model="deepseek-v4-pro"' in output
    assert 'direction="prompt"' in output
    assert 'direction="completion"' in output
    assert 'node="render"' in output


# ============================================================
# 报表脚本（parse / aggregate / cost / growth）
# ============================================================





def test_parse_labels_basic() -> None:
    result = _parse_labels('model="deepseek-v4-pro",direction="prompt"')
    assert result == {"model": "deepseek-v4-pro", "direction": "prompt"}


def test_parse_token_buckets() -> None:
    text = """
# TYPE otc_agent_llm_tokens_total counter
otc_agent_llm_tokens_total{direction="prompt",model="deepseek-v4-pro"} 1500
otc_agent_llm_tokens_total{direction="completion",model="deepseek-v4-pro"} 800
otc_agent_llm_tokens_total{direction="prompt",model="qwen3-30b-a3b",node="swap.intent"} 200
"""
    buckets = parse_token_buckets(text)
    assert len(buckets) == 3
    assert buckets[0].model == "deepseek-v4-pro"
    assert buckets[0].direction == "prompt"
    assert buckets[0].tokens == 1500
    assert buckets[2].node == "swap.intent"


def test_estimate_cost_usd() -> None:
    prices = {"deepseek-v4-pro": {"prompt": 0.50, "completion": 1.50}}
    # 1M prompt tokens × $0.50/M = $0.50
    b = TokenBucket(model="deepseek-v4-pro", direction="prompt", node=None, tokens=1_000_000)
    assert estimate_cost_usd(b, prices) == 0.5

    # 100K completion tokens × $1.50/M = $0.15
    b = TokenBucket(model="deepseek-v4-pro", direction="completion", node=None, tokens=100_000)
    assert estimate_cost_usd(b, prices) == pytest.approx(0.15)


def test_estimate_cost_unknown_model_returns_zero() -> None:
    prices = {"deepseek-v4-pro": {"prompt": 0.50}}
    b = TokenBucket(model="unknown-model", direction="prompt", node=None, tokens=1_000_000)
    assert estimate_cost_usd(b, prices) == 0.0


def test_aggregate_by_model() -> None:
    buckets = [
        TokenBucket("ds-v4", "prompt", None, 1000),
        TokenBucket("ds-v4", "completion", None, 500),
        TokenBucket("ds-v4", "prompt", "swap.intent", 200),  # 同 model 同 direction
        TokenBucket("qwen", "prompt", None, 800),
    ]
    agg = aggregate_by_model(buckets)
    assert agg["ds-v4"]["prompt"] == 1200
    assert agg["ds-v4"]["completion"] == 500
    assert agg["ds-v4"]["total"] == 1700
    assert agg["qwen"]["prompt"] == 800
    assert agg["qwen"]["completion"] == 0


def test_aggregate_by_node_excludes_unlabeled() -> None:
    buckets = [
        TokenBucket("ds-v4", "prompt", "swap.intent", 1000),
        TokenBucket("ds-v4", "completion", "swap.intent", 200),
        TokenBucket("ds-v4", "prompt", None, 500),  # 无 node 不计入
    ]
    agg = aggregate_by_node(buckets)
    assert "swap.intent" in agg
    assert agg["swap.intent"] == 1200


def test_compute_growth() -> None:
    assert compute_growth(150, 100) == 50.0  # +50%
    assert compute_growth(100, 100) == 0.0
    assert compute_growth(50, 100) == -50.0  # -50%


def test_compute_growth_zero_yesterday() -> None:
    """昨日 0 时不应除零。"""
    assert compute_growth(100, 0) == 0.0


def test_build_report_structure() -> None:
    buckets = [
        TokenBucket("deepseek-v4-pro", "prompt", "swap.intent", 1000),
        TokenBucket("deepseek-v4-pro", "completion", "swap.intent", 500),
    ]
    prices = {"deepseek-v4-pro": {"prompt": 0.50, "completion": 1.50}}
    report = build_report(buckets, prices)
    assert "timestamp" in report
    assert "date" in report
    assert report["total_tokens"] == 1500
    # cost = 1000/1M × 0.5 + 500/1M × 1.5 = 0.0005 + 0.00075 = 0.00125
    # build_report 内部 round(_, 4) → 0.0013
    assert report["total_cost_usd"] == pytest.approx(0.0013, abs=1e-4)
    assert "deepseek-v4-pro" in report["by_model"]
    assert "swap.intent" in report["by_node"]


def test_load_prices_default() -> None:
    """默认价格表含 DeepSeek + Qwen。"""
    prices = load_prices()
    assert "deepseek-v4-pro" in prices
    assert "qwen3-30b-a3b" in prices


def test_load_prices_from_env() -> None:
    custom = '{"my-model": {"prompt": 0.1, "completion": 0.3}}'
    with patch.dict("os.environ", {"LLM_PRICE_PER_M_TOKENS_JSON": custom}):
        prices = load_prices()
    assert prices == {"my-model": {"prompt": 0.1, "completion": 0.3}}


def test_load_prices_from_env_malformed_falls_back() -> None:
    """坏 JSON 时回退到默认（不崩）。"""
    with patch.dict("os.environ", {"LLM_PRICE_PER_M_TOKENS_JSON": "not json"}):
        prices = load_prices()
    assert "deepseek-v4-pro" in prices  # 回退到默认表
