"""历史自动化测试报告的只读索引。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class HistoricalReportError(ValueError):
    """历史报告不存在或内容不合法。"""


class HistoricalReportStore:
    """在固定目录内发现并读取 langgraph-direct JSON 报告。"""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _reports(self) -> dict[str, Path]:
        if not self.root.is_dir():
            return {}
        reports: dict[str, Path] = {}
        for path in self.root.rglob("langgraph-direct-*.json"):
            if not path.is_file():
                continue
            relative = path.relative_to(self.root).as_posix()
            report_id = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:16]
            reports[report_id] = path
        return reports

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise HistoricalReportError(f"历史报告无法读取：{path.name}") from exc
        if not isinstance(value, dict) or not isinstance(value.get("cases"), list):
            raise HistoricalReportError(f"历史报告格式不合法：{path.name}")
        return value

    def list_reports(self) -> list[dict[str, Any]]:
        """按生成时间倒序返回报告摘要，不读取用例详情。"""
        reports: list[dict[str, Any]] = []
        for report_id, path in self._reports().items():
            try:
                payload = self._read(path)
            except HistoricalReportError:
                continue
            cases = payload["cases"]
            reports.append(
                {
                    "report_id": report_id,
                    "name": path.name,
                    "path": path.relative_to(self.root).as_posix(),
                    "generated_at": payload.get("generated_at"),
                    "summary": payload.get("summary") or {"total": len(cases)},
                    "case_count": len(cases),
                }
            )
        return sorted(
            reports,
            key=lambda item: (item.get("generated_at") or 0, item["path"]),
            reverse=True,
        )

    def load_report(self, report_id: str) -> dict[str, Any]:
        path = self._reports().get(report_id)
        if path is None:
            raise HistoricalReportError("历史报告不存在")
        return self._read(path)

    def get_case(self, report_id: str, case_index: int) -> dict[str, Any]:
        cases = self.load_report(report_id)["cases"]
        if case_index < 1 or case_index > len(cases):
            raise HistoricalReportError("历史用例不存在")
        case = cases[case_index - 1]
        if not isinstance(case, dict):
            raise HistoricalReportError("历史用例格式不合法")
        return case


__all__ = ["HistoricalReportError", "HistoricalReportStore"]
