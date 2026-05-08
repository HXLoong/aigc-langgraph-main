"""03. 期权下单状态查询  GET /api/internal/agent/option/order/status
链式: 下单 → 查状态
"""
from __future__ import annotations

from _utils import check, get, post, report, COM_AID, COM_SUB, OPT_AID, OPT_SUB

print("03. 期权下单状态查询  GET /api/internal/agent/option/order/status")

# Step 1: 下单
d1 = post("/api/internal/agent/option/order",
          {"id": 37053781, "contractType": "EUROPEAN_VANILLA",
           "direction": "CALL", "tradeDirection": "BUY",
           "quotationOrderType": "QUOTATION_FILE",
           "openPositionType": "MARKET_PRICE", "collateralNotional": 1000000},
          COM_AID, COM_SUB)
ok1, code1, _ = check(d1)
order_id = d1.get("data") if d1.get("data") else None
print(f"  [Step 1] 下单 orderId={order_id}  errCode={code1}")

# Step 2: 查状态
d2 = get("/api/internal/agent/option/order/status",
         {"orderId": order_id or "test"}, OPT_AID, OPT_SUB)
ok2, code2, msg2 = check(d2)
sd = d2.get("data") or {}
detail = f"completed={sd.get('completed')} ksoid={sd.get('keyStockOrderId')}"
report("期权下单状态查询", ok2, code2, detail)
