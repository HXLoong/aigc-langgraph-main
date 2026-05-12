"""harness/token_tracker.py · LLM token 追踪测试。"""
from __future__ import annotations

from unittest.mock import MagicMock

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from harness.token_tracker import TokenTracker, TokenUsage, aggregate


# ============================================================
# TokenUsage.merge · 跨 case 聚合
# ============================================================


def test_token_usage_merge_basic() -> None:
    a = TokenUsage(call_count=1, prompt_tokens=10, completion_tokens=5,
                   total_tokens=15, by_model={"qwen-30b": {"prompt": 10, "completion": 5}})
    b = TokenUsage(call_count=2, prompt_tokens=20, completion_tokens=8,
                   total_tokens=28, by_model={"qwen-30b": {"prompt": 20, "completion": 8}})
    merged = a.merge(b)
    assert merged.call_count == 3
    assert merged.prompt_tokens == 30
    assert merged.completion_tokens == 13
    assert merged.by_model["qwen-30b"] == {"prompt": 30, "completion": 13}


def test_token_usage_merge_does_not_mutate_originals() -> None:
    a = TokenUsage(call_count=1, prompt_tokens=10, completion_tokens=5,
                   total_tokens=15, by_model={"m1": {"prompt": 10, "completion": 5}})
    b = TokenUsage(call_count=1, prompt_tokens=20, completion_tokens=8,
                   total_tokens=28, by_model={"m1": {"prompt": 20, "completion": 8}})
    a.merge(b)
    # 原对象不被改
    assert a.call_count == 1
    assert a.by_model["m1"]["prompt"] == 10
    assert b.call_count == 1


def test_token_usage_merge_different_models() -> None:
    a = TokenUsage(by_model={"qwen-30b": {"prompt": 10, "completion": 5}})
    b = TokenUsage(by_model={"qwen-vl": {"prompt": 100, "completion": 50}})
    merged = a.merge(b)
    assert set(merged.by_model.keys()) == {"qwen-30b", "qwen-vl"}
    assert merged.by_model["qwen-30b"]["prompt"] == 10
    assert merged.by_model["qwen-vl"]["completion"] == 50


def test_aggregate_empty_list() -> None:
    assert aggregate([]).total_tokens == 0
    assert aggregate([]).call_count == 0


def test_aggregate_multiple_usages() -> None:
    usages = [
        TokenUsage(call_count=1, prompt_tokens=10, completion_tokens=5, total_tokens=15),
        TokenUsage(call_count=2, prompt_tokens=20, completion_tokens=8, total_tokens=28),
        TokenUsage(call_count=1, prompt_tokens=30, completion_tokens=3, total_tokens=33),
    ]
    out = aggregate(usages)
    assert out.call_count == 4
    assert out.prompt_tokens == 60
    assert out.completion_tokens == 16
    assert out.total_tokens == 76


# ============================================================
# TokenTracker · on_llm_end 路径 1（llm_output['token_usage']）
# ============================================================


def _make_result_with_llm_output(
    prompt_tokens: int, completion_tokens: int, model_name: str = "qwen3-30b-a3b"
) -> LLMResult:
    return LLMResult(
        generations=[[]],
        llm_output={
            "token_usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "model_name": model_name,
        },
    )


def test_tracker_extracts_from_llm_output() -> None:
    tracker = TokenTracker()
    tracker.on_llm_end(_make_result_with_llm_output(150, 30))
    usage = tracker.to_usage()
    assert usage.call_count == 1
    assert usage.prompt_tokens == 150
    assert usage.completion_tokens == 30
    assert usage.total_tokens == 180
    assert usage.by_model == {"qwen3-30b-a3b": {"prompt": 150, "completion": 30}}


def test_tracker_accumulates_multiple_calls() -> None:
    tracker = TokenTracker()
    tracker.on_llm_end(_make_result_with_llm_output(100, 20))
    tracker.on_llm_end(_make_result_with_llm_output(50, 10))
    usage = tracker.to_usage()
    assert usage.call_count == 2
    assert usage.prompt_tokens == 150
    assert usage.completion_tokens == 30


def test_tracker_groups_by_model() -> None:
    tracker = TokenTracker()
    tracker.on_llm_end(_make_result_with_llm_output(100, 20, "qwen3-30b-a3b"))
    tracker.on_llm_end(_make_result_with_llm_output(500, 100, "qwen-vl"))
    usage = tracker.to_usage()
    assert usage.by_model["qwen3-30b-a3b"] == {"prompt": 100, "completion": 20}
    assert usage.by_model["qwen-vl"] == {"prompt": 500, "completion": 100}


# ============================================================
# TokenTracker · on_llm_end 路径 2（AIMessage.usage_metadata）
# ============================================================


def _make_result_with_usage_metadata(
    input_tokens: int, output_tokens: int, model_name: str = "qwen3-30b-a3b"
) -> LLMResult:
    msg = AIMessage(
        content="answer",
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
        response_metadata={"model_name": model_name},
    )
    gen = ChatGeneration(message=msg)
    return LLMResult(generations=[[gen]], llm_output=None)


def test_tracker_fallback_to_usage_metadata() -> None:
    tracker = TokenTracker()
    tracker.on_llm_end(_make_result_with_usage_metadata(80, 15))
    usage = tracker.to_usage()
    assert usage.call_count == 1
    assert usage.prompt_tokens == 80
    assert usage.completion_tokens == 15
    assert usage.by_model["qwen3-30b-a3b"]["prompt"] == 80


def test_tracker_prefers_llm_output_over_usage_metadata() -> None:
    """如果两处都有 usage 数据，应该用 llm_output（更权威）。"""
    msg = AIMessage(
        content="answer",
        usage_metadata={
            "input_tokens": 999, "output_tokens": 999, "total_tokens": 1998,
        },  # 不应该被采用
    )
    gen = ChatGeneration(message=msg)
    result = LLMResult(
        generations=[[gen]],
        llm_output={
            "token_usage": {"prompt_tokens": 100, "completion_tokens": 20},
            "model_name": "qwen3-30b-a3b",
        },
    )
    tracker = TokenTracker()
    tracker.on_llm_end(result)
    usage = tracker.to_usage()
    assert usage.prompt_tokens == 100  # 来自 llm_output
    assert usage.completion_tokens == 20


# ============================================================
# 边界场景
# ============================================================


def test_tracker_skips_when_no_usage_available() -> None:
    """既无 llm_output 也无 usage_metadata → 不增 call_count。"""
    result = LLMResult(generations=[[]], llm_output=None)
    tracker = TokenTracker()
    tracker.on_llm_end(result)
    assert tracker.to_usage().call_count == 0


def test_tracker_skips_when_zero_tokens() -> None:
    """usage 字段存在但都是 0 → 不增（避免计数 mock LLM）。"""
    result = LLMResult(
        generations=[[]],
        llm_output={"token_usage": {"prompt_tokens": 0, "completion_tokens": 0}},
    )
    tracker = TokenTracker()
    tracker.on_llm_end(result)
    assert tracker.to_usage().call_count == 0


def test_tracker_handles_extract_exception_gracefully() -> None:
    """异常的 LLMResult shape 不应让 tracker 崩 → 整个 harness run。"""
    bad = MagicMock()
    bad.llm_output = "not-a-dict"  # 触发异常
    bad.generations = None  # 让 fallback 也炸
    tracker = TokenTracker()
    tracker.on_llm_end(bad)  # 不应抛
    assert tracker.to_usage().call_count == 0


def test_tracker_unknown_model_fallback() -> None:
    """没有 model_name 时 → 'unknown' bucket。"""
    result = LLMResult(
        generations=[[]],
        llm_output={"token_usage": {"prompt_tokens": 10, "completion_tokens": 5}},
    )
    tracker = TokenTracker()
    tracker.on_llm_end(result)
    usage = tracker.to_usage()
    assert "unknown" in usage.by_model
    assert usage.by_model["unknown"] == {"prompt": 10, "completion": 5}


# ============================================================
# 集成：reporter 渲染 markdown
# ============================================================


def test_reporter_markdown_includes_token_section_when_used() -> None:
    """有 token usage 数据时，markdown 应有该段。"""
    from harness.golden import GoldenCase
    from harness.reporter import render_markdown
    from harness.runner import RunResult

    case = GoldenCase(
        id="t1", category="swap/place_order", raw_content="...",
        expected={}, source="business_seed",
    )
    result = RunResult(
        case=case,
        final_state={},
        elapsed_ms=100,
        token_usage=TokenUsage(
            call_count=3,
            prompt_tokens=300,
            completion_tokens=60,
            total_tokens=360,
            by_model={"qwen3-30b-a3b": {"prompt": 300, "completion": 60}},
        ),
    )
    md = render_markdown([(result, [])])
    assert "LLM token 使用" in md
    assert "300" in md  # prompt tokens
    assert "qwen3-30b-a3b" in md


def test_reporter_markdown_omits_token_section_when_empty() -> None:
    """无 token 数据时（如 mock LLM）→ markdown 不输出空段。"""
    from harness.golden import GoldenCase
    from harness.reporter import render_markdown
    from harness.runner import RunResult

    case = GoldenCase(
        id="t1", category="swap/place_order", raw_content="...",
        expected={}, source="business_seed",
    )
    result = RunResult(case=case, final_state={}, elapsed_ms=100)
    md = render_markdown([(result, [])])
    assert "LLM token 使用" not in md


def test_summarize_includes_token_aggregation() -> None:
    from harness.golden import GoldenCase
    from harness.reporter import summarize
    from harness.runner import RunResult

    case = GoldenCase(
        id="t1", category="x", raw_content="...", expected={}, source="business_seed",
    )
    r1 = RunResult(
        case=case, final_state={}, elapsed_ms=10,
        token_usage=TokenUsage(call_count=1, prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    r2 = RunResult(
        case=case, final_state={}, elapsed_ms=10,
        token_usage=TokenUsage(call_count=2, prompt_tokens=20, completion_tokens=8, total_tokens=28),
    )
    s = summarize([(r1, []), (r2, [])])
    assert s["token_usage"]["call_count"] == 3
    assert s["token_usage"]["total_tokens"] == 43
