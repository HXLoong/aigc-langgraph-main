"""D2.6 health_probes 内部 _check 测试 · 把 32% 覆盖率拉到 ~85%。

之前 test_health_probes.py 覆盖了 /health /ready 路由 + run_all_probes 聚合，
但 4 个 probe 内部的真实 IO 路径（aiomysql / httpx）全部用 stub_probe 替换，
导致 _check 内部代码（51-67 / 81-91 / 103-121 / 134-151 行）覆盖率 0。

F4.0 演练 /ready 准确性依赖 _check 行为正确——本文件用细粒度 mock 补齐。

Mock 策略：
  - aiomysql.connect: AsyncMock，返回 mock connection 支持 cursor + execute
  - httpx.AsyncClient: AsyncMock 上下文管理器，c.get 返回 mock Response
  - app.config.get_settings: 替换为 SimpleNamespace，按测试场景定制
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.observability import health_probes as hp

# ============================================================
# Settings fake helpers
# ============================================================


def _fake_settings(**overrides) -> SimpleNamespace:
    """构造 settings stub。默认所有 probe 都"已配置"（待 _check 真跑）。"""
    base = {
        "checkpoint_mysql_uri": "mysql://user:pw@127.0.0.1:3306/test_db",
        "enable_langfuse": True,
        "langfuse_base_url": "http://langfuse:3000",
        "qwen_api_base": "http://qwen:8000/v1",
        "qwen_api_key": "sk-test",
        "otc_api_base_url": "http://java:8080",
        "otc_api_secret": "secret-token",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ============================================================
# probe_mysql · aiomysql mock
# ============================================================


def _mock_aiomysql_connect_success():
    """构造 await aiomysql.connect(...) → mock_conn 链。"""
    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.fetchone = AsyncMock(return_value=(1,))
    cursor.__aenter__ = AsyncMock(return_value=cursor)
    cursor.__aexit__ = AsyncMock(return_value=None)

    conn = MagicMock()
    conn.cursor = MagicMock(return_value=cursor)
    conn.close = MagicMock()
    return AsyncMock(return_value=conn)


@pytest.mark.asyncio
async def test_probe_mysql_ok() -> None:
    fake = _fake_settings()
    mock_connect = _mock_aiomysql_connect_success()
    with (
        patch("app.config.get_settings", return_value=fake),
        patch("aiomysql.connect", mock_connect),
    ):
        result = await hp.probe_mysql()
    assert result.target == "mysql"
    assert result.status == "ok"
    assert result.latency_ms is not None
    mock_connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_probe_mysql_no_uri_returns_fail() -> None:
    """checkpoint_mysql_uri 空 → RuntimeError('no_uri') → fail。"""
    fake = _fake_settings(checkpoint_mysql_uri="")
    with patch("app.config.get_settings", return_value=fake):
        result = await hp.probe_mysql()
    assert result.status == "fail"
    assert result.error == "RuntimeError"


@pytest.mark.asyncio
async def test_probe_mysql_connection_refused_returns_fail() -> None:
    fake = _fake_settings()
    mock_connect = AsyncMock(side_effect=ConnectionRefusedError("refused"))
    with (
        patch("app.config.get_settings", return_value=fake),
        patch("aiomysql.connect", mock_connect),
    ):
        result = await hp.probe_mysql()
    assert result.status == "fail"
    assert result.error == "ConnectionRefusedError"


# ============================================================
# probe_langfuse · httpx mock
# ============================================================


def _patch_httpx_client(mock_response: httpx.Response) -> MagicMock:
    """构造 async with httpx.AsyncClient(...) as c: c.get(...) → mock_response。"""
    c = MagicMock()
    c.get = AsyncMock(return_value=mock_response)
    c.__aenter__ = AsyncMock(return_value=c)
    c.__aexit__ = AsyncMock(return_value=None)
    return MagicMock(return_value=c)


@pytest.mark.asyncio
async def test_probe_langfuse_disabled_when_flag_false() -> None:
    fake = _fake_settings(enable_langfuse=False)
    with patch("app.config.get_settings", return_value=fake):
        result = await hp.probe_langfuse()
    assert result.status == "disabled"
    assert result.target == "langfuse"


@pytest.mark.asyncio
async def test_probe_langfuse_ok_on_200() -> None:
    fake = _fake_settings()
    mock_resp = httpx.Response(200, json={"status": "OK"})
    client_factory = _patch_httpx_client(mock_resp)
    with (
        patch("app.config.get_settings", return_value=fake),
        patch("httpx.AsyncClient", client_factory),
    ):
        result = await hp.probe_langfuse()
    assert result.status == "ok"


@pytest.mark.asyncio
async def test_probe_langfuse_ok_on_4xx() -> None:
    """4xx 不算 fail —— probe 只关心 endpoint 是否活着（5xx 才 fail）。"""
    fake = _fake_settings()
    mock_resp = httpx.Response(404)
    client_factory = _patch_httpx_client(mock_resp)
    with (
        patch("app.config.get_settings", return_value=fake),
        patch("httpx.AsyncClient", client_factory),
    ):
        result = await hp.probe_langfuse()
    assert result.status == "ok"


@pytest.mark.asyncio
async def test_probe_langfuse_fail_on_500() -> None:
    fake = _fake_settings()
    mock_resp = httpx.Response(500)
    client_factory = _patch_httpx_client(mock_resp)
    with (
        patch("app.config.get_settings", return_value=fake),
        patch("httpx.AsyncClient", client_factory),
    ):
        result = await hp.probe_langfuse()
    assert result.status == "fail"
    assert result.error == "RuntimeError"


# ============================================================
# probe_llm · httpx mock + 鉴权语义
# ============================================================


@pytest.mark.asyncio
async def test_probe_llm_disabled_when_no_base() -> None:
    fake = _fake_settings(qwen_api_base="")
    with patch("app.config.get_settings", return_value=fake):
        result = await hp.probe_llm()
    assert result.status == "disabled"


@pytest.mark.asyncio
async def test_probe_llm_ok_with_bearer() -> None:
    """有 api_key → 应带 Authorization Bearer 头去探 /models。"""
    fake = _fake_settings()
    mock_resp = httpx.Response(200, json={"data": []})
    client_factory = _patch_httpx_client(mock_resp)
    with (
        patch("app.config.get_settings", return_value=fake),
        patch("httpx.AsyncClient", client_factory),
    ):
        result = await hp.probe_llm()
    assert result.status == "ok"
    # 验证 Authorization 头
    inst = client_factory.return_value
    inst.get.assert_awaited_once()
    call_args = inst.get.call_args
    headers = call_args.kwargs.get("headers") or {}
    assert headers.get("Authorization", "").startswith("Bearer ")


@pytest.mark.asyncio
async def test_probe_llm_ok_without_api_key() -> None:
    """没 api_key 时 → headers=None，仍发请求"""
    fake = _fake_settings(qwen_api_key="")
    mock_resp = httpx.Response(200)
    client_factory = _patch_httpx_client(mock_resp)
    with (
        patch("app.config.get_settings", return_value=fake),
        patch("httpx.AsyncClient", client_factory),
    ):
        result = await hp.probe_llm()
    assert result.status == "ok"


@pytest.mark.asyncio
async def test_probe_llm_401_returns_fail() -> None:
    """401 = key 失效 → fail 区分 endpoint 可达但鉴权坏。"""
    fake = _fake_settings()
    mock_resp = httpx.Response(401, json={"error": "invalid_key"})
    client_factory = _patch_httpx_client(mock_resp)
    with (
        patch("app.config.get_settings", return_value=fake),
        patch("httpx.AsyncClient", client_factory),
    ):
        result = await hp.probe_llm()
    assert result.status == "fail"
    assert result.error == "RuntimeError"


@pytest.mark.asyncio
async def test_probe_llm_5xx_returns_fail() -> None:
    fake = _fake_settings()
    mock_resp = httpx.Response(503)
    client_factory = _patch_httpx_client(mock_resp)
    with (
        patch("app.config.get_settings", return_value=fake),
        patch("httpx.AsyncClient", client_factory),
    ):
        result = await hp.probe_llm()
    assert result.status == "fail"


# ============================================================
# probe_java_backend · httpx mock + envelope 校验
# ============================================================


@pytest.mark.asyncio
async def test_probe_java_backend_disabled_when_no_base() -> None:
    fake = _fake_settings(otc_api_base_url="")
    with patch("app.config.get_settings", return_value=fake):
        result = await hp.probe_java_backend()
    assert result.status == "disabled"


@pytest.mark.asyncio
async def test_probe_java_backend_ok_with_proper_envelope() -> None:
    """合法 envelope {code, data}。"""
    fake = _fake_settings()
    mock_resp = httpx.Response(200, json={"code": 0, "data": "prompt..."})
    client_factory = _patch_httpx_client(mock_resp)
    with (
        patch("app.config.get_settings", return_value=fake),
        patch("app.tools.auth.get_goats_auth_headers", return_value={"X-Goats": "test"}),
        patch("httpx.AsyncClient", client_factory),
    ):
        result = await hp.probe_java_backend()
    assert result.status == "ok"


@pytest.mark.asyncio
async def test_probe_java_backend_fail_on_5xx() -> None:
    fake = _fake_settings()
    mock_resp = httpx.Response(502)
    client_factory = _patch_httpx_client(mock_resp)
    with (
        patch("app.config.get_settings", return_value=fake),
        patch("app.tools.auth.get_goats_auth_headers", return_value={}),
        patch("httpx.AsyncClient", client_factory),
    ):
        result = await hp.probe_java_backend()
    assert result.status == "fail"


@pytest.mark.asyncio
async def test_probe_java_backend_fail_on_bad_envelope() -> None:
    """200 但响应不含 `code` → bad_envelope（防 mock 服务伪装健康）。"""
    fake = _fake_settings()
    mock_resp = httpx.Response(200, json={"unexpected": "shape"})
    client_factory = _patch_httpx_client(mock_resp)
    with (
        patch("app.config.get_settings", return_value=fake),
        patch("app.tools.auth.get_goats_auth_headers", return_value={}),
        patch("httpx.AsyncClient", client_factory),
    ):
        result = await hp.probe_java_backend()
    assert result.status == "fail"
    assert result.error == "RuntimeError"


@pytest.mark.asyncio
async def test_probe_java_backend_uses_goats_auth_headers() -> None:
    """GOATS 鉴权头被合并到请求 headers。"""
    fake = _fake_settings()
    mock_resp = httpx.Response(200, json={"code": 0})
    client_factory = _patch_httpx_client(mock_resp)
    with (
        patch("app.config.get_settings", return_value=fake),
        patch(
            "app.tools.auth.get_goats_auth_headers",
            return_value={"X-Sub": "1688x", "X-Agent": "10821x"},
        ),
        patch("httpx.AsyncClient", client_factory),
    ):
        await hp.probe_java_backend()
    inst = client_factory.return_value
    headers = inst.get.call_args.kwargs.get("headers") or {}
    assert headers.get("X-Sub") == "1688x"
    assert headers.get("X-Agent") == "10821x"


# ============================================================
# run_all_probes · 整体超时降级
# ============================================================


@pytest.mark.asyncio
async def test_run_all_probes_total_timeout_returns_4_fails(monkeypatch) -> None:
    """整体 timeout > READY_TOTAL_TIMEOUT_SECONDS → 4 个 ProbeResult 全 fail。"""
    monkeypatch.setattr(hp, "READY_TOTAL_TIMEOUT_SECONDS", 0.05)

    async def _hang() -> hp.ProbeResult:
        import asyncio
        await asyncio.sleep(10)
        return hp.ProbeResult(target="mysql", status="ok")  # 不会到这里

    with (
        patch.object(hp, "probe_mysql", _hang),
        patch.object(hp, "probe_langfuse", _hang),
        patch.object(hp, "probe_llm", _hang),
        patch.object(hp, "probe_java_backend", _hang),
    ):
        results = await hp.run_all_probes()

    assert len(results) == 4
    assert all(r.status == "fail" for r in results)
    assert all(r.error == "total_timeout" for r in results)
    assert {r.target for r in results} == {
        "mysql", "langfuse", "llm", "java_backend",
    }


@pytest.mark.asyncio
async def test_probe_mysql_uses_saver_pool_when_checkpointer_initialized(monkeypatch) -> None:
    """ADR 0024 D4：saver 已接线时探针走 factory.probe_checkpointer（探的是 saver 自己的池），
    绝不另开新连接——否则 saver 连接已死 /ready 仍会返回 ok。"""
    from unittest.mock import AsyncMock

    import app.checkpointer.factory as factory

    monkeypatch.setattr(factory, "_pool", object())
    probe = AsyncMock()
    monkeypatch.setattr(factory, "probe_checkpointer", probe)

    def _no_connect(*_a, **_k):  # type: ignore[no-untyped-def]
        raise AssertionError("不应另开 aiomysql 连接")

    with patch("aiomysql.connect", _no_connect):
        result = await hp.probe_mysql()
    assert result.status == "ok"
    probe.assert_awaited_once()
