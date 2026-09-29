"""期限只按解析结果传输；代码不再换算月份或拒绝业务表达。"""
from __future__ import annotations

import json

import httpx
import pytest

from app.tools.option_client import FinancialOrderOpenApiSaveReqVO, OptionClientHttpx


@pytest.mark.parametrize("tenor", ["半年", "1Y", "1y", "0.5Y", "3个月", "0M", "-1M", "1.5M"])
@pytest.mark.parametrize("rfq", [False, True])
async def test_tenor_value_reaches_java_without_local_conversion(tenor, rfq):
    """普通询价与外部快速询价都不隐藏改写单位或数值。"""
    sent = []

    def handle(request):
        """观察真实 HTTP 出站 JSON。"""
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"code": 0, "data": "Java validation"})

    fields = {"optionRfq": {"tenor": [tenor]}} if rfq else {"orderList": [{"tenor": tenor}]}
    request = FinancialOrderOpenApiSaveReqVO(type="new_inquiry", conversationId="c", messageId=1,
        messageContent=tenor, rawContent=tenor, userId="u", roomId="r", **fields)
    await OptionClientHttpx(base_url="http://test", transport=httpx.MockTransport(handle), dry_run=False).operate(request)
    value = sent[0]["optionRfq"]["tenor"][0] if rfq else sent[0]["orderList"][0]["tenor"]
    assert value == tenor and sent[0]["rawContent"] == tenor
