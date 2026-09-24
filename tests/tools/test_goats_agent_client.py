"""GoatsAgentClient(DSL v2 /internal/agent/* 签名方案)单测。

对照源:主干工作流 code 节点「参与型看涨、雪球调询价参数解析」「存量兼容-交易查询指令」。
签名:md5(clientid + timestamp + extapp_salt).hexdigest().upper()[:16]。
"""
from __future__ import annotations

import hashlib
from unittest.mock import Mock

import httpx
import pytest

from app.tools.goats_agent_client import (
    IGNORE_REPLY_SENTINEL,
    GoatsAgentClientHttpx,
    build_agent_headers,
)


class TestBuildAgentHeaders:
    def test_signature_scheme(self):
        headers = build_agent_headers(
            room_id="R1", user_id="U1",
            client_id="CID", client_secret="SEC", extapp_salt="SALT",
            timestamp_ms=1700000000000,
        )
        expected_sig = hashlib.md5(b"CID1700000000000SALT").hexdigest().upper()[:16]
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
        base_url="http://goats.test/",
        client_id="C", client_secret="S", extapp_salt="X",
        transport=transport,
    )


class TestParseRfqInstrument:
    @pytest.mark.asyncio
    async def test_internal_request_disables_system_proxy(self, monkeypatch):
        client_factory = Mock(wraps=httpx.AsyncClient)
        monkeypatch.setattr(httpx, "AsyncClient", client_factory)
        await _make_client(lambda _: httpx.Response(200, json={
            "errCode": {"code": 200}, "data": {},
        })).parse_rfq_instrument("q", "R", "U")
        assert client_factory.call_args.kwargs.get("trust_env") is False

    @pytest.mark.asyncio
    async def test_success(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/internal/agent/option_rfq_instrument_parser"
            assert request.headers["agentsubid"] == "U"
            import json
            assert json.loads(request.content)["chatInstrument"] == "参与型看涨 茅台 1M"
            return httpx.Response(200, json={
                "errCode": {"code": 200}, "errMsg": "成功",
                "data": {"instrument": "600519.SH"},
            })

        out = await _make_client(handler).parse_rfq_instrument("参与型看涨 茅台 1M", "R", "U")
        assert out["code"] == 0
        assert out["api_data_result_obj"] == {"instrument": "600519.SH"}
        assert not out["errMsg"]
        assert out["reason"] is None

    @pytest.mark.asyncio
    async def test_api_suffix_base_is_normalized_to_single_prefix(self):
        """base 带 /api 尾缀（历史写法）归一后，最终路径仍只含一次 /api。"""
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/internal/agent/option_rfq_instrument_parser"
            return httpx.Response(200, json={"errCode": {"code": 200}, "data": {"ok": 1}})

        client = GoatsAgentClientHttpx(
            "http://goats.test/api/", "C", "S", "X", transport=httpx.MockTransport(handler)
        )
        out = await client.parse_rfq_instrument("q", "R", "U")
        assert out["code"] == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("code,message,expected,expected_reason", [
        (40301, "无询价权限", "无询价权限", "business_40301"),
        (50001, "无需回复", IGNORE_REPLY_SENTINEL, "sentinel_50001"),
        (40001, "", "", "business_40001"),
    ])
    async def test_business_error(self, code, message, expected, expected_reason):
        body = {"errCode": {"code": code}, "errMsg": message,
                "data": {"instrument": "must-not-be-forwarded"}}
        out = await _make_client(lambda _: httpx.Response(200, json=body)).parse_rfq_instrument(
            "q", "R", "U"
        )
        assert out["code"] == code
        assert out["errMsg"] == expected
        assert out["api_data_result_obj"] is None
        assert out["http_status"] == 200
        assert out["reason"] == expected_reason

    @pytest.mark.asyncio
    @pytest.mark.parametrize("body,expected_reason", [
        ({}, "err_code_invalid"),
        ([], "body_not_dict"),
        ({"errCode": None}, "err_code_invalid"),
        ({"errCode": {"code": 200}}, "data_missing"),
        ({"errCode": {"code": 200}, "data": "invalid"}, "data_missing"),
    ])
    async def test_malformed_response_is_failure(self, body, expected_reason):
        out = await _make_client(lambda _: httpx.Response(200, json=body)).parse_rfq_instrument(
            "q", "R", "U"
        )
        assert out["code"] == 500
        assert out["api_data_result_obj"] is None
        assert out["errMsg"] == "快速询价暂不可用,请检查网络"
        assert out["reason"] == expected_reason

    @pytest.mark.asyncio
    async def test_invalid_json(self):
        out = await _make_client(lambda _: httpx.Response(200, text="not json")).parse_rfq_instrument(
            "q", "R", "U"
        )
        assert out["code"] == 500
        assert out["errMsg"] == "快速询价暂不可用,请检查网络"
        assert out["reason"] == "invalid_json"

    @pytest.mark.asyncio
    async def test_json_null_body_is_failure(self):
        """JSON 字面量 null 响应（httpx 的 json=None 不会发送 body，需用 text="null" 构造）。"""
        out = await _make_client(
            lambda _: httpx.Response(200, text="null")
        ).parse_rfq_instrument("q", "R", "U")
        assert out["code"] == 500
        assert out["errMsg"] == "快速询价暂不可用,请检查网络"
        assert out["reason"] == "body_not_dict"

    @pytest.mark.asyncio
    async def test_network_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        out = await _make_client(handler).parse_rfq_instrument("q", "R", "U")
        assert out["code"] == 500
        # 对齐 DSL:网络场景沿用原文案透传给用户
        assert out["errMsg"] == "快速询价暂不可用,请检查网络"
        assert out["reason"] == "network_error"

    @pytest.mark.asyncio
    async def test_timeout_reason(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow")

        out = await _make_client(handler).parse_rfq_instrument("q", "R", "U")
        assert out["code"] == 500
        assert out["errMsg"] == "快速询价暂不可用,请检查网络"
        assert out["reason"] == "timeout"

    @pytest.mark.asyncio
    async def test_http_500(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(502, text="bad gateway")

        out = await _make_client(handler).parse_rfq_instrument("q", "R", "U")
        assert out["code"] == 500
        assert out["errMsg"] == "快速询价暂不可用,请检查网络"
        assert out["reason"] == "http_502"


class TestQueryInstruction:
    @pytest.mark.asyncio
    async def test_success_always_ignore_reply(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/internal/agent/instruction/query"
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
