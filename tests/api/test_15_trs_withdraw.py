"""15. 互换撤单  POST /api/internal/agent/trs/order/withdraw
链式: 下单 → 撤单
"""
from __future__ import annotations

from _utils import check, post, report, COM_AID, COM_SUB

print("15. 互换撤单  POST /api/internal/agent/trs/order/withdraw")

# Step 1: 下单 (HK_STOCK 同步单，可立即撤单)
d1 = post("/api/internal/agent/trs/order",
          {"transactionType": "HK_STOCK", "orderType": "BY_QTY", "quantity": 200,
           "windCode": "0700.HK", "price": 400, "priceType": "LimitOrder",
           "orderDirection": "BUY",
           "shortName": "11125测试短名（张天琪专用）"},
          COM_AID, COM_SUB)
ok1, code1, _ = check(d1)
koid = d1.get("data", {}).get("keyOrderId") if d1.get("data") else None
print(f"  [Step 1] 下单 keyOrderId={koid}  errCode={code1}")

# Step 2: 撤单
d2 = post("/api/internal/agent/trs/order/withdraw",
          {"orderList": [koid]}, COM_AID, COM_SUB)
ok2, code2, msg2 = check(d2)
detail = f"results={len(d2['data']) if d2.get('data') else 0}"
report("互换撤单", ok2, code2, detail)
