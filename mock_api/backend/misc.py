"""杂项后端接口：

- `/admin-api/business/config/bot/name/list` — Bot 名称（注意：data 是 JSON 字符串，与真实后端一致）
- `/admin-api/openapi/xbot/message/set-intent` — 意图审计写入（无返回值）
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body

from mock_api.backend.schemas import common_ok

router = APIRouter(tags=["mock-backend-misc"])


@router.post("/admin-api/business/config/bot/name/list")
async def bot_name_list() -> dict[str, Any]:
    """Bot 名称列表 — 真实后端 data 字段是个 JSON 字符串（业务方确认）。"""
    return common_ok(json.dumps(["otc-agent", "交易助手", "OTC小助手", "场外AI交易助手"]))


@router.post("/admin-api/openapi/xbot/message/set-intent")
async def set_intent(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    """意图审计写入 — 无返回值，仅 code=0 表示已记录。"""
    # 真实后端会落库；mock 不做存储，只 echo 关键字段确认收到
    return common_ok(None)
