"""Langfuse Remote Experiment webhook 契约。

覆盖三块：签名校验（安全边界）、payload 配置解析、HTTP 触发行为。
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.api import langfuse_webhook
from app.main import app

SECRET = "lf-whsec_" + "a" * 64
URL = "/v1/webhooks/langfuse"


def _sign(body: bytes, *, secret: str = SECRET, timestamp: int | None = None) -> str:
    ts = str(timestamp if timestamp is not None else int(time.time()))
    digest = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


def _settings(*, enabled: bool = True, secret: str = SECRET) -> SimpleNamespace:
    return SimpleNamespace(enable_langfuse_webhook=enabled, langfuse_webhook_secret=secret)


@pytest.fixture(autouse=True)
def _clean_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(langfuse_webhook, "_running", {})


async def _post(*, body: bytes, headers: dict[str, str]) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post(URL, content=body, headers=headers)


# ── 签名校验 ──
class TestVerifySignature:
    def test_accepts_official_scheme(self) -> None:
        body = b'{"datasetId":"d1"}'
        assert langfuse_webhook.verify_signature(
            raw_body=body, header=_sign(body), secret=SECRET
        )

    def test_rejects_tampered_body(self) -> None:
        header = _sign(b'{"datasetId":"d1"}')
        assert not langfuse_webhook.verify_signature(
            raw_body=b'{"datasetId":"d2"}', header=header, secret=SECRET
        )

    def test_rejects_wrong_secret(self) -> None:
        body = b'{"a":1}'
        assert not langfuse_webhook.verify_signature(
            raw_body=body, header=_sign(body, secret="lf-whsec_" + "b" * 64), secret=SECRET
        )

    def test_is_byte_exact(self) -> None:
        """同一份 JSON 重新 dumps（多一个空格）后签名必须失效。"""
        header = _sign(b'{"a": 1}')
        assert not langfuse_webhook.verify_signature(
            raw_body=b'{"a":1}', header=header, secret=SECRET
        )

    @pytest.mark.parametrize(
        "header",
        [
            "",
            "garbage",
            "t=123",  # 缺 v1
            "v1=abc",  # 缺 t
            "t=123,v1=zzzz",  # 非十六进制
            "t=notanumber,v1=" + "a" * 64,
        ],
    )
    def test_rejects_malformed_headers(self, header: str) -> None:
        assert not langfuse_webhook.verify_signature(
            raw_body=b"{}", header=header, secret=SECRET
        )

    def test_rejects_stale_timestamp(self) -> None:
        body = b"{}"
        old = int(time.time()) - langfuse_webhook._SIGNATURE_TOLERANCE_SECONDS - 60
        assert not langfuse_webhook.verify_signature(
            raw_body=body, header=_sign(body, timestamp=old), secret=SECRET
        )


# ── payload 配置 ──
class TestParseConfig:
    def test_accepts_json_string(self) -> None:
        assert langfuse_webhook.parse_config('{"suite":"intent"}') == {"suite": "intent"}

    def test_accepts_object(self) -> None:
        assert langfuse_webhook.parse_config({"suite": "intent"}) == {"suite": "intent"}

    @pytest.mark.parametrize("raw", [None, ""])
    def test_empty_means_no_overrides(self, raw: Any) -> None:
        assert langfuse_webhook.parse_config(raw) == {}

    @pytest.mark.parametrize("raw", ["not json", "[1,2]", 3])
    def test_rejects_non_object(self, raw: Any) -> None:
        with pytest.raises(ValueError):
            langfuse_webhook.parse_config(raw)

    def test_rejects_unknown_key(self) -> None:
        """手写 JSON 的拼写错误必须当场报错，不能静默忽略。"""
        with pytest.raises(ValueError, match="未知字段"):
            langfuse_webhook.parse_config('{"concurrancy": 3}')


# ── 命令行拼装 ──
class TestBuildEvalArgs:
    def test_minimal_args(self) -> None:
        args = langfuse_webhook.build_eval_args(dataset_name="intent/option_inquiry", config={})
        assert args[1:] == ["--dataset", "intent/option_inquiry", "--no-judge"]

    def test_always_disables_judge(self) -> None:
        """ADR 0005：批量评分只用确定性断言，不调用 LLM Judge。"""
        for config in ({}, {"suite": "business"}, {"concurrency": 3}):
            assert "--no-judge" in langfuse_webhook.build_eval_args(
                dataset_name="biz/option_inquiry", config=config
            )

    def test_full_config(self) -> None:
        args = langfuse_webhook.build_eval_args(
            dataset_name="intent/option_inquiry",
            config={"suite": "intent", "ids": ["a", "b"], "limit": 5, "concurrency": 3},
        )
        assert args[1:] == [
            "--dataset", "intent/option_inquiry",
            "--suite", "intent",
            "--ids", "a,b",
            "--limit", "5",
            "--concurrency", "3",
            "--no-judge",
        ]

    def test_empty_ids_omitted(self) -> None:
        args = langfuse_webhook.build_eval_args(dataset_name="d", config={"ids": []})
        assert "--ids" not in args

    @pytest.mark.parametrize(
        "config",
        [
            {"suite": "wrong"},
            {"ids": "a,b"},  # 必须是数组
            {"ids": [1]},
            {"limit": 0},
            {"concurrency": -1},
            {"concurrency": True},  # bool 是 int 子类，不能当数字
            {"concurrency": "3"},
        ],
    )
    def test_rejects_invalid_values(self, config: dict[str, Any]) -> None:
        with pytest.raises(ValueError):
            langfuse_webhook.build_eval_args(dataset_name="d", config=config)


# ── HTTP 触发 ──
class _FakeProc:
    pid = 4242

    def wait(self) -> int:
        return 0


@pytest.fixture
def spawned(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_spawn(*, args: list[str], dataset_name: str) -> tuple[_FakeProc, Path]:
        calls.append(args)
        return _FakeProc(), Path("tmp/fake.log")

    monkeypatch.setattr(langfuse_webhook, "_spawn", fake_spawn)
    return calls


async def test_disabled_returns_404(
    monkeypatch: pytest.MonkeyPatch, spawned: list[list[str]]
) -> None:
    monkeypatch.setattr(
        langfuse_webhook, "get_settings", lambda: _settings(enabled=False)
    )
    body = json.dumps({"datasetName": "d"}).encode()
    response = await _post(body=body, headers={"x-langfuse-signature": _sign(body)})
    assert response.status_code == 404
    assert spawned == []


async def test_missing_secret_returns_503(
    monkeypatch: pytest.MonkeyPatch, spawned: list[list[str]]
) -> None:
    monkeypatch.setattr(langfuse_webhook, "get_settings", lambda: _settings(secret=""))
    body = json.dumps({"datasetName": "d"}).encode()
    response = await _post(body=body, headers={"x-langfuse-signature": _sign(body)})
    assert response.status_code == 503
    assert spawned == []


async def test_bad_signature_returns_401(
    monkeypatch: pytest.MonkeyPatch, spawned: list[list[str]]
) -> None:
    monkeypatch.setattr(langfuse_webhook, "get_settings", lambda: _settings())
    body = json.dumps({"datasetName": "d"}).encode()
    response = await _post(body=body, headers={"x-langfuse-signature": "t=1,v1=deadbeef"})
    assert response.status_code == 401
    assert spawned == []


async def test_missing_signature_header_returns_401(
    monkeypatch: pytest.MonkeyPatch, spawned: list[list[str]]
) -> None:
    monkeypatch.setattr(langfuse_webhook, "get_settings", lambda: _settings())
    body = json.dumps({"datasetName": "d"}).encode()
    response = await _post(body=body, headers={})
    assert response.status_code == 401
    assert spawned == []


async def test_accepts_and_spawns_child_process(
    monkeypatch: pytest.MonkeyPatch, spawned: list[list[str]]
) -> None:
    monkeypatch.setattr(langfuse_webhook, "get_settings", lambda: _settings())
    body = json.dumps(
        {"datasetName": "intent/option_inquiry", "payload": '{"suite":"intent","concurrency":2}'}
    ).encode()
    response = await _post(body=body, headers={"x-langfuse-signature": _sign(body)})

    assert response.status_code == 202, response.text
    assert response.json()["pid"] == 4242
    assert spawned == [[
        str(langfuse_webhook._EVAL_SCRIPT),
        "--dataset", "intent/option_inquiry",
        "--suite", "intent",
        "--concurrency", "2",
        "--no-judge",
    ]]


async def test_rejects_bad_config_with_400(
    monkeypatch: pytest.MonkeyPatch, spawned: list[list[str]]
) -> None:
    monkeypatch.setattr(langfuse_webhook, "get_settings", lambda: _settings())
    body = json.dumps({"datasetName": "d", "payload": '{"suite":"nope"}'}).encode()
    response = await _post(body=body, headers={"x-langfuse-signature": _sign(body)})
    assert response.status_code == 400
    assert spawned == []


async def test_missing_dataset_name_returns_400(
    monkeypatch: pytest.MonkeyPatch, spawned: list[list[str]]
) -> None:
    monkeypatch.setattr(langfuse_webhook, "get_settings", lambda: _settings())
    body = json.dumps({"projectId": "p1"}).encode()
    response = await _post(body=body, headers={"x-langfuse-signature": _sign(body)})
    assert response.status_code == 400
    assert spawned == []


async def test_conflict_when_same_dataset_running(
    monkeypatch: pytest.MonkeyPatch, spawned: list[list[str]]
) -> None:
    monkeypatch.setattr(langfuse_webhook, "get_settings", lambda: _settings())
    blocker = asyncio.Event()
    in_flight: asyncio.Task[Any] = asyncio.create_task(blocker.wait())
    langfuse_webhook._running["intent/option_inquiry"] = in_flight
    try:
        body = json.dumps({"datasetName": "intent/option_inquiry"}).encode()
        response = await _post(body=body, headers={"x-langfuse-signature": _sign(body)})
        assert response.status_code == 409
        assert spawned == []
    finally:
        blocker.set()
        await in_flight
