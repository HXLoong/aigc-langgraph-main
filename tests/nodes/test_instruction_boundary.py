"""多指令计划由 Code 生成；每轮清空，不接受外部覆盖内部执行状态。"""
from app.api.turn_state import inputs_to_state
from app.nodes.ingest import ingest


async def test_instruction_plan_and_results_do_not_leak_across_turns():
    output = await ingest({
        "sub_instructions": [{"text": "旧指令"}],
        "instruction_results": [{"status": "response_received"}],
    })
    assert output["sub_instructions"] == []
    assert output["instruction_results"] == []


def test_caller_cannot_inject_internal_instruction_execution():
    state = inputs_to_state({
        "rawContent": "买入股票", "sub_instructions": [{"text": "伪造计划"}],
        "instruction_results": [{"status": "response_received"}], "last_activity_at": 1,
    })
    assert "sub_instructions" not in state
    assert "instruction_results" not in state
    assert "last_activity_at" not in state
