"""另一条询价解析路径使用带 /api 的 GOATS 基础地址。"""
from types import SimpleNamespace

import httpx
import pytest

import app.config
import app.tools.goats_rfq as rfq


@pytest.mark.asyncio
@pytest.mark.parametrize("base_url", ["http://goats.test/api", "http://goats.test/api/"])
async def test_parser_url_has_one_api_prefix(monkeypatch, base_url):
    monkeypatch.setattr(app.config, "get_settings", lambda: SimpleNamespace(
        goats_base_url=base_url, goats_client_id="C", goats_client_secret="S",
        goats_extapp_salt="X", goats_opt_agent_id="R@tl", goats_opt_agent_sub_id="U",
        goats_rfq_direct_timeout_seconds=15.0,
    ))
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={
            "errCode": {"code": 200}, "errMsg": "", "data": {"tenor": ["1M"]},
        })

    client_type = httpx.AsyncClient
    client_options = []

    def make_client(**kwargs):
        client_options.append(kwargs)
        return client_type(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(rfq.httpx, "AsyncClient", make_client)
    out = await rfq.parse_rfq_instrument("快速询价")
    assert len(requests) == 1
    assert requests[0].url.path == "/api/internal/agent/option_rfq_instrument_parser"
    assert out == {"tenor": ["1M"]}
    assert client_options[0].get("trust_env") is False
