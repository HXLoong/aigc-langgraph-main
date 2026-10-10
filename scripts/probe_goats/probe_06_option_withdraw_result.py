"""06. 期权撤单结果查询  GET /api/internal/agent/option/order/withdrawResult"""
from __future__ import annotations

from _utils import OPT_AID, OPT_SUB, check, get, report

print("06. 期权撤单结果查询  GET /api/internal/agent/option/order/withdrawResult")

d = get("/api/internal/agent/option/order/withdrawResult",
        {"stockOrderCode": "OPTG-WFJJ202509030002"},
        OPT_AID, OPT_SUB)
ok, code, msg = check(d)
report("期权撤单结果查询", ok, code)
