"""黄金用例的 HTTP 执行与本地确定性评分。"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from harness.evaluation import report_case, turn_diffs
from harness.golden import GoldenCase
from harness.intent_context import requires_replay
from harness.intent_runner import run_frozen_case
from harness.intent_scoring import score_intent
from harness.multi_turn import run_case_multi

DEFAULT_BASE_URL = "http://127.0.0.1:8000"


async def ensure_app_available(base_url: str = DEFAULT_BASE_URL) -> None:
    """评测只访问已有服务，不启动进程或核验数据库。"""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{base_url.rstrip('/')}/health")
            response.raise_for_status()
            if response.json().get("backend_mode") == "dry-run":
                raise ValueError("评测服务启用了 DRY_RUN_BACKEND，无法验证真实业务回复")
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError(f"评测服务不可用：{base_url}；请先启动 app。{exc}") from exc


async def run_case(
    case: GoldenCase, *, suite: str, base_url: str, user_id: str, room_id: str,
    client: httpx.AsyncClient | None = None,
    before_turn: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    timeout: float = 90, turn_interval: float = 1,
    trace_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """CLI 与平台触发共用执行和评分，不等待平台异步 Rule。"""
    # 1. 冻结意图只执行解析节点；业务与多轮回放走主图 HTTP。
    frozen = suite == "intent" and not requires_replay([turn.model_dump() for turn in case.turns])
    if frozen:
        result = await run_frozen_case(case, base_url=base_url, user_id=user_id, client=client,
                                       timeout=timeout, trace_metadata=trace_metadata)
    else:
        result = await run_case_multi(case, base_url=base_url, user_id=user_id, room_id=room_id,
            client=client, before_turn=before_turn, timeout=timeout, turn_interval=turn_interval,
            trace_metadata=trace_metadata)

    # 保留完整轮次与诊断字段；意图套件由本地确定性评分，业务套件由本地字段/文本断言。
    report = report_case(case, result, turn_diffs(case, result) if suite == "business" else {})
    report["mode"] = "intent_node" if frozen else "main_graph_http"
    # 快速样例只执行入口规则，报告不能把它标成普通模型解析。
    if frozen and all(turn.fast_query == "1" for turn in case.turns):
        report["mode"] = "entry_node"
    report["expected_rejection"] = any(turn.expected.get("rejection") for turn in case.turns)
    report["reply_text"] = "\n".join(turn.reply_text for turn in result.turns)
    if suite == "intent":
        scoring = score_intent(case, result)
        report["intent_scores"] = scoring["scores"]
        report["intent_pass"] = scoring["passed"]
        if not scoring["passed"]:
            report["status"] = "FAIL"
            report["passed"] = False
            report["failure"] = report.get("failure") or {
                "kind": "intent_mismatch",
                "error": "；".join(
                    score["comment"]
                    for score in scoring["scores"]
                    if score["metadata"]["assertion_count"] > 0 and not score["value"]
                )
                or "意图用例缺少可评分的标注",
            }
    return report
