"""GOATS API 测试共享工具。"""
from __future__ import annotations

import hashlib
import time
from typing import Any

import requests

BASE_URL = "http://tstgoats.gf.com.cn"
DIFY_BASE_URL = "http://agent.smart-zone-dev.gf.com.cn"
DIFY_API_KEY = "app-0gZMM7e4jdPL3J32nfVwqA6Y"
CLIENT_ID = "TL_AGENT"
CLIENT_SECRET = "tltest"
SALT = "aaa"

# 期权 agent
OPT_AID = "10955866372569317@tl"
OPT_SUB = "1688856778752437"
# 互换/通用 agent
COM_AID = "10821094351495088@tl"
COM_SUB = "1688855175747584"


def sig() -> tuple[str, str]:
    ts = str(int(time.time() * 1000))
    return hashlib.md5((CLIENT_ID + ts + SALT).encode()).hexdigest().upper()[:16], ts


def headers(agentid: str, agentsubid: str) -> dict:
    s, ts = sig()
    return {
        "clientid": CLIENT_ID,
        "clientsecret": CLIENT_SECRET,
        "signature": s,
        "timestamp": ts,
        "agenttype": "WECHAT",
        "agentid": agentid,
        "agentsubid": agentsubid,
        "Content-Type": "application/json",
    }


def post(path: str, body: Any, aid: str, asid: str) -> dict:
    r = requests.post(f"{BASE_URL}{path}", json=body, headers=headers(aid, asid), timeout=15)
    return r.json()


def get(path: str, params: dict, aid: str, asid: str) -> dict:
    r = requests.get(f"{BASE_URL}{path}", params=params, headers=headers(aid, asid), timeout=15)
    return r.json()


def check(d: dict) -> tuple[bool, int | None, str]:
    ec = d.get("errCode", {}) or {}
    code = ec.get("code")
    msg = d.get("errMsg") or ""
    ok = code == 200
    return ok, code, msg


def report(name: str, ok: bool, code: int | None, detail: str = "") -> None:
    status = "OK" if ok else f"FAIL(code={code})"
    detail_str = f"  |  {detail}" if detail else ""
    print(f"  [{status}] errCode={code}{detail_str}")
