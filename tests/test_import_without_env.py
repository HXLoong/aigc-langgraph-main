"""导入卫生：应用与图模块必须能在没有任何配置的环境里被 import。

`.claude/rules/testing.md`："所有测试必须 import 时能成功（不联网、不依赖真实 MySQL）"。
模块级 `get_settings()` 会让 import 时就要求 5 个必填环境变量，导致无 `.env` 的
CI / 新人环境里几十个测试文件收集失败。本测试在干净子进程（无 .env、无业务环境变量）
里导入关键模块，把这条纪律钉成契约。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# 只保留解释器能跑起来的最小环境；业务变量一律不带
_CLEAN_ENV_KEYS = ("PATH", "SYSTEMROOT", "PYTHONIOENCODING", "LANG", "LC_ALL", "HOME")


@pytest.mark.parametrize(
    "module",
    ["app.nodes.render", "app.graph.main", "app.node_execution.registry", "app.main"],
)
def test_module_imports_without_any_settings(tmp_path: Path, module: str) -> None:
    env = {key: os.environ[key] for key in _CLEAN_ENV_KEYS if key in os.environ}
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PYTHONUTF8"] = "1"
    # cwd 指向空目录：pydantic-settings 的 env_file=".env" 相对 cwd 解析，确保读不到仓库 .env
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
