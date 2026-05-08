"""04. 期权下单结果查询  POST /api/internal/agent/option/order/query"""
from __future__ import annotations

from _utils import check, post, report, OPT_AID, OPT_SUB

print("04. 期权下单结果查询  POST /api/internal/agent/option/order/query")

d = post("/api/internal/agent/option/order/query",
         {"filter": {"contractType": "EUROPEAN_VANILLA", "keyStockOrderId": 973409},
          "pageNum": 1, "pageSize": 10},
         OPT_AID, OPT_SUB)
ok, code, msg = check(d)
total = d.get("data", {}).get("total", 0) if d.get("data") else 0
report("期权下单结果查询", ok, code, f"total={total}")
