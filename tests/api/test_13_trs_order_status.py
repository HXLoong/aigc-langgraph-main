"""13. 互换下单状态查询  POST /api/internal/agent/trs/order/status
链式: 下单 → 查状态
"""
from __future__ import annotations

import time

from _utils import check, post, report, COM_AID, COM_SUB

print("13. 互换下单状态查询  POST /api/internal/agent/trs/order/status")

# Step 1: 下单
d1 = post("/api/internal/agent/trs/order",
          {"transactionType": "HK_STOCK", "orderType": "BY_QTY", "quantity": 200,
           "windCode": "0700.HK", "price": 400, "priceType": "LimitOrder",
           "orderDirection": "BUY",
           "shortName": "11125测试短名（张天琪专用）"},
          COM_AID, COM_SUB)
ok1, code1, _ = check(d1)
koid = d1.get("data", {}).get("keyOrderId") if d1.get("data") else None
print(f"  [Step 1] 下单 keyOrderId={koid}  errCode={code1}")

time.sleep(2)

# Step 2: 查状态
d2 = post("/api/internal/agent/trs/order/status",
          [{"keyOrderId": koid}],
          COM_AID, COM_SUB)
ok2, code2, msg2 = check(d2)
dl = d2.get("data", []) if d2.get("data") else []
detail = f"results={len(dl)}"
if dl:
    detail += f" completed={dl[0].get('completed')}"
report("互换下单状态查询", ok2, code2, detail)
