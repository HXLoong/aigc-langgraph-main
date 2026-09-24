"""LangFuse 只允许自托管部署（ADR 0014）：代码里不得写死 LangFuse Cloud 主机作为默认值。"""
from __future__ import annotations

from pathlib import Path

from app.config import Settings

ROOT = Path(__file__).resolve().parents[1]
CLOUD_HOST = "cloud.langfuse.com"
SELF_HOSTED_DEFAULT = "http://127.0.0.1:3000"


def test_settings_default_points_to_self_hosted_instance() -> None:
    assert Settings.model_fields["langfuse_base_url"].default == SELF_HOSTED_DEFAULT


def test_code_has_no_hardcoded_langfuse_cloud_host() -> None:
    offenders = [
        f"{path.relative_to(ROOT)}:{lineno}"
        for top in ("app", "scripts", "harness")
        for path in sorted((ROOT / top).rglob("*.py"))
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if CLOUD_HOST in line
    ]
    assert offenders == []
