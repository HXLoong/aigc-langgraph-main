"""18. 企微群绑定交易对手查询  GET /api/internal/agent/getCtptyListByChatRoomId"""
from __future__ import annotations

from _utils import check, get, report, COM_AID, COM_SUB

print("18. 企微群绑定交易对手查询  GET /api/internal/agent/getCtptyListByChatRoomId")

d = get("/api/internal/agent/getCtptyListByChatRoomId",
        {"type": "TRS"}, COM_AID, COM_SUB)
ok, code, msg = check(d)
n = len(d.get("data", [])) if d.get("data") else 0
report("交易对手查询", ok, code, f"{n}个交易对手")
