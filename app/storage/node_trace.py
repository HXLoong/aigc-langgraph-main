"""langgraph_node_trace 审计表写入（与 Java / checkpoint 共库，以 langgraph_ 前缀隔离）。

表结构（sql/init.sql）：
    message_id / thread_id / trace_id / node_name / step_index /
    input_preview / output_preview / status / error / duration_ms / created_at

写入失败由调用方（主图 persist 节点）吞掉并告警，不阻塞业务主流程。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiomysql

from app.config import get_settings
from app.storage.mysql import NODE_TRACE, connection_args

logger = logging.getLogger(__name__)

_INPUT_PREVIEW_MAX = 2048
_OUTPUT_PREVIEW_MAX = 2048
_ERROR_PREVIEW_MAX = 4096


async def write_node_trace(
    trace: list[Any], message_id: str, thread_id: str, trace_id: str = "",
) -> None:
    """批量写 trace 到 node_trace 表；MYSQL_URI 未配置或不可达时抛异常。"""
    settings = get_settings()
    uri = settings.mysql_uri
    if not uri:
        raise RuntimeError("MYSQL_URI 未配置")
    rows = [
        trace_entry_to_row(entry, idx, message_id, thread_id, trace_id)
        for idx, entry in enumerate(trace)
    ]
    conn = await asyncio.wait_for(
        aiomysql.connect(**connection_args(uri), autocommit=True),
        timeout=settings.persist_timeout_seconds,
    )
    try:
        async with conn.cursor() as cur:
            sql = (
                f"INSERT INTO {NODE_TRACE} "
                "(message_id, thread_id, trace_id, node_name, step_index, "
                " input_preview, output_preview, status, error, duration_ms) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            )
            await cur.executemany(sql, rows)
            logger.debug("persist: wrote %d rows to node_trace", len(rows))
    finally:
        conn.close()


def trace_entry_to_row(
    entry: Any, idx: int, message_id: str, thread_id: str, trace_id: str = "",
) -> tuple[Any, ...]:
    """把 TraceEntry / dict 转成 INSERT 行 tuple。"""
    # 鸭子类型：TraceEntry pydantic 模型 / dict
    if hasattr(entry, "model_dump"):
        data = entry.model_dump()
    elif isinstance(entry, dict):
        data = entry
    else:
        data = {"node": getattr(entry, "node", "unknown")}

    node_name = data.get("node", "unknown")
    decision = data.get("decision") or ""
    elapsed_ms = data.get("elapsed_ms")
    llm_output = data.get("llm_output")

    # status：decision == "error" → error；否则 success
    status = "error" if decision == "error" or decision.startswith("error:") else "success"

    # preview 截断
    input_preview = truncate_preview(decision, _INPUT_PREVIEW_MAX)
    output_preview = ""
    if llm_output is not None:
        try:
            output_preview = truncate_preview(
                json.dumps(llm_output, ensure_ascii=False), _OUTPUT_PREVIEW_MAX,
            )
        except Exception:  # noqa: BLE001
            output_preview = truncate_preview(repr(llm_output), _OUTPUT_PREVIEW_MAX)

    error_msg: str | None = None
    if status == "error":
        error_msg = truncate_preview(decision, _ERROR_PREVIEW_MAX)

    return (
        message_id,
        thread_id,
        trace_id,
        node_name,
        idx,
        input_preview,
        output_preview,
        status,
        error_msg,
        elapsed_ms,
    )


def truncate_preview(text: str | None, max_len: int) -> str:
    if text is None:
        return ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


__all__ = ["trace_entry_to_row", "truncate_preview", "write_node_trace"]
