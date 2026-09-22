"""PR 检查必须自动运行、隔离真实依赖，并如实报告失败。"""
from pathlib import Path
from urllib.parse import urlsplit

import yaml


def workflow():
    # BaseLoader 保留 GitHub Actions 的 on 键，不按 YAML 1.1 转为布尔值。
    return yaml.load(Path(".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader)


def test_ci_runs_for_pull_requests_and_manual_dispatch():
    assert {"pull_request", "workflow_dispatch"} <= set(workflow()["on"])


def test_ci_uses_explicit_offline_settings():
    env = workflow()["jobs"]["test"]["env"]
    for key in ("ENABLE_LANGFUSE", "USE_MYSQL_CHECKPOINTER", "REQUEST_IDEMPOTENCY"):
        assert env.get(key) == "false", key
    for key in ("MYSQL_URI", "QWEN_API_BASE", "OTC_API_BASE_URL"):
        assert urlsplit(env.get(key, "")).hostname == "127.0.0.1", key
    for key in ("QWEN_API_KEY", "OTC_API_SECRET"):
        assert env.get(key) == "ci-placeholder", key


def test_required_checks_do_not_swallow_failures():
    steps = workflow()["jobs"]["test"]["steps"]
    for command in (
        "ruff check app/ tests/", "pytest tests/",
        "mypy app/ harness/",
        "scripts/check_alert_threshold_consistency.py",
        "scripts/check_fixture_consistency.py", "scripts/check_adr_refs.py",
        "scripts/sync_agents_md.py --check",
    ):
        selected = [step for step in steps if command in step.get("run", "")]
        assert len(selected) == 1, command
        step = selected[0]
        assert "||" not in step["run"] and "if [" not in step["run"]
        assert step.get("continue-on-error", "false") == "false"
    assert workflow()["jobs"]["test"].get("continue-on-error", "false") == "false"
