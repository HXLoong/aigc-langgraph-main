"""GoatsAgentClient(DSL v2 /internal/agent/* 签名方案)单测。

对照源:主干工作流 code 节点「参与型看涨、雪球调询价参数解析」「存量兼容-交易查询指令」。
签名:md5(clientid + timestamp + extapp_salt).hexdigest().upper()[:16]。
"""
from __future__ import annotations

import hashlib

import httpx
import pytest

from app.tools.goats_agent_client import GoatsAgentClientHttpx, build_agent_headers


class TestBuildAgentHeaders:
    def test_signature_scheme(self):
        headers = build_agent_headers(
            room_id="R1", user_id="U1",
            client_id="CID", client_secret="SEC", extapp_salt="SALT",
            timestamp_ms=1700000000000,
        )
        expected_sig = hashlib.md5("CID1700000000000SALT".encode()).hexdigest().upper()[:16]
        assert headers["signature"] == expected_sig
        assert headers["agenttype"] == "WECHAT"
        assert headers["agentid"] == "R1@tl"
        assert headers["agentsubid"] == "U1"
        assert headers["clientid"] == "CID"
        assert headers["clientsecret"] == "SEC"
        assert headers["timestamp"] == "1700000000000"

    def test_empty_user_id(self):
        headers = build_agent_headers(
            room_id="R1", user_id=None,
            client_id="C", client_secret="S", extapp_salt="",
            timestamp_ms=1,
        )
        assert headers["agentsubid"] == ""


def _make_client(handler) -> GoatsAgentClientHttpx:
    transport = httpx.MockTransport(handler)
    return GoatsAgentClientHttpx(
        base_url="http://goats.test",
        client_id="C", client_secret="S", extapp_salt="X",
        transport=transport,
    )


class TestParseRfqInstrument:
    @pytest.mark.asyncio
    async def test_success(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/internal/agent/option_rfq_instrument_parser"
            import json
            assert json.loads(request.content)["chatInstrument"] == "参与型看涨 茅台 1M"
            return httpx.Response(200, json={"instrument": "600519.SH"})

        out = await _make_client(handler).parse_rfq_instrument("参与型看涨 茅台 1M", "R", "U")
        assert out["code"] == 0
        assert out["api_data_result_obj"] == {"instrument": "600519.SH"}
        assert not out["errMsg"]

    @pytest.mark.asyncio
    async def test_network_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        out = await _make_client(handler).parse_rfq_instrument("q", "R", "U")
        assert out["code"] == 500
        assert out["errMsg"]  # 对齐 DSL:错误文案透传给用户

    @pytest.mark.asyncio
    async def test_http_500(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(502, text="bad gateway")

        out = await _make_client(handler).parse_rfq_instrument("q", "R", "U")
        assert out["code"] == 500


class TestQueryInstruction:
    @pytest.mark.asyncio
    async def test_success_always_ignore_reply(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/internal/agent/instruction/query"
            import json
            assert json.loads(request.content)["chatInstruction"] == "#TRS #当日委托"
            return httpx.Response(200, json={"rows": []})

        out = await _make_client(handler).query_instruction("#TRS #当日委托", "R", "U")
        assert out["code"] == 0
        # DSL 语义:存量兼容分支恒回 IGNORE 哨兵,Java 侧静默
        assert out["errMsg"] == "IGNORE_REQUEST_NOT_REPLY_USER"
        assert out["api_data_result_obj"] == {"rows": []}

    @pytest.mark.asyncio
    async def test_failure_also_ignore(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        out = await _make_client(handler).query_instruction("q", "R", "U")
        assert out["code"] == 500
        assert out["errMsg"] == "IGNORE_REQUEST_NOT_REPLY_USER"
