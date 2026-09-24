from __future__ import annotations

from pathlib import Path

from harness.golden import GoldenCase, TurnSpec, load_golden
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


def test_detect_suite_from_source_path() -> None:
    """意图集放 tests/fixtures/intent/，其余按业务集处理。"""
    from pathlib import Path

    from scripts.langfuse.upload_golden_to_langfuse import detect_suite

    assert detect_suite(Path("tests/fixtures/intent/swap.jsonl")) == "intent"
    assert detect_suite(Path("tests/fixtures/intent")) == "intent"
    assert detect_suite(Path("tests/fixtures/categories/swap_prod_data.jsonl")) == "business"
    assert detect_suite(Path("tests/fixtures/categories")) == "business"


def test_metadata_carries_suite_backend_and_drops_empty_tags() -> None:
    from scripts.langfuse.upload_golden_to_langfuse import _metadata

    case = GoldenCase(
        id="intent-swap-1",
        category="intent/swap",
        turns=[TurnSpec(send_text="市价买一百万京东", at_bot=True)],
        expected={"product_type": "swap", "intent": "place_order_request"},
    )
    metadata = _metadata(case, suite="intent", backend="mock")

    assert metadata["suite"] == "intent"
    assert metadata["backend"] == "mock"
    assert metadata["tags"] == ["intent/swap", "intent"]
    assert "" not in metadata["tags"]


def test_dataset_metadata_binds_instrument_evaluator_only_with_instrument_labels():
    from scripts.langfuse.upload_golden_to_langfuse import build_dataset_metadata

    root = Path(__file__).resolve().parents[2]
    option = load_golden(root / 'tests/fixtures/intent/option.jsonl')
    swap = load_golden(root / 'tests/fixtures/intent/swap_instrument.jsonl')
    assert build_dataset_metadata(option, suite='intent')['evaluator_names'] == ['intent-match']
    assert build_dataset_metadata(swap, suite='intent')['evaluator_names'] == [
        'intent-match', 'instrument-match',
    ]


def test_dataset_item_ids_are_stable_and_do_not_move_items_between_datasets():
    from scripts.langfuse.upload_golden_to_langfuse import dataset_item_id

    assert dataset_item_id('intent-option', 'case-025') == dataset_item_id('intent-option', 'case-025')
    assert dataset_item_id('intent-option', 'case-025') != dataset_item_id('business-option', 'case-025')


def test_manual_upload_defaults_dataset_name_and_passes_base_url(monkeypatch) -> None:
    """--sync-all 去掉了 --dataset-name 默认值后，手动模式必须回落到 DATASET_NAME，
    且 --base-url 要同时传给清空接口与 Langfuse 客户端（回归：合并后曾用 None 作数据集名）。"""
    import inspect
    import sys
    import types

    import scripts.langfuse.upload_golden_to_langfuse as mod

    assert "base_url" in inspect.signature(mod._clear_dataset).parameters
    source = Path("tests/fixtures/categories/golden_option_inquiry_case.jsonl")
    cleared: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        mod, "_clear_dataset",
        lambda name, *, base_url=None: cleared.append((name, base_url)),
    )

    created: dict[str, object] = {}

    class FakeLangfuse:
        def __init__(self, **kwargs: object) -> None:
            created["client_kwargs"] = kwargs

        def create_dataset(self, *, name: str, metadata: object) -> object:
            created["dataset"] = name
            return types.SimpleNamespace(name=name)

        def create_dataset_item(self, **kwargs: object) -> None:
            created.setdefault("item_datasets", []).append(kwargs["dataset_name"])  # type: ignore[union-attr]

    monkeypatch.setitem(sys.modules, "langfuse", types.SimpleNamespace(Langfuse=FakeLangfuse))
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setattr(
        sys, "argv",
        ["upload", "--source", str(source), "--base-url", "http://langfuse.local"],
    )

    assert mod.main() == 0
    assert cleared == [(mod.DATASET_NAME, "http://langfuse.local")]
    assert created["client_kwargs"] == {"base_url": "http://langfuse.local"}
    assert created["dataset"] == mod.DATASET_NAME
    item_datasets = created["item_datasets"]
    assert isinstance(item_datasets, list) and item_datasets
    assert set(item_datasets) == {mod.DATASET_NAME}
