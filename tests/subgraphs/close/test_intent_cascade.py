"""期权平仓子图校验失败后停止，不重试模型或提交 Java。"""
from unittest.mock import AsyncMock

import pytest

from app.subgraphs.close.graph import build_close_graph


@pytest.mark.parametrize("parsed", [{}, {"intent": "invalid", "confidence": .9, "evidence": [{"origin": "raw", "text": "测试"}]}, {"intent": "unknown_intent", "confidence": .9, "evidence": [{"origin": "raw", "text": "伪造"}]}])
async def test_invalid_joint_result_cascades_without_backend(monkeypatch, parsed):
    """结构错误和来源错误均应停在产品检查节点。"""
    client = AsyncMock()
    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.operate", client)
    result = await build_close_graph().ainvoke({"raw_text": "测试", "parsed_instruction": parsed})
    assert result.get("error") and result["error"].code == "E2"
    assert result["error"].node == "close_intent"
    client.assert_not_called()
