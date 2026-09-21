"""Cache coverage distinguishes unknown usage from an explicitly reported miss."""
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from app.observability.llm_metrics import LLMMetricsCallback
from app.observability.metrics import get_collector


@pytest.mark.parametrize("usage,metadata,hit,miss,status", [
    ({"prompt_tokens": 100, "completion_tokens": 2, "prompt_cache_hit_tokens": 80, "prompt_cache_miss_tokens": 20}, None, 80, 20, "reported"),
    ({"prompt_tokens": 100, "completion_tokens": 2, "prompt_tokens_details": {"cached_tokens": 0}}, None, 0, 100, "reported"),
    ({"prompt_tokens": 100, "completion_tokens": 2}, None, 0, 0, "unreported"),
    ({}, {"input_tokens": 100, "output_tokens": 2, "total_tokens": 102, "input_token_details": {"cache_read": 40}}, 40, 60, "reported"),
    ({"prompt_tokens": 100, "completion_tokens": 2, "prompt_cache_hit_tokens": 80, "prompt_cache_miss_tokens": 20, "prompt_tokens_details": {"cached_tokens": 80}}, None, 80, 20, "reported"),
    ({"prompt_tokens": 100, "completion_tokens": 2, "prompt_cache_hit_tokens": 101}, None, 0, 0, "invalid"),
])
def test_cache_usage_callback(usage, metadata, hit, miss, status):
    collector = get_collector()
    collector.reset()
    callback = LLMMetricsCallback()
    rid = uuid4()
    callback.on_chat_model_start({}, [[]], run_id=rid,
        metadata={"langgraph_node": "swap_intent"}, invocation_params={"model_name": "test"})
    msg = AIMessage(content="ok", usage_metadata=metadata)
    callback.on_llm_end(LLMResult(generations=[[ChatGeneration(message=msg)]],
        llm_output={"model_name": "test", "token_usage": usage}), run_id=rid)
    labels = {"model": "test", "node": "swap_intent"}
    assert collector.get_counter("otc_agent_llm_cache_usage_total", {**labels, "status": status}) == 1
    for result, expected in (("hit", hit), ("miss", miss)):
        assert collector.get_counter("otc_agent_llm_cache_tokens_total", {**labels, "result": result}) == expected
    collector.reset()
