"""12. 互换下单  POST /api/internal/agent/trs/order"""
from __future__ import annotations

from _utils import check, post, report, COM_AID, COM_SUB

print("12. 互换下单  POST /api/internal/agent/trs/order")

d = post("/api/internal/agent/trs/order",
         {"transactionType": "HK_STOCK", "orderType": "BY_QTY", "quantity": 200,
          "windCode": "0700.HK", "price": 400, "priceType": "LimitOrder",
          "orderDirection": "BUY",
          "shortName": "11125测试短名（张天琪专用）"},
         COM_AID, COM_SUB)
ok, code, msg = check(d)
koid = d.get("data", {}).get("keyOrderId") if d.get("data") else None
report("互换下单", ok, code, f"keyOrderId={koid} async={d.get('data',{}).get('async') if d.get('data') else '?'}")
