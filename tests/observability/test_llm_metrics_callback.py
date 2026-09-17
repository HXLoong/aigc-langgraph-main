"""LLM 指标 callback（ADR 0024 D5）：emit_llm_call / emit_llm_tokens 此前零调用，
llm_failure_high 告警永不触发、成本日报恒空。现由 LangChain callback 在 on_llm_end /
on_llm_error 自动打点，节点名取 LangGraph 注入的 metadata["langgraph_node"]。"""
from __future__ import annotations

from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from app.observability import metrics
from app.observability.llm_metrics import LLMMetricsCallback


@pytest.fixture(autouse=True)
def _reset() -> None:
    metrics.get_collector().reset()
    yield
    metrics.get_collector().reset()


def test_on_llm_end_emits_call_and_tokens_with_node_label() -> None:
    cb = LLMMetricsCallback()
    run_id = uuid4()
    cb.on_chat_model_start(
        {"name": "ChatOpenAI"}, [[]], run_id=run_id,
        metadata={"langgraph_node": "swap_intent"},
        invocation_params={"model_name": "deepseek-v4-pro"},
    )
    cb.on_llm_end(
        LLMResult(
            generations=[[ChatGeneration(message=AIMessage(content="ok"))]],
            llm_output={"token_usage": {"prompt_tokens": 120, "completion_tokens": 30},
                        "model_name": "deepseek-v4-pro"},
        ),
        run_id=run_id,
    )
    c = metrics.get_collector()
    assert c.get_counter(metrics.METRIC_LLM_TOTAL, {"model": "deepseek-v4-pro", "status": "ok"}) == 1
    assert c.get_counter(
        metrics.METRIC_LLM_TOKENS, {"model": "deepseek-v4-pro", "direction": "prompt", "node": "swap_intent"}
    ) == 120
    assert c.get_counter(
        metrics.METRIC_LLM_TOKENS, {"model": "deepseek-v4-pro", "direction": "completion", "node": "swap_intent"}
    ) == 30


def test_on_llm_end_reads_usage_metadata_fallback() -> None:
    cb = LLMMetricsCallback()
    msg = AIMessage(content="ok", usage_metadata={"input_tokens": 7, "output_tokens": 3, "total_tokens": 10},
                    response_metadata={"model_name": "m2"})
    cb.on_llm_end(LLMResult(generations=[[ChatGeneration(message=msg)]]), run_id=uuid4())
    c = metrics.get_collector()
    assert c.get_counter(metrics.METRIC_LLM_TOTAL, {"model": "m2", "status": "ok"}) == 1


def test_on_llm_error_emits_error_status_with_model_from_start() -> None:
    cb = LLMMetricsCallback()
    run_id = uuid4()
    cb.on_llm_start({"name": "x"}, ["p"], run_id=run_id, invocation_params={"model_name": "m3"})
    cb.on_llm_error(TimeoutError("slow"), run_id=run_id)
    c = metrics.get_collector()
    assert c.get_counter(metrics.METRIC_LLM_TOTAL, {"model": "m3", "status": "timeout"}) == 1


def test_callback_never_raises_on_garbage() -> None:
    cb = LLMMetricsCallback()
    cb.on_llm_end(LLMResult(generations=[]), run_id=uuid4())  # 无 usage → 不计数、不抛
    assert metrics.get_collector().get_counter(metrics.METRIC_LLM_TOTAL, {"model": "unknown", "status": "ok"}) == 0
