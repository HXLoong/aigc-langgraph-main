"""19. 互换交易时间配置查询  GET /api/uniweb/rpa/trs/tradingHoursConfig"""
from __future__ import annotations

from _utils import check, get, report, COM_AID, COM_SUB

print("19. 互换交易时间配置查询  GET /api/uniweb/rpa/trs/tradingHoursConfig")

d = get("/api/uniweb/rpa/trs/tradingHoursConfig", {}, COM_AID, COM_SUB)
ok, code, msg = check(d)
n = len(d.get("data", [])) if d.get("data") else 0
report("交易时间配置查询", ok, code, f"{n}条配置")
