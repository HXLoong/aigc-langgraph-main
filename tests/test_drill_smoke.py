"""scripts/drill_smoke.sh · F4.0 演练 smoke 脚本测试。

测试范围：
- 参数解析（--help / 未知参数）
- 6 件套工具存在性 check（重命名/删除任一工具 → fail）
- 工具语法 check（注入语法错误的临时脚本 → fail）
- 服务未启动场景（metrics/ready 不可达 → 多项 fail，整体 exit 1）
- --skip-deploy-check 行为
- --json 输出可解析

不测：
- 真实服务启动场景（覆盖太广，留给 m3-f4.0-oncall-drill.md 真演练）
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "drill_smoke.sh"


def _run(
    *args: str, cwd: Path | None = None, timeout: int = 30,
    project_dir: Path | None = None,
) -> subprocess.CompletedProcess:
    env = {**os.environ}
    if project_dir is not None:
        env["PROJECT_DIR"] = str(project_dir)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=cwd or ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _extract_json(stdout: str) -> dict:
    """从混合输出里抓 JSON 块（脚本在末尾打印 \\n{...}\\n}）。"""
    # JSON 块以 "\n{\n" 开头（顶级对象）
    idx = stdout.rfind("\n{\n")
    if idx < 0:
        raise AssertionError(f"未找到 JSON 块: tail={stdout[-300:]!r}")
    return json.loads(stdout[idx + 1:])


# ============================================================
# 参数解析
# ============================================================


def test_help_prints_usage() -> None:
    r = _run("--help")
    assert r.returncode == 0
    assert "F4.0 演练" in r.stdout
    assert "--metrics-url" in r.stdout
    assert "--skip-deploy-check" in r.stdout


def test_unknown_arg_exits_2() -> None:
    r = _run("--bogus")
    assert r.returncode == 2


# ============================================================
# 真跑（服务未启动）· skip-deploy 路径
# ============================================================


def test_runs_without_service_returns_1() -> None:
    """服务未启动时，前 2 项 pass，后 3 项 fail，整体 exit 1。"""
    r = _run("--skip-deploy-check", "--metrics-url", "http://127.0.0.1:1/nope",
             "--ready-url", "http://127.0.0.1:1/nope")
    assert r.returncode == 1
    # 工具存在 + 语法应通过
    assert "6 件套工具存在" in r.stdout
    assert "工具语法可加载" in r.stdout
    # 服务相关应失败
    assert "不可达" in r.stdout or "fail" in r.stdout.lower() or "❌" in r.stdout


def test_json_output_is_parsable() -> None:
    r = _run("--skip-deploy-check", "--json",
             "--metrics-url", "http://127.0.0.1:1/nope",
             "--ready-url", "http://127.0.0.1:1/nope")
    payload = _extract_json(r.stdout)
    assert payload["total"] == 6
    assert payload["passed"] >= 2
    assert payload["failed"] >= 1
    assert isinstance(payload["checks"], list)
    assert len(payload["checks"]) == 6
    # 每个 check 项必有这 3 个字段
    for chk in payload["checks"]:
        assert set(chk.keys()) == {"name", "status", "detail"}


def test_skip_deploy_check_emits_warn() -> None:
    r = _run("--skip-deploy-check",
             "--metrics-url", "http://127.0.0.1:1/nope",
             "--ready-url", "http://127.0.0.1:1/nope")
    assert "跳过" in r.stdout or "skip" in r.stdout.lower()


# ============================================================
# 工具缺失场景 · 复制项目到 tmp 删工具
# ============================================================


def _make_minimal_project(tmp_path: Path) -> Path:
    """造一个最小可跑的项目副本：只复制 scripts/ + infra/grafana/ + .env。"""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "infra" / "grafana" / "dashboards").mkdir(parents=True)
    # 复制所有 scripts + dashboard
    for f in (ROOT / "scripts").glob("*"):
        if f.is_file():
            shutil.copy(f, tmp_path / "scripts" / f.name)
    shutil.copy(
        ROOT / "infra/grafana/dashboards/otc-agent-overview.json",
        tmp_path / "infra/grafana/dashboards/otc-agent-overview.json",
    )
    return tmp_path


def test_missing_tool_fails_check(tmp_path: Path) -> None:
    """删掉 rollback_canary.sh → Check 1 应失败。"""
    proj = _make_minimal_project(tmp_path)
    (proj / "scripts" / "rollback_canary.sh").unlink()

    r = _run("--skip-deploy-check",
             "--metrics-url", "http://127.0.0.1:1/nope",
             "--ready-url", "http://127.0.0.1:1/nope",
             project_dir=proj)
    assert r.returncode == 1
    assert "rollback_canary.sh" in r.stdout
    assert "缺失" in r.stdout or "fail" in r.stdout.lower()


def test_missing_grafana_dashboard_fails(tmp_path: Path) -> None:
    proj = _make_minimal_project(tmp_path)
    (proj / "infra/grafana/dashboards/otc-agent-overview.json").unlink()

    r = _run("--skip-deploy-check",
             "--metrics-url", "http://127.0.0.1:1/nope",
             "--ready-url", "http://127.0.0.1:1/nope",
             project_dir=proj)
    assert r.returncode == 1
    assert "otc-agent-overview.json" in r.stdout


# ============================================================
# 工具语法错误场景
# ============================================================


def test_syntax_error_in_shell_tool_fails(tmp_path: Path) -> None:
    """注入语法错的 rollback_canary.sh → Check 2 应失败。"""
    proj = _make_minimal_project(tmp_path)
    # 用错误语法覆盖
    (proj / "scripts" / "rollback_canary.sh").write_text(
        "#!/usr/bin/env bash\nif [ unclosed\n", encoding="utf-8"
    )

    r = _run("--skip-deploy-check",
             "--metrics-url", "http://127.0.0.1:1/nope",
             "--ready-url", "http://127.0.0.1:1/nope",
             project_dir=proj)
    assert r.returncode == 1
    assert "工具语法可加载" in r.stdout
    # 应能定位到哪个文件
    assert "rollback_canary.sh" in r.stdout
