from __future__ import annotations

import json

import pytest


def test_history_store_discovers_reports_and_loads_cases(tmp_path) -> None:
    from harness.report_history import HistoricalReportStore

    report_path = tmp_path / "20260920" / "langgraph-direct-20260920-120000.json"
    report_path.parent.mkdir()
    report_path.write_text(
        json.dumps(
            {
                "generated_at": 1_790_000_000,
                "summary": {"total": 2, "passed": 1, "failed": 1},
                "cases": [
                    {"case_no": "case-001", "name": "成功用例", "passed": True},
                    {"case_no": "case-002", "name": "失败用例", "passed": False},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = HistoricalReportStore(tmp_path)

    reports = store.list_reports()

    assert len(reports) == 1
    assert reports[0]["name"] == report_path.name
    assert reports[0]["summary"]["total"] == 2
    report_id = reports[0]["report_id"]
    assert store.load_report(report_id)["cases"][0]["case_no"] == "case-001"
    assert store.get_case(report_id, 2)["case_no"] == "case-002"


def test_history_store_rejects_unknown_report_id(tmp_path) -> None:
    from harness.report_history import HistoricalReportError, HistoricalReportStore

    store = HistoricalReportStore(tmp_path)

    with pytest.raises(HistoricalReportError, match="历史报告不存在"):
        store.load_report("missing")
