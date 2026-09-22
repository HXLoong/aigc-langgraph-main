from __future__ import annotations

from harness.golden import GoldenCase, TurnSpec
from scripts.langfuse.upload_golden_to_langfuse import build_expected, build_input


def test_dataset_projection_keeps_categories_shape() -> None:
    case = GoldenCase(
        id="case-021",
        category="option/inquiry",
        turns=[
            TurnSpec(
                scene="普通询价",
                send_text="600519.SH，欧式看涨,1M，80%",
                at_bot=True,
                expected={
                    "product_type": "option",
                    "intent": "new_inquiry",
                    "winners": ["600519.SH"],
                },
                response_contains=["场外期权询价详情"],
                response_not_contains=["未搜索到相关标的信息"],
            ),
            TurnSpec(
                scene="补充名义本金",
                send_text="100万",
                quote_previous=True,
                expected={"intent": "new_inquiry"},
                response_contains_any=["名义本金：100万", "名义本金：1,000,000"],
                response_not_contains=["【待补充】"],
            ),
        ],
        expected={
            "product_type": "option",
            "intent": "new_inquiry",
            "winners": ["600519.SH"],
        },
    )

    assert build_input(case) == {
        "send_text": "600519.SH，欧式看涨,1M，80%",
        "at_bot": True,
        "sub_scenes": [
            {
                "send_text": "100万",
                "at_bot": False,
                "quote_previous": True,
            }
        ],
    }
    assert build_expected(case) == {
        "expected": {
            "product_type": "option",
            "intent": "new_inquiry",
            "winners": ["600519.SH"],
        },
        "response_contains": ["场外期权询价详情"],
        "response_not_contains": ["未搜索到相关标的信息"],
        "sub_scenes": [
            {
                "expected": {"intent": "new_inquiry"},
                "response_contains_any": [
                    "名义本金：100万",
                    "名义本金：1,000,000",
                ],
                "response_not_contains": ["【待补充】"],
            }
        ],
    }
    assert "expected_scope" not in build_expected(case)
    assert "turns" not in build_expected(case)
