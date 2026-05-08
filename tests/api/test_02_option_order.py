"""02. 期权下单  POST /api/internal/agent/option/order"""
from __future__ import annotations

from _utils import check, post, report, COM_AID, COM_SUB

print("02. 期权下单  POST /api/internal/agent/option/order")

d = post("/api/internal/agent/option/order",
         {"id": 37053781, "contractType": "EUROPEAN_VANILLA",
          "direction": "CALL", "tradeDirection": "BUY",
          "quotationOrderType": "QUOTATION_FILE",
          "openPositionType": "MARKET_PRICE", "collateralNotional": 1000000},
         COM_AID, COM_SUB)
ok, code, msg = check(d)
opt_order_id = d.get("data") if d.get("data") else None
report("期权下单", ok, code, f"orderId={opt_order_id}")
