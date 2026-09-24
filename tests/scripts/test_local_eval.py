"""Local HTTP evaluation prepares the exact message before sending it to the app."""
import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from harness.golden import GoldenCase
from harness.multi_turn import run_case_multi


async def test_turn_preparation_receives_real_quote_and_precedes_http():
    prepared = []

    async def prepare(inputs):
        prepared.append(dict(inputs))
        inputs["swap_counterparties"] = "[]"

    def respond(request):
        inputs = json.loads(request.content)["inputs"]
        assert prepared[-1]["message_id"] == inputs["message_id"]
        assert inputs["swap_counterparties"] == "[]"
        return httpx.Response(200, json={"data": {"status": "succeeded", "outputs": {
            "reply_text": f"reply-{len(prepared)}",
        }}})

    case = GoldenCase(id="local", category="test", turns=[
        {"send_text": "one"}, {"send_text": "two", "quote_previous": True},
    ])
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await run_case_multi(case, base_url="http://localhost:8201", user_id="u",
                                      room_id="r", client=client, before_turn=prepare)
    assert len(result.turns) == 2
    assert prepared[1]["quote_content"] == "reply-1"
    assert prepared[0]["message_id"] != prepared[1]["message_id"]
    assert all(turn.elapsed_ms >= 0 for turn in result.turns)


@pytest.mark.parametrize("url", ["http://10.49.91.229:8201", "https://remote.invalid", ""])
def test_local_eval_rejects_nonlocal_application_targets(url):
    local_eval = importlib.import_module("scripts.local_eval")
    with pytest.raises(ValueError, match="local"):
        local_eval.require_local(url)


@pytest.mark.parametrize("url", ["http://127.0.0.1:8201", "http://localhost:48080"])
def test_local_eval_accepts_loopback_targets(url):
    importlib.import_module("scripts.local_eval").require_local(url)


async def test_java_database_must_be_explicit_before_any_network_call(monkeypatch):
    module = importlib.import_module("scripts.local_eval")
    settings = module.get_settings().model_copy(update={
        "mysql_uri": "mysql+aiomysql://user:pass@localhost:3308",
        "eval_user_id": "u", "eval_room_id": "r",
    })
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    doctor = AsyncMock(return_value=2)
    monkeypatch.setattr(module, "_doctor", doctor)
    with pytest.raises(ValueError, match="database"):
        await module.run(SimpleNamespace(base_url="http://127.0.0.1:8201"))
    doctor.assert_not_called()


async def test_local_eval_uses_mysql_uri_without_separate_database_setting(monkeypatch):
    module = importlib.import_module("scripts.local_eval")
    monkeypatch.setattr(module, "get_settings", lambda: SimpleNamespace(
        mysql_uri="mysql+aiomysql://user:pass@localhost:3308/shared_java",
        otc_api_base_url="http://127.0.0.1:48080", eval_user_id="u", eval_room_id="r",
    ))
    doctor = AsyncMock(return_value=2)
    monkeypatch.setattr(module, "_doctor", doctor)
    assert await module.run(SimpleNamespace(base_url="http://127.0.0.1:8201")) == 2
    doctor.assert_awaited_once()


def test_empirical_percentiles_include_tail_for_small_samples():
    module = importlib.import_module("scripts.local_eval")
    assert module.latency_percentiles([10, 20, 30, 100]) == {
        "p50_ms": 20, "p95_ms": 100, "p99_ms": 100,
    }


async def test_text_model_probe_checks_every_distinct_configured_model(monkeypatch):
    module = importlib.import_module("scripts.local_eval")
    from app.llm import clients

    invoked = []
    def factory(name):
        async def invoke(messages):
            invoked.append(name)
            if name == "unsupported-ocr":
                raise ValueError("Function call is not supported")
            return {"status": "ready"}
        return SimpleNamespace(model_name=name, openai_api_base="http://model.invalid",
                               with_structured_output=lambda schema: SimpleNamespace(ainvoke=invoke))
    for name in ("get_qwen_standard", "get_qwen_thinking"):
        monkeypatch.setattr(clients, name, lambda: factory("text-model"))
    monkeypatch.setattr(clients, "get_qwen_complex", lambda: factory("unsupported-ocr"))
    with pytest.raises(ValueError, match="unsupported-ocr"):
        await module.probe_text_models()
    assert invoked == ["text-model", "unsupported-ocr"]


@pytest.mark.parametrize('dry_run,backend', [(True, 'dry-run'), (False, 'real')])
async def test_local_eval_preflight_requires_the_actual_configured_backend_mode(monkeypatch, dry_run, backend):
    module = importlib.import_module('scripts.local_eval')
    settings = module.get_settings().model_copy(update={
        'mysql_uri': 'mysql+aiomysql://test:test@localhost/local_eval',
        'otc_api_base_url': 'http://localhost:48081', 'eval_user_id': 'u', 'eval_room_id': 'r',
        'dry_run_backend': dry_run,
    })
    monkeypatch.setattr(module, 'get_settings', lambda: settings)
    doctor = AsyncMock(return_value=2)
    monkeypatch.setattr(module, '_doctor', doctor)
    assert await module.run(SimpleNamespace(base_url='http://localhost:8201')) == 2
    doctor.assert_awaited_once_with('http://localhost:8201', checkpoint='mysql', backend=backend)
