"""GOATS 快速询价指令解析端点客户端。

调用 `${goatsBaseUrl}/api/internal/agent/option_rfq_instrument_parser`（base 为主机根，
/api 前缀由本模块补全，#178 定案），把用户的快速询价
原文（如 "快速询价：雪球，600989.SH，70/103，6M，30"）解析为结构化字段
（productType / tenor / strike / knockInPrice / knockOutPrice / estimateMargin 等）。

Dify 工作流原型见 `dify/yaml/主干工作流.yml` 节点 "参与型看涨、雪球调询价参数解析"。
鉴权风格（agenttype/agentid/clientid/clientsecret/timestamp/signature）与 GOATS
内部 agent 接口约定一致，与 securities-instrument 那套不同。
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

import httpx

from app.tools.goats_agent_client import normalize_agent_base

logger = logging.getLogger(__name__)


def _signature(client_id: str, ts: str, extapp_salt: str) -> str:
    """MD5(clientid + timestamp + extappsalt)[:16] 大写 —— Dify 内部 agent 端点专用签名。"""
    raw = f"{client_id}{ts}{extapp_salt or ''}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()[:16]


async def parse_rfq_instrument(chat_instrument: str) -> dict[str, Any] | None:
    """调 GOATS 快速询价解析端点，返回结构化字段 dict（或 None 表示失败）。

    返回值字段（核心）:
    - productType: "AUTOCALL" | "EUROPEAN_VANILLA" | "PARTICIPATORY" | ...
    - tenor: list[str]  期限，如 ["1M", "2M", "3M"]
    - strike: list[float]  执行价比例（0.8 表示 80%）
    - knockInPrice / knockOutPrice / estimateMargin: list[float]
    - fuzzyCodeList: list[str]  标的代码候选
    - chatType: "json"
    - chatInstrument: 原文回显

    失败返回 None（业务方 fall back 到 LLM 抽取路径）。
    """
    from app.config import get_settings
    settings = get_settings()

    base_url = settings.goats_base_url
    client_id = settings.goats_client_id
    client_secret = settings.goats_client_secret
    extapp_salt = settings.goats_extapp_salt
    agent_id = settings.goats_opt_agent_id
    sub_id = settings.goats_opt_agent_sub_id

    if not (base_url and client_id and client_secret and agent_id):
        logger.warning("goats 快速询价解析跳过：缺少配置（base/client/secret/agentId）")
        return None

    ts = str(int(time.time() * 1000))
    url = normalize_agent_base(base_url) + "/api/internal/agent/option_rfq_instrument_parser"
    headers = {
        "agenttype": "WECHAT",
        "agentid": agent_id,
        "agentsubid": sub_id or "",
        "clientid": client_id,
        "clientsecret": client_secret,
        "timestamp": ts,
        "signature": _signature(client_id, ts, extapp_salt),
    }

    try:
        async with httpx.AsyncClient(
            timeout=settings.goats_rfq_direct_timeout_seconds, trust_env=False
        ) as client:
            resp = await client.post(url, headers=headers, json={"chatInstrument": chat_instrument})
    except Exception as exc:  # noqa: BLE001  网络异常 → fall back
        logger.warning("goats 快速询价解析网络失败：%s", exc)
        return None

    if resp.status_code != 200:
        logger.warning("goats 快速询价解析 HTTP %s：%s", resp.status_code, resp.text[:200])
        return None
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        logger.warning("goats 快速询价解析响应非 JSON：%s", resp.text[:200])
        return None

    err_code = body.get("errCode", {})
    if not isinstance(err_code, dict) or err_code.get("code") != 200:
        logger.warning(
            "goats 快速询价解析业务失败：errCode=%s msg=%s",
            err_code,
            str(body.get("errMsg"))[:120],
        )
        return None

    data = body.get("data") or None
    if data is None:
        logger.warning("goats 快速询价解析无 data：%s", resp.text[:200])
    return data


__all__ = ["parse_rfq_instrument"]
