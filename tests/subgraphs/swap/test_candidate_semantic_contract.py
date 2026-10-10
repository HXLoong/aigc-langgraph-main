"""一次联合解析的请求契约显式包含接口值、原文与字段定位。"""
import json

from langchain_core.utils.function_calling import convert_to_openai_tool

from app.parsing.prompts import SPECS


def test_joint_request_preserves_sources_and_declares_field_evidence():
    """引用、历史与本轮数据分开，规则不混入 Python 拼接。"""
    messages, _ = SPECS["swap"].build_messages({"raw_text": "甲证券剩余持仓 -120股，VWAP全天",
        "quote_content": "上一笔卖出平仓", "history_messages": [{"id": "old", "role": "user", "content": "买入甲证券"}]})
    sources = json.loads(messages[-1][1])["sources"]
    assert sources["raw"] == "甲证券剩余持仓 -120股，VWAP全天"
    assert sources["quote"] == "上一笔卖出平仓" and sources["history:old"] == "买入甲证券"
    wire = json.dumps(convert_to_openai_tool(SPECS["swap"].output_model), ensure_ascii=False)
    assert all(field in wire for field in ("intent", "orders", "fields", "confidence", "reference"))
    assert "CandidateDescription" not in wire
