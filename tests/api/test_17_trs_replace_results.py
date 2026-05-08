"""17. 互换改单状态查询  POST /api/internal/agent/trs/order/replaceResults
链式: 下单 → 改单 → 查改单状态
"""
from __future__ import annotations

import time
from datetime import datetime

from _utils import check, post, report, COM_AID, COM_SUB

print("17. 互换改单状态查询  POST /api/internal/agent/trs/order/replaceResults")

# Step 1: 下单
d1 = post("/api/internal/agent/trs/order",
          {"transactionType": "HK_STOCK", "orderType": "BY_QTY", "quantity": 300,
           "windCode": "0700.HK", "price": 380, "priceType": "LimitOrder",
           "orderDirection": "BUY",
           "shortName": "11125测试短名（张天琪专用）"},
          COM_AID, COM_SUB)
ok1, code1, _ = check(d1)
koid = d1.get("data", {}).get("keyOrderId") if d1.get("data") else None
print(f"  [Step 1] 下单 keyOrderId={koid}  errCode={code1}")

time.sleep(2)

# Step 2: 改单
d2 = post("/api/internal/agent/trs/order/replace",
          {"orderList": [{"keyOrderId": koid, "priceType": "LimitOrder",
                          "quantity": 500, "price": 390, "algorithmType": "TWAP",
                          "startTime": datetime.now().strftime("%Y-%m-%d 11:00:00"),
                          "endTime": datetime.now().strftime("%Y-%m-%d 16:00:00")}]},
          COM_AID, COM_SUB)
ok2, code2, _ = check(d2)
print(f"  [Step 2] 改单 errCode={code2}")

# Step 3: 查改单状态
d3 = post("/api/internal/agent/trs/order/replaceResults",
          {"orderList": [koid]}, COM_AID, COM_SUB)
ok3, code3, msg3 = check(d3)
dl = d3.get("data", []) if d3.get("data") else []
detail = f"results={len(dl)}"
report("互换改单状态查询", ok3, code3, detail)
