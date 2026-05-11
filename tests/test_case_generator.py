"""harness/case_generator 测试（grill-with-docs 第 4 决策）。"""
from __future__ import annotations

import pytest

from harness.case_generator import (
    NODE_REGISTRY,
    NodeSeedSpec,
    render_seed_template,
)


# ============================================================
# 节点注册表
# ============================================================


def test_node_registry_contains_p0_nodes() -> None:
    """P0 横切 + 三链路核心节点必须在注册表里。"""
    must_have = {
        "ticker.react_agent",
        "swap.intent",
        "swap.place_order",
        "option.intent",
        "option.extract_place_or_modify",
        "close.intent",
        "close.place_close",
    }
    assert must_have.issubset(set(NODE_REGISTRY.keys()))


def test_swap_confirm_merges_three_intents() -> None:
    """ADR 0001 D5：合并版 swap.confirm 节点对应 3 个原 confirm 意图。"""
    spec = NODE_REGISTRY["swap.confirm"]
    assert set(spec.intent_values) == {
        "confirm_order",
        "confirm_cancel_order",
        "confirm_modify_order",
    }


def test_option_intent_does_not_include_close_intents() -> None:
    """ADR 0011 二次修订：option 意图不含 close_order_*。"""
    spec = NODE_REGISTRY["option.intent"]
    assert all(
        not v.startswith("close_order_") for v in spec.intent_values
    ), f"option.intent 不应含 close 意图，实际: {spec.intent_values}"


def test_close_intent_has_six_close_order_intents() -> None:
    """ADR 0011：close 子图独立，6 个 close_order_* 意图都归 close。"""
    spec = NODE_REGISTRY["close.intent"]
    close_intents = [v for v in spec.intent_values if v.startswith("close_order_")]
    assert len(close_intents) == 6


def test_ticker_has_no_intent() -> None:
    """ticker 子图输出 list[TickerCandidate]，无 intent 字段。"""
    spec = NODE_REGISTRY["ticker.react_agent"]
    assert spec.intent_values == []
    assert spec.product_type == "ticker"


# ============================================================
# 模板渲染
# ============================================================


def test_render_template_includes_node_name() -> None:
    md = render_seed_template("swap.place_order")
    assert "swap.place_order" in md
    assert "product_type" in md
    assert "place_order_request" in md


def test_render_template_default_eight_slots() -> None:
    md = render_seed_template("swap.intent")
    assert md.count("### Case ") == 8


def test_render_template_custom_slot_count() -> None:
    md = render_seed_template("swap.intent", num_slots=6)
    assert md.count("### Case ") == 6


def test_render_template_includes_sample_inputs() -> None:
    md = render_seed_template("ticker.react_agent")
    spec = NODE_REGISTRY["ticker.react_agent"]
    for sample in spec.sample_inputs:
        assert sample in md


def test_render_template_unknown_node_raises() -> None:
    with pytest.raises(KeyError, match="Unknown node"):
        render_seed_template("nonexistent.node")


def test_render_template_marks_source_as_business_seed() -> None:
    """业务方种子 case 必须标 source: business_seed（B 桶 PASS ≥ 90% 阈值）。"""
    md = render_seed_template("swap.place_order")
    assert "source: business_seed" in md
