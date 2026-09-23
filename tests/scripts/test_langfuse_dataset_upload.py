from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

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


def _write(path: Path, *rows: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def test_sync_all_discovers_only_intent_and_categories(tmp_path: Path) -> None:
    from scripts.langfuse.upload_golden_to_langfuse import prepare_sync_files

    root = tmp_path / "tests" / "fixtures"
    _write(root / "intent" / "option_close.jsonl", {
        "caseNo": "intent-1", "send_text": "平仓", "expected": {"intent": "place_close"},
        "description": "意图说明", "reference": {"ticket": "Q-1"},
        "sub_scenes": [{"send_text": "确认", "wait_before_seconds": 2.5,
                        "expected": {"intent": "confirm_close"}}],
    })
    _write(root / "categories" / "golden_option_close_case.jsonl", {
        "caseNo": "business-1", "send_text": "询价", "expected": {"product_type": "option"},
        "reference": "业务来源", "description": "业务说明",
    })
    node_path = root / "nodes" / "option_close" / "close_intent.jsonl"
    node_path.parent.mkdir(parents=True)
    node_path.write_text("invalid node JSONL\n", encoding="utf-8")
    _write(root / "categories" / "tr-data" / "ignored.jsonl", {"id": "ignored"})

    files = prepare_sync_files(root)
    assert [file.dataset_name for file in files] == [
        "golden_option_close_case", "intent_option_close",
    ]
    business, intent = [file.items[0] for file in files]
    assert business["id"] == "golden_option_close_case:business-1"
    assert intent["id"] == "intent_option_close:intent-1"
    assert business["input"] == {"send_text": "询价", "at_bot": True, "sub_scenes": []}
    assert business["expected_output"]["expected"] == {"product_type": "option"}
    assert business["metadata"]["reference"] == "业务来源"
    assert business["metadata"]["description"] == "业务说明"
    assert intent["input"]["sub_scenes"][0]["wait_before_seconds"] == 2.5
    assert intent["expected_output"]["sub_scenes"][0]["expected"] == {"intent": "confirm_close"}
    assert intent["metadata"]["reference"] == {"ticket": "Q-1"}


@pytest.mark.parametrize("duplicate_kind", ["name", "id"])
def test_sync_all_rejects_conflicts_before_upload(tmp_path: Path, duplicate_kind: str) -> None:
    from scripts.langfuse.upload_golden_to_langfuse import prepare_sync_files

    root = tmp_path / "fixtures"
    _write(root / "intent" / "x.jsonl", {"id": "same", "send_text": "a"})
    if duplicate_kind == "name":
        _write(root / "categories" / "intent_x.jsonl", {"id": "other", "send_text": "b"})
    else:
        _write(root / "categories" / "other.jsonl", {"id": "same", "send_text": "b"})
    with pytest.raises(ValueError, match="Dataset name conflict|Duplicate case ID"):
        prepare_sync_files(root)


class _DatasetClient:
    def __init__(self) -> None:
        self.items: dict[str, dict] = {}
        self.calls: list[dict] = []
        self.fail_id: str | None = None

    def create_dataset(self, *, name: str) -> SimpleNamespace:
        return SimpleNamespace(name=name)

    def create_dataset_item(self, **kwargs: object) -> None:
        self.calls.append(kwargs)
        if kwargs["id"] == self.fail_id:
            raise RuntimeError("upload failed")
        self.items[str(kwargs["id"])] = dict(kwargs)

    def get_dataset(self, name: str) -> SimpleNamespace:
        return SimpleNamespace(items=[SimpleNamespace(id=item_id, status=item["status"])
                                      for item_id, item in self.items.items()
                                      if item["dataset_name"] == name])


def test_sync_reuses_ids_reactivates_and_archives_removed_items(tmp_path: Path) -> None:
    from scripts.langfuse.upload_golden_to_langfuse import prepare_sync_files, sync_prepared_files

    root = tmp_path / "fixtures"
    path = root / "intent" / "x.jsonl"
    _write(path, {"id": "a", "send_text": "one"}, {"id": "b", "send_text": "two"})
    client = _DatasetClient()
    sync_prepared_files(client, prepare_sync_files(root))
    sync_prepared_files(client, prepare_sync_files(root))
    assert set(client.items) == {"intent_x:a", "intent_x:b"}
    assert all(item["status"] == "ACTIVE" for item in client.items.values())

    _write(path, {"id": "a", "send_text": "changed"})
    sync_prepared_files(client, prepare_sync_files(root))
    assert client.items["intent_x:a"]["input"]["send_text"] == "changed"
    assert client.items["intent_x:b"]["status"] == "ARCHIVED"
    _write(path, {"id": "a", "send_text": "changed"}, {"id": "b", "send_text": "back"})
    sync_prepared_files(client, prepare_sync_files(root))
    assert client.items["intent_x:b"]["status"] == "ACTIVE"


def test_sync_failure_and_empty_file_never_archive(tmp_path: Path) -> None:
    from scripts.langfuse.upload_golden_to_langfuse import prepare_sync_files, sync_prepared_files

    root = tmp_path / "fixtures"
    path = root / "intent" / "x.jsonl"
    _write(path, {"id": "keep", "send_text": "one"}, {"id": "fail", "send_text": "two"})
    client = _DatasetClient()
    sync_prepared_files(client, prepare_sync_files(root))
    _write(path, {"id": "fail", "send_text": "two"})
    client.fail_id = "intent_x:fail"
    with pytest.raises(RuntimeError, match="upload failed"):
        sync_prepared_files(client, prepare_sync_files(root))
    assert client.items["intent_x:keep"]["status"] == "ACTIVE"

    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        prepare_sync_files(root)
    assert client.items["intent_x:keep"]["status"] == "ACTIVE"


def test_sync_does_not_reuse_id_from_historical_dataset(tmp_path: Path) -> None:
    from scripts.langfuse.upload_golden_to_langfuse import prepare_sync_files, sync_prepared_files

    root = tmp_path / "fixtures"
    _write(root / "intent" / "x.jsonl", {"id": "same", "send_text": "new"})
    client = _DatasetClient()
    client.items["same"] = {"id": "same", "dataset_name": "intent-x", "status": "ACTIVE"}
    sync_prepared_files(client, prepare_sync_files(root))
    assert client.items["same"]["dataset_name"] == "intent-x"
    assert client.items["intent_x:same"]["dataset_name"] == "intent_x"


def test_sync_cli_passes_base_url_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.langfuse import upload_golden_to_langfuse as upload

    seen: dict[str, object] = {}
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://wrong.example")
    monkeypatch.setattr(sys, "argv", ["upload", "--sync-all", "--base-url", "https://right.example"])
    monkeypatch.setattr(upload, "prepare_sync_files", lambda: [])
    monkeypatch.setattr(upload, "sync_prepared_files", lambda client, files: seen.update(client=client, files=files))
    monkeypatch.setattr("langfuse.Langfuse", lambda **kwargs: seen.update(kwargs=kwargs) or object())
    assert upload.main() == 0
    assert seen["kwargs"] == {"base_url": "https://right.example"}
