"""scripts/probe_goats 探针的两条安全线：凭据不进代码、写类接口默认拒绝。"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts.probe_goats import _utils

PROBE_DIR = Path(__file__).resolve().parents[1] / "scripts" / "probe_goats"
# 明文地址 / 凭据 / agent id 的特征：内网域名、疑似 secret 赋值、"数字@tl" 形态的 agent id
_PLAINTEXT_RX = re.compile(
    r"https?://[a-z0-9.-]+\.(?:gf\.com\.cn|local)|"
    r"^(?:CLIENT_SECRET|SALT|BASE_URL)\s*=\s*['\"][^'\"]+['\"]|"
    r"['\"]\d{6,}@tl['\"]",
    re.M,
)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/internal/agent/trs/order", True),
        ("/api/internal/agent/option/order/close/withdraw", True),
        ("/api/internal/agent/trs/order/replace", True),
        ("/api/internal/agent/option/order/query", False),
        ("/api/internal/agent/trs/order/status", False),
        ("/api/internal/agent/trs/order/replaceResults", False),
        ("/api/internal/agent/get_option_rfq", False),
        ("/api/uniweb/rpa/trs/tradingHoursConfig", False),
    ],
)
def test_write_paths_are_recognised(path: str, expected: bool) -> None:
    assert _utils.is_write(path) is expected


def test_write_probe_is_refused_before_any_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_utils, "_require_config", lambda: None)
    monkeypatch.setattr(_utils, "write_confirmed", lambda: False)
    monkeypatch.setattr(
        _utils.httpx, "post", lambda *a, **k: pytest.fail("写类探针未确认时不得发出 HTTP")
    )
    with pytest.raises(SystemExit, match="SKIP-WRITE"):
        _utils.post("/api/internal/agent/trs/order", {}, "aid", "sub")


def test_missing_config_is_reported_not_defaulted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_utils, "config", lambda name: "")
    with pytest.raises(SystemExit, match="GOATS_BASE_URL"):
        _utils.get("/api/internal/agent/get_option_rfq", {}, "aid", "sub")


def test_probe_sources_contain_no_plaintext_credentials() -> None:
    offenders = [
        f"{path.name}: {match.group(0)}"
        for path in PROBE_DIR.glob("*.py")
        for match in _PLAINTEXT_RX.finditer(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], offenders
