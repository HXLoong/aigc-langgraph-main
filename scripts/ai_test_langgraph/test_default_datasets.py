"""CLI 和工作台共同消费直属分类数据，显式多文件继续兼容。"""
from __future__ import annotations

import json
from pathlib import Path

import automation_runner_server as server
import langgraph_direct_regression as cli


def test_default_cli_loads_all_categories_in_filename_order(capsys):
    expected = sorted((cli.REPO_ROOT / "tests/fixtures/categories").glob("*.jsonl"))
    assert len(expected) == 6
    assert cli.resolve_paths([]) == expected
    assert len(cli.load_cases(cli.resolve_paths([]))) == 388
    assert cli.main(["--dry-run", "--limit", "3"]) == 0
    output = capsys.readouterr().out
    assert "加载 388 条，选中 3 条" in output
    assert "case-030" in output


def test_default_workbench_discovers_only_direct_categories():
    datasets = server.discover_datasets()
    paths = [Path(item["path"]) for item in datasets]
    assert len(paths) == 6
    assert all(path.parent == Path("tests/fixtures/categories") for path in paths)
    assert [path.name for path in paths] == sorted(path.name for path in paths)
    assert sum(item["cases"] for item in datasets) == 388


def test_default_discovery_ignores_nested_and_archived_jsonl(tmp_path, monkeypatch):
    categories = tmp_path / "tests/fixtures/categories"
    for relative in ("a.jsonl", "b.jsonl", "nested/ignored.jsonl", "../old_typing/ignored.jsonl"):
        path = categories / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"name": path.stem, "send_text": "测试"}), encoding="utf-8")
    monkeypatch.setattr(cli, "DEFAULT_DATASET_DIR", categories)
    monkeypatch.setattr(server, "DATASET_ROOT", categories)
    monkeypatch.setattr(server, "REPO_ROOT", tmp_path)
    assert cli.resolve_paths([]) == [categories / "a.jsonl", categories / "b.jsonl"]
    assert [item["name"] for item in server.discover_datasets()] == ["a.jsonl", "b.jsonl"]


def test_cli_explicit_multiple_files_preserves_formats_and_order(tmp_path, capsys):
    conversation = tmp_path / "conversation.jsonl"
    conversation.write_text(json.dumps({
        "id": "legacy-conversation", "category": "swap", "source": "test",
        "conversation": [{"raw_content": "下单"}, {"raw_content": "确认", "quote_desc": "上一轮"}],
    }), encoding="utf-8")
    ticker = tmp_path / "ticker.jsonl"
    ticker.write_text(json.dumps({"id": "legacy-ticker", "raw_content": "600519.SH"}), encoding="utf-8")
    paths = cli.resolve_paths([str(ticker), str(conversation)])
    cases = cli.load_cases(paths)
    assert [case["caseNo"] for case in cases] == ["legacy-ticker", "legacy-conversation"]
    assert cases[1]["sub_scenes"][0]["quote_previous"] is True
    assert cli.main(["--data", str(ticker), "--data", str(conversation), "--dry-run"]) == 0
    assert "加载 2 条，选中 2 条" in capsys.readouterr().out


def test_offline_self_tests_use_current_datasets():
    assert cli.run_self_test() == 0
    assert server.run_self_test() == 0
