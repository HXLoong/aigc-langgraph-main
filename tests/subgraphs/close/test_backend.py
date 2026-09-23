"""close 子图后端调用测试（`call_close_backend`）。

平仓 operate payload 契约（docs/api-contracts/java-backend.md）：payload 固定
`orderList: []` + `closeOrderReqVO: {...}`，不复用 option 域的 orderList 字段
（P0 payload 对齐项）。
"""
from __future__ import annotations

from typing import Any

import pytest

from app.subgraphs.close.backend import call_close_backend
from app.tools.exceptions import MissingBackendContextError


def _patch_operate(monkeypatch: pytest.MonkeyPatch, result: dict[str, Any]) -> list[Any]:
    captured: list[Any] = []

    async def _fake_operate(self, req):  # type: ignore[no-untyped-def]
        captured.append(req)
        return result

    monkeypatch.setattr(
        "app.tools.option_client.OptionClientHttpx.operate", _fake_operate
    )
    return captured


FULL_STATE = {
    "raw_text": "平 CO-1 全部",
    "conversation_id": "conv-1",
    "user_id": "u-1",
    "room_id": "r-1",
    "message_id": 123,
}


@pytest.mark.asyncio
class TestCallCloseBackend:
    async def test_missing_context_raises_without_network(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = _patch_operate(monkeypatch, {"code": 0, "data": "x"})
        with pytest.raises(MissingBackendContextError):
            await call_close_backend(
                {"raw_text": "x"}, intent="close_order_query", close_order_req_vo={}
            )
        assert captured == []

    async def test_sends_close_order_req_vo_not_order_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = _patch_operate(monkeypatch, {"code": 0, "data": "ok"})
        req_vo = {"confirmOrderNoList": ["CO-A"]}
        await call_close_backend(
            FULL_STATE, intent="close_order_confirm", close_order_req_vo=req_vo
        )
        assert len(captured) == 1
        req = captured[0]
        # Java operate 契约：平仓请求 orderList 恒为 []，平仓明细走 closeOrderList
        assert req.order_list == []
        assert req.close_order_req_vo.model_dump()["confirmOrderNoList"] == ["CO-A"]
        assert req.type.value == "close_order_confirm"

    async def test_sanitizes_null_literal_before_sending(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = _patch_operate(monkeypatch, {"code": 0, "data": "ok"})
        req_vo = {"queryOrderNoList": ["null", "CO-B"]}
        await call_close_backend(
            FULL_STATE, intent="close_order_order_query", close_order_req_vo=req_vo
        )
        dumped = captured[0].close_order_req_vo.model_dump()
        assert dumped["queryOrderNoList"] == ["CO-B"]

    async def test_success_returns_code_and_data_verbatim(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_operate(monkeypatch, {"code": 0, "msg": "ok", "data": "真实回执文案"})
        result = await call_close_backend(
            FULL_STATE, intent="close_order_query", close_order_req_vo={}
        )
        assert result == {"api_code": 0, "api_result": "真实回执文案"}

    async def test_non_zero_code_returns_msg_not_data(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLAUDE.md P0：不掩盖后端真实响应——失败时透传 msg，不本地伪造成功文案。"""
        _patch_operate(
            monkeypatch,
            {"code": 500, "msg": "交易指令服务暂不可用", "data": None},
        )
        result = await call_close_backend(
            FULL_STATE, intent="close_order_request", close_order_req_vo={}
        )
        assert result == {"api_code": 500, "api_result": "交易指令服务暂不可用"}

    async def test_context_fields_mapped_from_state(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = _patch_operate(monkeypatch, {"code": 0, "data": "ok"})
        await call_close_backend(
            FULL_STATE, intent="close_order_query", close_order_req_vo={}
        )
        req = captured[0]
        assert req.conversation_id == "conv-1"
        assert req.user_id == "u-1"
        assert req.room_id == "r-1"
        assert req.raw_content == "平 CO-1 全部"


__all__: list[str] = []
