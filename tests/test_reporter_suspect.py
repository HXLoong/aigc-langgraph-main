"""harness reporter 启发式定位测试（M2 升级版 _suspect）。

ADR 0001 D7 D7：嫌疑节点根据 product_type 分流到正确子图节点，
替代 M1 的扁平 _FIELD_TO_NODE_HINTS。
"""
from __future__ import annotations

from harness.differ import FieldDiff
from harness.golden import GoldenCase
from harness.reporter import _suspect, render_failure_json
from harness.runner import RunResult


def _diff(path: str = "intent") -> list[FieldDiff]:
    return [FieldDiff(path=path, expected="x", actual="y")]


# ============================================================
# 第 1 层：product_type 分流
# ============================================================


class TestIntentByProductType:
    def test_swap_intent_failure_points_to_swap_intent_node(self) -> None:
        node, prompt = _suspect(_diff("intent"), {"product_type": "swap"})
        assert node == "swap_intent"
        assert prompt == "app/prompts/swap/intent.md"

    def test_option_intent_failure_points_to_option_intent_node(self) -> None:
        node, prompt = _suspect(_diff("intent"), {"product_type": "option"})
        assert node == "option_intent"
        assert prompt == "app/prompts/option/intent.md"

    def test_close_intent_failure_points_to_close_intent_node(self) -> None:
        node, prompt = _suspect(
            _diff("intent"), {"product_type": "option_close"}
        )
        assert node == "close_intent"
        assert prompt == "app/prompts/option_close/intent.md"


class TestPlaceParamsByProductType:
    def test_swap_place_params_points_to_swap_place_order(self) -> None:
        node, prompt = _suspect(
            _diff("place_params.orderList[0]"), {"product_type": "swap"}
        )
        assert node == "swap_place_order"
        assert prompt == "app/prompts/swap/place_order.md"

    def test_option_place_params_points_to_extract_place_or_modify(self) -> None:
        node, _ = _suspect(_diff("place_params"), {"product_type": "option"})
        assert node == "option_extract_place_or_modify"

    def test_option_close_place_params_points_to_close_place_close(self) -> None:
        node, _ = _suspect(
            _diff("place_params"), {"product_type": "option_close"}
        )
        assert node == "close_place_close"


class TestTickersByProductType:
    def test_swap_tickers_points_to_place_order(self) -> None:
        node, _ = _suspect(_diff("tickers"), {"product_type": "swap"})
        assert node == "swap_place_order"

    def test_option_tickers_points_to_extract_inquiry(self) -> None:
        """tickers 在 option 链路由 extract_inquiry 写。"""
        node, _ = _suspect(_diff("tickers"), {"product_type": "option"})
        assert node == "option_extract_inquiry"


# ============================================================
# 第 2 层：兜底（product_type 未知或不在分流表）
# ============================================================


class TestFallback:
    def test_intent_with_unknown_product_falls_back_to_intent_route(
        self,
    ) -> None:
        """g019 类场景：product_type=unknown → intent_route 漏判嫌疑。"""
        node, prompt = _suspect(_diff("intent"), {"product_type": "unknown"})
        assert node == "intent_route"
        assert prompt == "app/prompts/router/product_type.md"

    def test_intent_without_final_state_falls_back(self) -> None:
        node, _ = _suspect(_diff("intent"), None)
        assert node == "intent_route"

    def test_product_type_diff_always_intent_route(self) -> None:
        node, _ = _suspect(_diff("product_type"), {"product_type": "swap"})
        assert node == "intent_route"


# ============================================================
# 端到端：render_failure_json 拿到正确 suspected_node
# ============================================================


def test_render_failure_json_uses_product_type_aware_suspect() -> None:
    """g008 真实失败场景：swap intent 错判 → suspected_node 应是 swap_intent。"""
    case = GoldenCase(
        id="g008",
        category="swap/confirm_modify",
        raw_content="swap确认修改订单 H-...",
        expected={"product_type": "swap", "intent": "confirm_modify_order"},
    )
    result = RunResult(
        case=case,
        final_state={
            "product_type": "swap",
            "intent": "place_order_request",
            "trace": [],
        },
        elapsed_ms=10,
    )
    diffs = [
        FieldDiff(
            path="intent",
            expected="confirm_modify_order",
            actual="place_order_request",
        )
    ]
    rep = render_failure_json(result, diffs)

    # M2 升级：suspected_node 现在精确指向 swap_intent（不是 intent_route）
    assert rep["suspected_node"] == "swap_intent"
    assert rep["suspected_prompt"] == "app/prompts/swap/intent.md"
