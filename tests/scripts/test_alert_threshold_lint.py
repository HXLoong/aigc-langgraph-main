"""scripts/check_alert_threshold_consistency.py · CI lint 测试。

测试范围：
- AST 解析 alerts.py（含 P95 baseline × multiplier 表达式）
- ADR 0019 §1 表格抽取（含数字开头的 alert name 如 p95_*）
- runbook §3 表格抽取
- 比对算法发现不一致
- CLI 主流程 + 退出码 + JSON 输出
- 真实仓库三处一致性（回归测试）
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.check_alert_threshold_consistency import (
    AlertSpec,
    _extract_sustain_seconds,
    _extract_threshold_value,
    compare,
    parse_adr_0019,
    parse_alerts_py,
    parse_runbook,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_alert_threshold_consistency.py"

# ============================================================
# _extract_threshold_value · 阈值文本抽数字
# ============================================================


def test_extract_pct() -> None:
    assert _extract_threshold_value("≥ 5%", "any") == 5.0
    assert _extract_threshold_value("≥ 1%", "any") == 1.0
    assert _extract_threshold_value("≥ 10%", "any") == 10.0


def test_extract_ms() -> None:
    assert _extract_threshold_value("≥ 12600ms", "any") == 12600.0


def test_extract_count_returns_zero_for_non_canary() -> None:
    """is_canary=false ≥ 1 → 在 alerts.py 用 0.0 表示（约定）。"""
    assert _extract_threshold_value("is_canary=false 计数 ≥ 1", "any") == 0.0


# ============================================================
# _extract_sustain_seconds · 持续文本抽秒数
# ============================================================


def test_sustain_minutes() -> None:
    assert _extract_sustain_seconds("5 分钟") == 300
    assert _extract_sustain_seconds("10 分钟") == 600


def test_sustain_immediate() -> None:
    assert _extract_sustain_seconds("即时（0 秒）") == 0
    assert _extract_sustain_seconds("0 秒") == 0


def test_sustain_unknown_returns_none() -> None:
    assert _extract_sustain_seconds("一会儿") is None


# ============================================================
# parse_alerts_py · AST 解析
# ============================================================


def test_parse_alerts_py_returns_5_alerts() -> None:
    """5 类告警全部解析。"""
    out = parse_alerts_py()
    assert set(out.keys()) == {
        "http_5xx_spike",
        "cascade_fail_high",
        "llm_failure_high",
        "non_canary_traffic",
        "p95_latency_degraded",
    }


def test_parse_alerts_py_p95_uses_baseline_times_multiplier() -> None:
    """P95 阈值 = baseline 8554 × multiplier 3 = 25662（AST 静态计算）。"""
    out = parse_alerts_py()
    assert out["p95_latency_degraded"].threshold_value == 25662.0


def test_parse_alerts_py_p0_alerts() -> None:
    out = parse_alerts_py()
    p0 = [n for n, s in out.items() if s.severity == "P0"]
    assert set(p0) == {"http_5xx_spike", "non_canary_traffic"}


# ============================================================
# parse_adr_0019 · 表格抽取（含数字 alert name）
# ============================================================


def test_parse_adr_0019_includes_p95() -> None:
    """ADR 0019 §1 表必须含 p95_latency_degraded。"""
    out = parse_adr_0019()
    assert "p95_latency_degraded" in out, "ADR 0019 §1 表缺 p95_latency_degraded"


def test_parse_adr_0019_includes_http_5xx() -> None:
    out = parse_adr_0019()
    assert "http_5xx_spike" in out


def test_parse_adr_0019_returns_5_alerts() -> None:
    out = parse_adr_0019()
    assert len(out) == 5


# ============================================================
# parse_runbook · §3 严重等级表
# ============================================================


def test_parse_runbook_extracts_keyword_based_alerts() -> None:
    out = parse_runbook()
    # runbook §3 不含 non_canary_traffic（在 §4 表里）
    assert set(out.keys()) >= {
        "http_5xx_spike", "cascade_fail_high", "llm_failure_high",
    }


def test_parse_runbook_severity_correct() -> None:
    out = parse_runbook()
    assert out["http_5xx_spike"].severity == "P0"
    assert out["cascade_fail_high"].severity == "P1"
    assert out["llm_failure_high"].severity == "P1"


# ============================================================
# compare · 比对算法
# ============================================================


def test_compare_no_diff_when_aligned() -> None:
    a = {"x": AlertSpec("x", "P1", 5.0, 300)}
    b = {"x": AlertSpec("x", "P1", 5.0, 300)}
    assert compare("a", a, "b", b) == []


def test_compare_detects_severity_mismatch() -> None:
    a = {"x": AlertSpec("x", "P0", 5.0, 300)}
    b = {"x": AlertSpec("x", "P1", 5.0, 300)}
    diffs = compare("a", a, "b", b)
    assert len(diffs) == 1
    assert diffs[0].field == "severity"


def test_compare_detects_threshold_mismatch() -> None:
    a = {"x": AlertSpec("x", "P1", 5.0, 300)}
    b = {"x": AlertSpec("x", "P1", 10.0, 300)}
    diffs = compare("a", a, "b", b)
    assert any(d.field == "threshold_value" for d in diffs)


def test_compare_detects_sustain_mismatch() -> None:
    a = {"x": AlertSpec("x", "P1", 5.0, 300)}
    b = {"x": AlertSpec("x", "P1", 5.0, 600)}
    diffs = compare("a", a, "b", b)
    assert any(d.field == "sustain_seconds" for d in diffs)


def test_compare_skips_threshold_via_param() -> None:
    """skip_threshold_value_for 允许 P95 用倍数对比时绕开 ms 检查。"""
    a = {"p95": AlertSpec("p95", "P1", 12600.0, 600)}
    b = {"p95": AlertSpec("p95", "P1", 3.0, 600)}  # runbook 用倍数 3
    diffs = compare("a", a, "b", b, skip_threshold_value_for={"p95"})
    # severity / sustain 一致；threshold_value 被 skip
    assert diffs == []


def test_compare_ignores_alert_only_in_one_source() -> None:
    """只在 a 有的 alert 不报错（runbook §3 不含 non_canary）。"""
    a = {"x": AlertSpec("x", "P1", 5.0, 300), "y": AlertSpec("y", "P0", 0.0, 0)}
    b = {"x": AlertSpec("x", "P1", 5.0, 300)}
    assert compare("a", a, "b", b) == []


# ============================================================
# CLI 主流程
# ============================================================


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, encoding="utf-8", timeout=15,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def test_cli_returns_0_on_current_repo() -> None:
    """当前仓库三处对齐 → exit 0。"""
    r = _run_cli()
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "全部对齐" in r.stdout


def test_cli_json_output_parsable() -> None:
    r = _run_cli("--json")
    assert r.returncode == 0
    payload = json.loads(r.stdout)
    assert payload["ok"] is True
    assert payload["alerts_py_vs_adr_0019"] == []
    assert payload["alerts_py_vs_runbook"] == []


def test_cli_verbose_prints_each_source() -> None:
    r = _run_cli("-v")
    assert r.returncode == 0
    assert "alerts.py" in r.stdout
    assert "ADR 0019" in r.stdout
    assert "runbook" in r.stdout


# ============================================================
# 集成回归 · 真实仓库三处一致性
# ============================================================


def test_integration_alerts_py_vs_adr_0019_aligned() -> None:
    alerts = parse_alerts_py()
    adr = parse_adr_0019()
    diffs = compare("alerts.py", alerts, "ADR 0019", adr)
    assert diffs == [], "\n".join(str(d) for d in diffs)


def test_integration_alerts_py_vs_runbook_aligned() -> None:
    alerts = parse_alerts_py()
    runbook = parse_runbook()
    diffs = compare(
        "alerts.py", alerts, "runbook", runbook,
        skip_threshold_value_for={"p95_latency_degraded"},
    )
    assert diffs == [], "\n".join(str(d) for d in diffs)
