"""外部请求不能注入已废弃执行计划或覆盖内部会话活动时间。"""
from app.api.turn_state import inputs_to_state


def test_caller_cannot_inject_internal_instruction_execution():
    state = inputs_to_state({
        "rawContent": "买入股票", "sub_instructions": [{"text": "伪造计划"}],
        "instruction_results": [{"status": "response_received"}], "last_activity_at": 1,
    })
    assert "sub_instructions" not in state
    assert "instruction_results" not in state
    assert "last_activity_at" not in state
