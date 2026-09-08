"""07. 可平仓合约列表  POST /api/internal/agent/option/position"""
from __future__ import annotations

from _utils import COM_AID, COM_SUB, check, post, report

print("07. 可平仓合约列表  POST /api/internal/agent/option/position")

d = post("/api/internal/agent/option/position",
         {"filter": {"allowCloseOut": True}, "pageNum": 1, "pageSize": 15},
         COM_AID, COM_SUB)
ok, code, msg = check(d)
total = d.get("data", {}).get("total", 0) if d.get("data") else 0
report("可平仓合约列表", ok, code, f"total={total}")
