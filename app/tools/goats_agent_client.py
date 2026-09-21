"""GOATS /api/internal/agent/* 客户端(DSL v2 签名方案)。

对照源:主干工作流 code 节点「参与型看涨、雪球调询价参数解析」「存量兼容-交易查询指令」。
路径前缀口径（#178 定案，2026-09-18 tstgoats 实测）：`GOATS_BASE_URL` 为主机根（不含
`/api`），客户端补全 `/api/internal/agent/*`；缺该前缀会被 APISIX 网关以 405 / 静态页拒掉。
签名与鉴权头与 app/tools/auth.py 的 x-goats-* HMAC 方案**不同**:
本客户端用 md5(clientid + timestamp + extapp_salt).upper()[:16] + agent 系列头,
仅用于 /internal/agent/* 两个端点。

返回 dict 结构对齐 DSL code 节点输出:
{code, errMsg, api_data_result_obj, http_status, raw_response, reason, intent, productType}
- parse_rfq_instrument:网络/超时 → DSL 原文案;有响应但不可用(HTTP 非 200 / 结构异常 /
  字段缺失)→ _RFQ_RESPONSE_INVALID_MSG;失败根因写入 reason(trace 透出,6 类)
- query_instruction:errMsg 恒为 IGNORE_REQUEST_NOT_REPLY_USER(Java 侧静默哨兵)
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Protocol

import httpx

from app.config import get_settings
from app.tools.http_pool import acquire_http_client

RFQ_PARSER_PATH = "/api/internal/agent/option_rfq_instrument_parser"
INSTRUCTION_QUERY_PATH = "/api/internal/agent/instruction/query"

#: 存量兼容分支及 GOATS 50001 的静默哨兵(Java 机器人层看到即不回复用户)
IGNORE_REPLY_SENTINEL = "IGNORE_REQUEST_NOT_REPLY_USER"

#: 仅网络/超时使用(归因准确,DSL 原文案);其余失败分支见下方新增文案
_RFQ_UNAVAILABLE_MSG = "快速询价暂不可用,请检查网络"
#: 新增:GOATS 有响应但不可用(HTTP 非 200 / 结构异常 / 字段缺失)时的用户文案
_RFQ_RESPONSE_INVALID_MSG = "快速询价参数解析服务异常，请稍后重试或联系交易员。"


def build_agent_headers(
    *,
    room_id: str,
    user_id: str | None,
    client_id: str,
    client_secret: str,
    extapp_salt: str,
    timestamp_ms: int | None = None,
) -> dict[str, str]:
    """构造 /internal/agent/* 鉴权头(签名算法 1:1 对照 DSL code 节点)。"""
    ts = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
    signature_string = f"{client_id}{ts}{extapp_salt or ''}"
    signature = hashlib.md5(signature_string.encode()).hexdigest().upper()[:16]
    return {
        "agenttype": "WECHAT",
        "agentid": f"{room_id}@tl",
        "agentsubid": user_id or "",
        "clientid": client_id,
        "clientsecret": client_secret,
        "timestamp": str(ts),
        "signature": signature,
    }


def normalize_agent_base(base_url: str) -> str:
    """GOATS agent 基址归一（#178）：允许主机根或带 `/api` 尾缀两种历史写法。

    返回去掉尾斜杠、且不含尾部 `/api` 的基址；调用方统一拼接
    `/api/internal/agent/*`，保证最终路径只出现一次 `/api` 前缀。
    """
    base = (base_url or "").rstrip("/")
    return base[: -len("/api")] if base.endswith("/api") else base


class GoatsAgentClient(Protocol):
    """GOATS agent 端点协议(依赖反转,测试塞 Fake)。"""

    async def parse_rfq_instrument(
        self, query: str, room_id: str, user_id: str | None
    ) -> dict[str, Any]: ...

    async def query_instruction(
        self, query: str, room_id: str, user_id: str | None
    ) -> dict[str, Any]: ...


class GoatsAgentClientHttpx:
    """httpx 实现。"""

    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        extapp_salt: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = normalize_agent_base(base_url)
        self._client_id = client_id
        self._client_secret = client_secret
        self._extapp_salt = extapp_salt
        self._transport = transport

    def _headers(self, room_id: str, user_id: str | None) -> dict[str, str]:
        return build_agent_headers(
            room_id=room_id,
            user_id=user_id,
            client_id=self._client_id,
            client_secret=self._client_secret,
            extapp_salt=self._extapp_salt,
        )

    async def _post(
        self, path: str, body: dict[str, Any], room_id: str, user_id: str | None, timeout: float
    ) -> tuple[int | None, httpx.Response | None, str | None]:
        """返回 (http_status, response, fail_reason);网络异常 → (None, None, reason)。"""
        try:
            # 内网 GOATS 直连（池 trust_env=False，避免 Windows 系统代理返回 502）
            async with acquire_http_client(timeout=timeout, transport=self._transport) as client:
                resp = await client.post(
                    self._base_url + path,
                    headers=self._headers(room_id, user_id),
                    json=body,
                    timeout=timeout,
                )
                return resp.status_code, resp, None
        except (httpx.TimeoutException, TimeoutError):
            return None, None, "timeout"
        except httpx.HTTPError:
            return None, None, "network_error"

    async def parse_rfq_instrument(
        self, query: str, room_id: str, user_id: str | None
    ) -> dict[str, Any]:
        """参与型看涨/雪球快速询价指令解析(timeout 60s,对照 DSL)。"""
        base = {
            "code": 500,
            "errMsg": _RFQ_UNAVAILABLE_MSG,
            "api_data_result_str": "",
            "api_data_result_obj": None,
            "http_status": None,
            "raw_response": None,
            "reason": None,
            "intent": "new_inquiry",
            "productType": 0,
        }
        status, resp, fail_reason = await self._post(
            RFQ_PARSER_PATH, {"chatInstrument": query}, room_id, user_id,
            timeout=get_settings().goats_agent_rfq_timeout_seconds,
        )
        if resp is None:
            return {**base, "reason": fail_reason}
        base["http_status"] = status
        base["raw_response"] = resp.text
        if status != 200:
            return {**base, "errMsg": _RFQ_RESPONSE_INVALID_MSG, "reason": f"http_{status}"}
        try:
            body = resp.json()
        except ValueError:
            return {**base, "errMsg": _RFQ_RESPONSE_INVALID_MSG, "reason": "invalid_json"}
        if not isinstance(body, dict):
            return {**base, "errMsg": _RFQ_RESPONSE_INVALID_MSG, "reason": "body_not_dict"}
        err_code = body.get("errCode")
        if not isinstance(err_code, dict) or not isinstance(err_code.get("code"), int):
            return {**base, "errMsg": _RFQ_RESPONSE_INVALID_MSG, "reason": "err_code_invalid"}
        code = err_code["code"]
        if code == 50001:
            return {
                **base, "code": code, "errMsg": IGNORE_REPLY_SENTINEL,
                "reason": "sentinel_50001",
            }
        if code != 200:
            return {
                **base, "code": code, "errMsg": body.get("errMsg"),
                "reason": f"business_{code}",
            }
        data = body.get("data")
        if not isinstance(data, dict):
            return {**base, "errMsg": _RFQ_RESPONSE_INVALID_MSG, "reason": "data_missing"}
        return {
            **base,
            "code": 0,
            "errMsg": "",
            "api_data_result_obj": data,
            "api_data_result_str": json.dumps(data, ensure_ascii=False),
        }

    async def query_instruction(
        self, query: str, room_id: str, user_id: str | None
    ) -> dict[str, Any]:
        """存量兼容交易查询指令(timeout 10s;errMsg 恒为静默哨兵,对照 DSL)。"""

        def _result(code: int, **extra: Any) -> dict[str, Any]:
            return {
                "code": code,
                "errMsg": IGNORE_REPLY_SENTINEL,
                "api_data_result_str": "",
                "api_data_result_obj": None,
                "http_status": None,
                "raw_response": None,
                "intent": "new_inquiry",
                "productType": 0,
                **extra,
            }

        status, resp, _ = await self._post(
            INSTRUCTION_QUERY_PATH, {"chatInstruction": query}, room_id, user_id,
            timeout=get_settings().goats_agent_instruction_timeout_seconds,
        )
        if resp is None:
            return _result(500)
        if status != 200:
            return _result(500, http_status=status, raw_response=resp.text)
        try:
            data = resp.json()
        except ValueError:
            return _result(500, http_status=status, raw_response=resp.text)
        return _result(0, api_data_result_obj=data, http_status=status, raw_response=resp.text)


def make_goats_agent_client() -> GoatsAgentClientHttpx:
    """从 Settings 构造默认实现(生产入口)。"""
    from app.config import get_settings

    settings = get_settings()
    return GoatsAgentClientHttpx(
        base_url=settings.goats_base_url,
        client_id=settings.goats_client_id,
        client_secret=settings.goats_client_secret,
        extapp_salt=settings.goats_extapp_salt,
    )


__all__ = [
    "GoatsAgentClient",
    "GoatsAgentClientHttpx",
    "build_agent_headers",
    "make_goats_agent_client",
    "IGNORE_REPLY_SENTINEL",
]
