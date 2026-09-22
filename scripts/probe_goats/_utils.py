"""GOATS 接口探针共享工具（手工脚本，不是 pytest 用例）。

- 凭据一律来自 `app.config.get_settings()`（`.env` / 环境变量），仓库里不允许出现明文
  地址、client secret、salt 或 agent id（根 CLAUDE.md「绝对禁止」）；配置经模块级
  `__getattr__` 惰性读取，import 本模块不要求 `.env` 存在
- 写类接口（下单 / 撤单 / 平仓 / 改单）默认拒绝执行，必须显式 `--confirm-write`
  或 `PROBE_CONFIRM_WRITE=1`，避免"顺手跑一下"在测试环境真实下单
"""
from __future__ import annotations

import hashlib
import os
import sys
import time
from typing import Any

import httpx

from app.config import get_settings

#: 模块常量名 → (Settings 字段, 环境变量名)
_CONFIG_NAMES: dict[str, tuple[str, str]] = {
    "BASE_URL": ("goats_base_url", "GOATS_BASE_URL"),
    "CLIENT_ID": ("goats_client_id", "GOATS_CLIENT_ID"),
    "CLIENT_SECRET": ("goats_client_secret", "GOATS_CLIENT_SECRET"),
    "SALT": ("goats_extapp_salt", "GOATS_EXTAPP_SALT"),
    "OPT_AID": ("goats_opt_agent_id", "GOATS_OPT_AGENT_ID"),  # 期权 agent
    "OPT_SUB": ("goats_opt_agent_sub_id", "GOATS_OPT_AGENT_SUB_ID"),
    "COM_AID": ("goats_com_agent_id", "GOATS_COM_AGENT_ID"),  # 互换 / 通用 agent
    "COM_SUB": ("goats_com_agent_sub_id", "GOATS_COM_AGENT_SUB_ID"),
}
#: 子 agent id 允许为空
_OPTIONAL = frozenset({"OPT_SUB", "COM_SUB"})
_WRITE_SUFFIXES = ("/order", "/withdraw", "/close", "/replace")
_TIMEOUT = 15.0


def config(name: str) -> str:
    field, _env = _CONFIG_NAMES[name]
    return str(getattr(get_settings(), field) or "").rstrip("/")


def __getattr__(name: str) -> str:
    """`from _utils import COM_AID` 这类常量式用法走这里，首次访问才读 Settings。"""
    if name in _CONFIG_NAMES:
        return config(name)
    raise AttributeError(name)


def _require_config() -> None:
    missing = [env for name, (_field, env) in _CONFIG_NAMES.items()
               if name not in _OPTIONAL and not config(name)]
    if missing:
        raise SystemExit(f"探针缺少配置（写在 .env 或环境变量，禁止写进代码）: {', '.join(missing)}")


def write_confirmed() -> bool:
    return "--confirm-write" in sys.argv[1:] or os.getenv("PROBE_CONFIRM_WRITE") == "1"


def is_write(path: str) -> bool:
    return path.rstrip("/").endswith(_WRITE_SUFFIXES)


def sig() -> tuple[str, str]:
    ts = str(int(time.time() * 1000))
    raw = (config("CLIENT_ID") + ts + config("SALT")).encode()
    return hashlib.md5(raw).hexdigest().upper()[:16], ts


def headers(agentid: str, agentsubid: str) -> dict[str, str]:
    s, ts = sig()
    return {
        "clientid": config("CLIENT_ID"),
        "clientsecret": config("CLIENT_SECRET"),
        "signature": s,
        "timestamp": ts,
        "agenttype": "WECHAT",
        "agentid": agentid,
        "agentsubid": agentsubid,
        "Content-Type": "application/json",
    }


def post(path: str, body: Any, aid: str, asid: str) -> dict[str, Any]:
    _require_config()
    if is_write(path) and not write_confirmed():
        raise SystemExit(
            f"[SKIP-WRITE] {path} 是写类接口（会在测试环境真实下单/撤单）；"
            "确认后加 --confirm-write 或 PROBE_CONFIRM_WRITE=1 再跑"
        )
    url = f"{config('BASE_URL')}{path}"
    r = httpx.post(url, json=body, headers=headers(aid, asid), timeout=_TIMEOUT)
    return r.json()


def get(path: str, params: dict[str, Any], aid: str, asid: str) -> dict[str, Any]:
    _require_config()
    url = f"{config('BASE_URL')}{path}"
    r = httpx.get(url, params=params, headers=headers(aid, asid), timeout=_TIMEOUT)
    return r.json()


def check(d: dict[str, Any]) -> tuple[bool, int | None, str]:
    """errCode=200 算通过，即使 data 为空（查询类接口返回空列表是合法的）。"""
    ec = d.get("errCode", {}) or {}
    code = ec.get("code")
    msg = d.get("errMsg") or ""
    ok = code == 200
    return ok, code, msg


def report(name: str, ok: bool, code: int | None, detail: str = "") -> None:
    status = "OK" if ok else f"FAIL(code={code})"
    detail_str = f"  |  {detail}" if detail else ""
    print(f"  [{status}] errCode={code}{detail_str}")
