"""快速询价/存量兼容前置分支节点单测(mock 两个客户端工厂)。"""
from __future__ import annotations

import json
from unittest.mock import Mock

import httpx
import pytest

import app.nodes.fast_query as fq
from app.nodes.fast_query import (
    existing_command_query,
    is_existing_command,
    is_fast_query,
    quick_inquiry,
)
from app.tools.goats_agent_client import IGNORE_REPLY_SENTINEL, GoatsAgentClientHttpx
from app.tools.option_client import OptionClientHttpx


class FakeAgentClient:
    def __init__(self, rfq=None, instr=None):
        self._rfq = rfq or {}
        self._instr = instr or {}
        self.calls: list[tuple] = []

    async def parse_rfq_instrument(self, query, room_id, user_id):
        self.calls.append(("rfq", query, room_id, user_id))
        return self._rfq

    async def query_instruction(self, query, room_id, user_id):
        self.calls.append(("instr", query, room_id, user_id))
        return self._instr


class FakeOptionClient:
    def __init__(self, result):
        self._result = result
        self.reqs: list = []

    async def operate(self, req):
        self.reqs.append(req)
        return self._result


class TestBranchPredicates:
    def test_fast_query_flag(self):
        assert is_fast_query({"fast_query": "1"})
        assert not is_fast_query({"fast_query": "0"})
        assert not is_fast_query({})

    def test_existing_command_requires_not_at_bot(self):
        assert is_existing_command({"existing_command": "1", "at_bot": "0"})
        assert is_existing_command({"existing_command": "1", "at_bot": False})
        assert not is_existing_command({"existing_command": "1", "at_bot": "1"})
        assert not is_existing_command({"existing_command": "0", "at_bot": "0"})


class TestQuickInquiry:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("values,expected", [
        ([0.8, 1, "0.90"], ["0.8", "1", "0.90"]),
        (["0.8", "1"], ["0.8", "1"]),
        ([], []),
        (None, None),
    ])
    async def test_goats_numeric_arrays_reach_backend_as_strings(self, monkeypatch, values, expected):
        rfq_data = {
            "chatType": "json", "productType": "EUROPEAN_VANILLA",
            "fuzzyCodeList": ["600519.SH"], "tenor": ["1M"],
            "strike": values, "knockInPrice": values, "knockOutPrice": values,
            "estimateMargin": values, "participateRate": values,
        }
        requests = []

        def backend_handler(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={"code": 0, "data": "询价卡片"})

        agent = GoatsAgentClientHttpx("http://goats.test", "C", "S", "X",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
                "errCode": {"code": 200}, "errMsg": None, "data": rfq_data,
            })))
        backend = OptionClientHttpx(base_url="http://backend.test", token="test",
            transport=httpx.MockTransport(backend_handler))
        monkeypatch.setattr(fq, "_make_agent_client", lambda: agent)
        monkeypatch.setattr(fq, "_make_option_client", lambda: backend)
        out = await quick_inquiry({"raw_text": "快速询价：欧式看涨，600519.SH,80%，1M",
            "room_id": "R", "user_id": "U", "conversation_id": "c1", "message_id": 1})
        assert out.get("error") is None
        assert out["api_code"] == 0
        assert out["reply_text"] == "询价卡片"
        assert len(requests) == 1
        expected_rfq = {
            "chatType": "json", "productType": "EUROPEAN_VANILLA",
            "fuzzyCodeList": ["600519.SH"], "tenor": ["1M"],
        }
        if expected is not None:
            expected_rfq.update({k: expected for k in (
                "strike", "knockInPrice", "knockOutPrice", "estimateMargin", "participateRate",
            )})
        assert requests[0]["optionRfq"] == expected_rfq
        assert requests[0]["userId"] == "U"
        assert rfq_data["strike"] == values

    @pytest.mark.asyncio
    @pytest.mark.parametrize("user_id", ["dify-user", "", None])
    async def test_real_parser_unwraps_data_and_preserves_user_identity(self, monkeypatch, user_id):
        events = []

        def handler(request):
            events.append("goats")
            assert request.headers["agentsubid"] == (user_id or "")
            assert request.url.path == "/api/internal/agent/option_rfq_instrument_parser"
            return httpx.Response(200, json={
                "errCode": {"code": 200}, "errMsg": "成功",
                "data": {"windCode": "600519.SH", "tenor": ["1M"]},
            })

        agent = GoatsAgentClientHttpx("http://goats.test", "C", "S", "X",
                                      transport=httpx.MockTransport(handler))
        backend = FakeOptionClient({"code": 0, "data": "询价卡片", "msg": None})

        def make_backend():
            events.append("backend")
            return backend

        monkeypatch.setattr(fq, "_make_agent_client", lambda: agent)
        monkeypatch.setattr(fq, "_make_option_client", make_backend)
        out = await quick_inquiry({"raw_text": "参与型看涨 茅台 1M", "room_id": "R",
                                   "user_id": user_id, "operator_user_id": "operator",
                                   "conversation_id": "c", "message_id": 1})
        if not user_id:
            assert events == ["goats"] and not backend.reqs
            assert out["error"].type == "MissingBackendContextError"
            return
        assert out["api_code"] == 0
        assert events == ["goats", "backend"]
        assert len(backend.reqs) == 1
        dumped = backend.reqs[0].model_dump(exclude_none=True)
        assert dumped["userId"] == (user_id or "")
        assert dumped["optionRfq"] == {"windCode": "600519.SH", "tenor": ["1M"]}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status,body,code,reply,reason", [
        (200, {"errCode": {"code": 40301}, "errMsg": "无询价权限"}, 40301, "无询价权限", "business_40301"),
        (
            200, {"errCode": {"code": 50001}, "errMsg": "忽略"},
            50001, IGNORE_REPLY_SENTINEL, "sentinel_50001",
        ),
        (200, {"errCode": {"code": 40001}, "errMsg": ""}, 40001, "", "business_40001"),
        (502, {}, 500, "快速询价暂不可用,请检查网络", "http_502"),
        (200, {}, 500, "快速询价暂不可用,请检查网络", "err_code_invalid"),
    ])
    async def test_parser_failure_never_calls_backend(
        self, monkeypatch, status, body, code, reply, reason
    ):
        agent = GoatsAgentClientHttpx("http://goats.test", "C", "S", "X",
            transport=httpx.MockTransport(lambda _: httpx.Response(status, json=body)))
        backend_factory = Mock(side_effect=AssertionError("backend must not be called"))
        monkeypatch.setattr(fq, "_make_agent_client", lambda: agent)
        monkeypatch.setattr(fq, "_make_option_client", backend_factory)
        out = await quick_inquiry({"raw_text": "q", "room_id": "R", "user_id": "U"})
        backend_factory.assert_not_called()
        assert out["api_code"] == code
        assert out["reply_text"] == reply
        assert out["api_result"] == reply
        assert out["trace"][0].decision == f"rfq_parser_error:{reason}"

    @pytest.mark.asyncio
    async def test_rfq_error_passthrough(self, monkeypatch):
        agent = FakeAgentClient(rfq={"code": 500, "errMsg": "快速询价暂不可用,请检查网络"})
        monkeypatch.setattr(fq, "_make_agent_client", lambda: agent)
        out = await quick_inquiry({"raw_text": "参与型看涨 茅台", "room_id": "R"})
        assert out["api_code"] == 500
        assert out["reply_text"] == "快速询价暂不可用,请检查网络"
        assert out["trace"][0].decision == "rfq_parser_error:unknown"

    @pytest.mark.asyncio
    async def test_success_calls_backend_with_option_rfq(self, monkeypatch):
        agent = FakeAgentClient(
            rfq={"code": 0, "errMsg": "", "api_data_result_obj": {"windCode": "600519.SH"}}
        )
        backend = FakeOptionClient({"code": 0, "data": "询价卡片", "msg": None})
        monkeypatch.setattr(fq, "_make_agent_client", lambda: agent)
        monkeypatch.setattr(fq, "_make_option_client", lambda: backend)
        out = await quick_inquiry(
            {"raw_text": "参与型看涨 茅台 1M", "room_id": "R", "user_id": "U",
             "conversation_id": "c1", "message_id": 5}
        )
        assert out["api_code"] == 0
        assert out["reply_text"] == "询价卡片"
        req = backend.reqs[0]
        dumped = req.model_dump()
        assert dumped["type"] == "new_inquiry"
        assert dumped["operate"] == "询价"
        # VO 规范化后仍保留 optionRfq 数据(extra=allow,其余声明字段为 None)
        assert dumped["optionRfq"]["windCode"] == "600519.SH"

    @pytest.mark.asyncio
    async def test_backend_500_projects_reply_but_preserves_original_result(self, monkeypatch):
        agent = FakeAgentClient(rfq={"code": 0, "errMsg": "", "api_data_result_obj": {}})
        backend = FakeOptionClient({"code": 500, "data": None, "msg": "ignored"})
        monkeypatch.setattr(fq, "_make_agent_client", lambda: agent)
        monkeypatch.setattr(fq, "_make_option_client", lambda: backend)
        out = await quick_inquiry({"raw_text": "q", "room_id": "R", "user_id": "U",
                                   "conversation_id": "c", "message_id": 1})
        assert out["api_code"] == 500
        assert out["reply_text"] == "交易指令服务暂不可用"
        assert out["api_result"] == "ignored"

    async def test_parser_failure_log_omits_raw_customer_response(self, monkeypatch):
        agent = FakeAgentClient(rfq={"code": 500, "errMsg": "解析失败",
                                    "reason": "invalid_json", "raw_response": "客户私有交易数据"})
        monkeypatch.setattr(fq, "_make_agent_client", lambda: agent)
        warning = Mock()
        monkeypatch.setattr(fq.logger, "warning", warning)
        await quick_inquiry({"raw_text": "询价"})
        assert "客户私有交易数据" not in str(warning.call_args)
        assert "invalid_json" in str(warning.call_args)


class TestErrorCopyDisambiguation:
    def test_parser_failure_and_backend_failure_have_distinct_copy(self):
        import app.tools.goats_agent_client as goats

        texts = {
            goats._RFQ_UNAVAILABLE_MSG,
            goats._RFQ_RESPONSE_INVALID_MSG,
            fq._SERVICE_UNAVAILABLE,
        }
        assert len(texts) == 2
        assert "请检查网络" in goats._RFQ_UNAVAILABLE_MSG
        assert goats._RFQ_RESPONSE_INVALID_MSG == goats._RFQ_UNAVAILABLE_MSG
        assert "交易指令服务" in fq._SERVICE_UNAVAILABLE


class TestExistingCommand:
    @pytest.mark.asyncio
    async def test_ignore_sentinel_reply(self, monkeypatch):
        agent = FakeAgentClient(
            instr={
                "code": 0,
                "errMsg": IGNORE_REPLY_SENTINEL,
                "api_data_result_obj": {"rows": [1]},
            }
        )
        monkeypatch.setattr(fq, "_make_agent_client", lambda: agent)
        out = await existing_command_query({"raw_text": "#TRS #当日委托", "room_id": "R"})
        assert out["reply_text"] == IGNORE_REPLY_SENTINEL
        assert out["api_code"] == 0
        assert '"rows"' in out["api_result"]
