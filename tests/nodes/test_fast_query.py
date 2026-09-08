"""快速询价/存量兼容前置分支节点单测(mock 两个客户端工厂)。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.nodes.fast_query as fq
from app.nodes.fast_query import (
    existing_command_query,
    is_existing_command,
    is_fast_query,
    quick_inquiry,
)
from app.tools.goats_agent_client import IGNORE_REPLY_SENTINEL


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
    async def test_rfq_error_passthrough(self, monkeypatch):
        agent = FakeAgentClient(rfq={"code": 500, "errMsg": "快速询价暂不可用,请检查网络"})
        monkeypatch.setattr(fq, "_make_agent_client", lambda: agent)
        out = await quick_inquiry({"raw_text": "参与型看涨 茅台", "room_id": "R"})
        assert out["api_code"] == 500
        assert out["reply_text"] == "快速询价暂不可用,请检查网络"

    @pytest.mark.asyncio
    async def test_success_calls_backend_with_option_rfq(self, monkeypatch):
        agent = FakeAgentClient(
            rfq={"code": 0, "errMsg": "", "api_data_result_obj": {"windCode": "600519.SH"}}
        )
        backend = FakeOptionClient(SimpleNamespace(code=0, data="询价卡片", msg=None))
        monkeypatch.setattr(fq, "_make_agent_client", lambda: agent)
        monkeypatch.setattr(fq, "_make_option_client", lambda: backend)
        out = await quick_inquiry(
            {"raw_text": "参与型看涨 茅台 1M", "room_id": "R", "conversation_id": "c1", "message_id": 5}
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
    async def test_backend_500_mapped(self, monkeypatch):
        agent = FakeAgentClient(rfq={"code": 0, "errMsg": "", "api_data_result_obj": {}})
        backend = FakeOptionClient(SimpleNamespace(code=500, data=None, msg="ignored"))
        monkeypatch.setattr(fq, "_make_agent_client", lambda: agent)
        monkeypatch.setattr(fq, "_make_option_client", lambda: backend)
        out = await quick_inquiry({"raw_text": "q", "room_id": "R"})
        assert out["api_code"] == 500
        assert out["reply_text"] == "交易指令服务暂不可用"


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
