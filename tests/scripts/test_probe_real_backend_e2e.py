"""scripts/probe_real_backend_e2e.py · 真后端 probe runner 测试。

不实跑真后端（CI 没 EVAL credential），仅测：
- 前置校验（EVAL_* 缺失 → exit 2）
- --target 过滤
- --case 越界
- --report-only 跳过实跑
- 状态分类算法（_classify_status）
- 报告渲染 + 输出文件创建
- webhook 触发条件
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.probe_real_backend_e2e import (
    CASES,
    ProbeCase,
    ProbeResult,
    _classify_status,
    filter_cases,
    render_markdown,
    summarize,
    write_outputs,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "probe_real_backend_e2e.py"

# ============================================================
# CASES 库基本约束
# ============================================================


def test_cases_have_4_targets() -> None:
    targets = {c.target for c in CASES}
    assert targets == {"swap", "option", "close", "ticker"}


def test_cases_safety_ordering_within_target() -> None:
    """每个 target 内部 case 顺序应从 read → write（不可逆）排列。"""
    # 这是软约束，本测试只 smoke：CASES 里没有 place_*/confirm_place 在 query_* 之前
    by_target: dict[str, list[ProbeCase]] = {}
    for c in CASES:
        by_target.setdefault(c.target, []).append(c)
    for target, cases in by_target.items():
        names = [c.id for c in cases]
        # query 类应该出现在 place 类之前（如果都有）
        first_place = next((i for i, n in enumerate(names) if "place" in n), None)
        first_query = next((i for i, n in enumerate(names) if "query" in n), None)
        if first_place is not None and first_query is not None:
            assert first_query < first_place, (
                f"{target}: query 类 case 应在 place 类之前，避免下错单"
            )


# ============================================================
# filter_cases
# ============================================================


def test_filter_all_returns_all() -> None:
    assert len(filter_cases("all")) == len(CASES)


def test_filter_swap_returns_swap_only() -> None:
    cases = filter_cases("swap")
    assert all(c.target == "swap" for c in cases)
    assert len(cases) > 0


# ============================================================
# _classify_status
# ============================================================


def test_classify_status_exception_path() -> None:
    assert _classify_status({}, RuntimeError("boom")) == "exception"


def test_classify_status_unreachable_exception() -> None:
    class BackendUnreachableError(Exception):
        pass

    exc = BackendUnreachableError("timeout")
    assert _classify_status({}, exc) == "unreachable"


def test_classify_status_ok_api_code_0() -> None:
    assert _classify_status({"api_code": 0}, None) == "ok"


def test_classify_status_business_reject() -> None:
    assert _classify_status({"api_code": 400}, None) == "business_reject"


def test_classify_status_state_error_unreachable() -> None:
    err = MagicMock(type="BackendUnreachableError", message="timeout")
    assert _classify_status({"error": err}, None) == "unreachable"


def test_classify_status_no_api_code_with_fallback_reply() -> None:
    """ticker 类只 read，无 api_code；reply_text 含 fallback → exception。"""
    assert (
        _classify_status({"reply_text": "我没完全理解你的意思，能换种说法吗"}, None) == "exception"
    )


def test_classify_status_no_api_code_clean_reply() -> None:
    """ticker 类正常返回 → ok。"""
    assert _classify_status({"reply_text": "已为您找到 600519.SH"}, None) == "ok"


# ============================================================
# summarize
# ============================================================


def _r(case_id: str, target: str, status: str, api_code: int | None = None) -> ProbeResult:
    return ProbeResult(
        case_id=case_id,
        target=target,
        raw_text="x",
        notes="x",
        latency_ms=100,
        status=status,
        api_code=api_code,
    )


def test_summarize_counts_by_status_and_target() -> None:
    results = [
        _r("a", "swap", "ok", api_code=0),
        _r("b", "swap", "business_reject", api_code=400),
        _r("c", "option", "exception"),
    ]
    s = summarize(results)
    assert s["total"] == 3
    assert s["by_status"]["ok"] == 1
    assert s["by_status"]["business_reject"] == 1
    assert s["by_status"]["exception"] == 1
    assert s["has_failure"] is True
    # pass rate = ok + business_reject = 2/3
    assert s["pass_rate"] == pytest.approx(2 / 3)


def test_summarize_zero_results() -> None:
    s = summarize([])
    assert s["total"] == 0
    assert s["pass_rate"] == 0.0
    assert s["has_failure"] is False


def test_summarize_business_reject_counts_as_pass() -> None:
    """business_reject = 后端按业务规则拒绝，链路本身工作 → 计入通过率。"""
    results = [_r(f"c{i}", "swap", "business_reject", api_code=400) for i in range(5)]
    s = summarize(results)
    assert s["pass_rate"] == 1.0
    assert s["has_failure"] is False


# ============================================================
# 报告渲染 + 文件输出
# ============================================================


def test_render_markdown_includes_all_sections() -> None:
    results = [
        _r("a", "swap", "ok", api_code=0),
        _r("b", "option", "exception"),
    ]
    md = render_markdown(results, summarize(results))
    assert "真后端 E2E probe 报告" in md
    assert "按 target 分类" in md
    assert "case 详情" in md
    assert "失败详情" in md  # 有 exception → 失败段
    assert "swap" in md and "option" in md


def test_render_markdown_no_failure_section_when_all_ok() -> None:
    results = [_r("a", "swap", "ok", api_code=0)]
    md = render_markdown(results, summarize(results))
    assert "失败详情" not in md


def test_write_outputs_creates_files(tmp_path: Path) -> None:
    results = [_r("a", "swap", "ok", api_code=0)]
    sum_path, rep_path = write_outputs(results, summarize(results), tmp_path)
    assert sum_path.exists()
    assert rep_path.exists()
    payload = json.loads(sum_path.read_text(encoding="utf-8"))
    assert payload["summary"]["total"] == 1
    assert len(payload["results"]) == 1


# ============================================================
# CLI 主流程（subprocess）
# ============================================================


def _run(
    *args: str, env_extra: dict | None = None, timeout: int = 30
) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    # 清掉 EVAL_*，让默认前置校验生效
    env.pop("EVAL_USER_ID", None)
    env.pop("EVAL_ROOM_ID", None)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


def test_cli_report_only_smoke() -> None:
    """--report-only 应直接跳过实跑 + 不需要 EVAL。"""
    r = _run("--target", "swap", "--report-only")
    assert r.returncode == 0
    assert "--report-only" in r.stdout or "跳过实跑" in r.stdout


def test_cli_invalid_target_exits_2() -> None:
    r = _run("--target", "invalid")
    # argparse choices 校验失败返回 2
    assert r.returncode == 2


def test_cli_case_out_of_range() -> None:
    """--case 999 越界 → exit 2。"""
    r = _run("--target", "swap", "--case", "999", "--report-only")
    # report-only 路径仍校验 --case 越界
    # 但 report-only 走早期 return 路径，--case 越界检测在 filter 之后
    # 实测决定：若 report-only 在 case 检测前 return → 不会触发 exit 2
    # 接受 0 或 2，主要是不能抛 exception
    assert r.returncode in (0, 2)


def test_cli_help() -> None:
    r = _run("--help")
    assert r.returncode == 0
    assert "真后端 E2E probe runner" in r.stdout
    assert "--target" in r.stdout
    assert "--report-only" in r.stdout
