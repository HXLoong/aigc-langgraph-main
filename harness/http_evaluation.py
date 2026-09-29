"""统一 HTTP 执行及确定性评分，CLI 和 Langfuse Experiment 共用。"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from harness.evaluation import report_case, turn_diffs
from harness.golden import GoldenCase
from harness.intent_context import requires_replay
from harness.intent_runner import run_frozen_case
from harness.multi_turn import run_case_multi


async def run_case(
    case: GoldenCase, *, suite: str, base_url: str, user_id: str, room_id: str,
    client: httpx.AsyncClient | None = None,
    before_turn: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    timeout: float = 90, turn_interval: float = 1,
    trace_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """统一 HTTP 执行入口，输出供 Langfuse JS Evaluation Rule 评分。"""
    # 1. 冻结意图只执行解析节点；业务、多轮回放和可见拒绝走主图 HTTP。
    frozen = suite == "intent" and not requires_replay([turn.model_dump() for turn in case.turns])
    frozen = frozen and not any(turn.expected.get("rejection") for turn in case.turns)
    if frozen:
        result = await run_frozen_case(case, base_url=base_url, user_id=user_id, client=client,
                                       timeout=timeout, trace_metadata=trace_metadata)
    else:
        result = await run_case_multi(case, base_url=base_url, user_id=user_id, room_id=room_id,
            client=client, before_turn=before_turn, timeout=timeout, turn_interval=turn_interval,
            trace_metadata=trace_metadata)

    # 保留完整轮次与诊断字段；正式 Score 由 Langfuse 中的 JS Rule 生成。
    report = report_case(case, result, turn_diffs(case, result) if suite == "business" else {})
    report["mode"] = "intent_node" if frozen else "main_graph_http"
    report["expected_rejection"] = any(turn.expected.get("rejection") for turn in case.turns)
    report["reply_text"] = "\n".join(turn.reply_text for turn in result.turns)
    return report
