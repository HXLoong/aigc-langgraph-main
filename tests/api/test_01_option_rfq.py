"""01. 期权询价查询  POST /api/internal/agent/get_option_rfq"""
from __future__ import annotations

from _utils import check, post, report, OPT_AID, OPT_SUB

print("01. 期权询价查询  POST /api/internal/agent/get_option_rfq")

d = post("/api/internal/agent/get_option_rfq",
         {"chatType": "json", "chatInstrument": "快速询价：欧式看涨，600519.SH，100，1M",
          "productType": "EUROPEAN_VANILLA", "productSubtypeList": [],
          "fuzzyCodeList": ["600519.SH"], "tenor": [], "strike": [],
          "participateRate": [], "knockInPrice": [], "knockOutPrice": [],
          "estimateMargin": []},
         OPT_AID, OPT_SUB)
ok, code, msg = check(d)
n = len(d.get("data", {}).get("chatResult", [])) if d.get("data") else 0
report("期权询价查询", ok, code, f"返回{n}条询价")
