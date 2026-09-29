"""标的与交易对手路由：

- `/admin-api/counterparty/info/list` — 交易对手列表
- `/admin-api/counterparty/info/instrument-inference-prompt` — 推断 prompt 配置
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from mock_api.backend.fixtures import (
    COUNTERPARTIES,
    INSTRUMENT_INFERENCE_PROMPT,
)
from mock_api.backend.schemas import (
    CounterpartyInfoReqVO,
    common_ok,
)

router = APIRouter(tags=["mock-backend-ticker"])


# ============================================================
# 工具：词典匹配 + 评分
# ============================================================


def _normalize_hk(code: str) -> str:
    """港股代码补零归一化：00700.HK → 0700.HK，700 → 0700"""
    if "." in code:
        parts = code.split(".")
        if parts[1].upper() == "HK":
            num = parts[0].lstrip("0") or "0"
            return f"{int(num):04d}.HK"
    return code


@router.get("/admin-api/counterparty/info/list")
async def counterparty_info_list(
    type: str = Query("TRS", min_length=1),
    room_id: str = Query("mock-room", min_length=1, alias="roomId"),
    message_id: int | None = Query(None, alias="messageId"),
    order_id: str | None = Query(None, alias="orderId"),
    user_id: str | None = Query(None, alias="userId"),
) -> dict[str, Any]:
    """交易对手列表（GET /admin-api/counterparty/info/list）。

    Java 端是 `@Valid CounterpartyInfoRespVO`（命名沿用），实际是 ReqVO，
    `type` + `roomId` 必填。
    """
    # 触发 Pydantic 校验确保参数合法（业务行为：当前 mock 不区分 type/roomId）
    CounterpartyInfoReqVO(
        type=type, roomId=room_id, messageId=message_id, orderId=order_id, userId=user_id
    )
    return common_ok(COUNTERPARTIES)


@router.get("/admin-api/counterparty/info/instrument-inference-prompt")
async def instrument_inference_prompt() -> dict[str, Any]:
    """推断 prompt 配置（GET /admin-api/counterparty/info/instrument-inference-prompt）。"""
    return common_ok(INSTRUMENT_INFERENCE_PROMPT)
