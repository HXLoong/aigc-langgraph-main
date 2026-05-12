"""D2.3 render 节点不可达文案分支测试（Issue #73）。"""
from __future__ import annotations

import pytest

from app.graph.state import ErrorInfo
from app.nodes.render import _ERROR_REPLY, _UNREACHABLE_REPLY, render


@pytest.mark.asyncio
async def test_backend_unreachable_error_uses_unreachable_reply() -> None:
    state: dict = {
        "error": ErrorInfo(
            node="option_operate",
            type="BackendUnreachableError",
            message="option: timeout",
            traceback=None,
        ),
    }
    update = await render(state)  # type: ignore[arg-type]
    assert update["reply_text"] == _UNREACHABLE_REPLY


@pytest.mark.asyncio
async def test_other_error_uses_generic_reply() -> None:
    """ValidationError / 一般异常仍走 _ERROR_REPLY。"""
    state: dict = {
        "error": ErrorInfo(
            node="intent_route",
            type="ValidationError",
            message="bad schema",
            traceback=None,
        ),
    }
    update = await render(state)  # type: ignore[arg-type]
    assert update["reply_text"] == _ERROR_REPLY


@pytest.mark.asyncio
async def test_error_as_dict_with_unreachable_type() -> None:
    """error 字段是 dict 形式（兼容情况）也能正确识别。"""
    state: dict = {
        "error": {
            "node": "swap_operate",
            "type": "BackendUnreachableError",
            "message": "swap: http_503",
        },
    }
    update = await render(state)  # type: ignore[arg-type]
    assert update["reply_text"] == _UNREACHABLE_REPLY
