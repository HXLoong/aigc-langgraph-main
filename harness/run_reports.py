"""CLI 与平台触发共用的仓库外逐条报告。"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from harness.evaluation import summarize
from harness.reporting import render_markdown

RUN_ROOT = (
    Path(tempfile.gettempdir()) / "aigc-langgraph-tmp" / "harness"
    if os.name == "nt"
    else Path("/opt/work-file/code-tmp/aigc-langgraph-tmp/harness")
)


class RunReports:
    """先保存每条结果，批次收尾保留完整请求分母。"""

    def __init__(self, run_id: str, requested: int, metadata: dict[str, Any]) -> None:
        self.directory = RUN_ROOT / run_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.requested = requested
        self.metadata = metadata
        self.reports: list[dict[str, Any]] = []

    def append(self, report: dict[str, Any]) -> None:
        with (self.directory / "results.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(report, ensure_ascii=False, default=str) + "\n")
        self.reports.append(report)

    def finish(self) -> dict[str, Any]:
        summary = {
            **summarize(self.reports), **self.metadata,
            "total": self.requested,
            "requested": self.requested,
            "recorded": len(self.reports),
            "unexecuted": self.requested - len(self.reports),
            "skipped": sum(row["status"] == "SKIP" for row in self.reports),
            "pass_rate": sum(bool(row["passed"]) for row in self.reports) / self.requested
            if self.requested else 0.0,
            "reports": self.reports,
        }
        (self.directory / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8",
        )
        (self.directory / "report.md").write_text(
            f"请求用例：{self.requested}；已记录：{len(self.reports)}；"
            f"未执行：{summary['unexecuted']}\n\n" + render_markdown(self.reports), encoding="utf-8",
        )
        return summary
