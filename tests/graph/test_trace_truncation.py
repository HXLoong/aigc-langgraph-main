"""TraceEntry llm_output 截断测试(架构体检改进 C:防 checkpoint 膨胀)。

trace 是 add-reducer 累积字段,每个 checkpoint 携带全部历史 trace;
llm_output 若存完整 LLM 输出(如 OCR 全文),长会话下 checkpoint 会线性膨胀。
写入端统一截断:字符串字段超限截到上限并加标记,结构与短值原样保留。
"""
from __future__ import annotations

from app.graph.state import TRACE_TEXT_LIMIT, TraceEntry


class TestLlmOutputTruncation:
    def test_long_string_truncated(self):
        long_text = "长" * (TRACE_TEXT_LIMIT + 200)
        e = TraceEntry(node="n", llm_output={"raw": long_text})
        assert len(e.llm_output["raw"]) < TRACE_TEXT_LIMIT + 20
        assert e.llm_output["raw"].endswith("…[已截断]")

    def test_nested_structures_truncated(self):
        long_text = "x" * (TRACE_TEXT_LIMIT * 2)
        e = TraceEntry(
            node="n",
            llm_output={"orderList": [{"memo": long_text, "qty": 100}], "type": "ok"},
        )
        assert e.llm_output["orderList"][0]["memo"].endswith("…[已截断]")
        assert e.llm_output["orderList"][0]["qty"] == 100
        assert e.llm_output["type"] == "ok"

    def test_short_values_untouched(self):
        e = TraceEntry(node="n", llm_output={"type": "place_order_request", "n": 3})
        assert e.llm_output == {"type": "place_order_request", "n": 3}

    def test_excerpt_field_truncated(self):
        e = TraceEntry(node="n", llm_input_excerpt="y" * (TRACE_TEXT_LIMIT + 50))
        assert e.llm_input_excerpt.endswith("…[已截断]")

    def test_none_llm_output_ok(self):
        e = TraceEntry(node="n")
        assert e.llm_output is None
