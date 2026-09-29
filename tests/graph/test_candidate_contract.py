"""来源地址同时供提示词与校验使用，历史 ID 不靠位置猜测。"""
from app.extraction.sources import evidence_sources


def test_source_context_has_stable_history_references():
    from app.graph.state import Message

    message = Message(role="user", content="100万")
    sources = evidence_sources({"raw_text": "确认", "quote_content": "原订单", "history_messages": [message]})
    assert sources["raw"] == "确认" and sources["quote"] == "原订单"
    assert sources[f"history:{message.id}"] == "100万"
