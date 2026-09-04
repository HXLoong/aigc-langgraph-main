"""09. 期权平仓订单查询  POST /api/internal/agent/option/order/close/query"""
from __future__ import annotations

from datetime import datetime

from _utils import COM_AID, COM_SUB, check, post, report

print("09. 期权平仓订单查询  POST /api/internal/agent/option/order/close/query")

d = post("/api/internal/agent/option/order/close/query",
         {"filter": {"tradeDate": datetime.now().strftime("%Y-%m-%d")},
          "pageNum": 1, "pageSize": 100},
         COM_AID, COM_SUB)
ok, code, msg = check(d)
total = d.get("data", {}).get("total", 0) if d.get("data") else 0
report("期权平仓订单查询", ok, code, f"total={total}")
