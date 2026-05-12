"""D2.5 动态 prompt 指标埋点测试（ADR 0013 / Issue #77）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.observability import metrics as M
from app.subgraphs.ticker import tools as tools_mod

# 引用 clear_infer_prompt_cache 便于隔离
from app.subgraphs.ticker.tools import _INFER_PROMPT_CACHE, _get_dynamic_prompt_cached, infer_code


def _clear_cache() -> None:
    _INFER_PROMPT_CACHE.clear()


@pytest.fixture(autouse=True)
def isolated_state() -> None:
    M.get_collector().reset()
    _clear_cache()
    yield
    M.get_collector().reset()
    _clear_cache()


def test_cache_miss_ok_emits_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.get_inference_prompt = AsyncMock(return_value="规则片段")
    monkeypatch.setattr(tools_mod, "_make_client", lambda: client)

    _get_dynamic_prompt_cached()

    coll = M.get_collector()
    assert (
        coll.get_counter(
            M.METRIC_DYNAMIC_PROMPT_TOTAL, {"status": "cache_miss_ok"}
        )
        == 1
    )
    assert coll.get_counter(M.METRIC_DYNAMIC_PROMPT_TOTAL, {"status": "cache_hit"}) == 0
    assert coll.get_counter(M.METRIC_DYNAMIC_PROMPT_TOTAL, {"status": "fallback"}) == 0


def test_cache_hit_emits_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.get_inference_prompt = AsyncMock(return_value="规则片段")
    monkeypatch.setattr(tools_mod, "_make_client", lambda: client)

    _get_dynamic_prompt_cached()  # miss_ok
    _get_dynamic_prompt_cached()  # hit
    _get_dynamic_prompt_cached()  # hit

    coll = M.get_collector()
    assert coll.get_counter(M.METRIC_DYNAMIC_PROMPT_TOTAL, {"status": "cache_hit"}) == 2
    assert (
        coll.get_counter(
            M.METRIC_DYNAMIC_PROMPT_TOTAL, {"status": "cache_miss_ok"}
        )
        == 1
    )


def test_fallback_emits_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.get_inference_prompt = AsyncMock(
        side_effect=ConnectionError("backend down")
    )
    monkeypatch.setattr(tools_mod, "_make_client", lambda: client)

    result = _get_dynamic_prompt_cached()
    assert result == ""  # 降级返回空串

    coll = M.get_collector()
    assert coll.get_counter(M.METRIC_DYNAMIC_PROMPT_TOTAL, {"status": "fallback"}) == 1


def test_backend_unreachable_treated_as_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真后端不可达（BackendUnreachableError）也应触发 fallback 指标。"""
    from app.tools.exceptions import BackendUnreachableError

    client = MagicMock()
    client.get_inference_prompt = AsyncMock(
        side_effect=BackendUnreachableError("ticker", "timeout")
    )
    monkeypatch.setattr(tools_mod, "_make_client", lambda: client)

    result = _get_dynamic_prompt_cached()
    assert result == ""

    coll = M.get_collector()
    assert coll.get_counter(M.METRIC_DYNAMIC_PROMPT_TOTAL, {"status": "fallback"}) == 1


def test_infer_code_end_to_end_emits_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    """infer_code 工具被调用时整链路应正确埋点。"""
    client = MagicMock()
    client.get_inference_prompt = AsyncMock(return_value="片段")
    monkeypatch.setattr(tools_mod, "_make_client", lambda: client)

    with patch.object(tools_mod, "_llm_infer", return_value="600519.SH"):
        result = infer_code.invoke({"keyword": "茅台"})

    assert result == "600519.SH"
    coll = M.get_collector()
    assert (
        coll.get_counter(
            M.METRIC_DYNAMIC_PROMPT_TOTAL, {"status": "cache_miss_ok"}
        )
        == 1
    )
