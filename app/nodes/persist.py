"""persist 节点：把 trace 沉淀到持久化层。

C1.8（Issue #57）完整实现：

- LangFuse：通过 CallbackHandler 自动写（M1 已接入，本节点不重复写）
- MySQL `langgraph_node_trace` 表：本节点把 `state["trace"]` 每条转一行写入

设计原则（CLAUDE.md 原则 3 + C1.8 acceptance）：
- 写 MySQL 失败**不阻塞业务主流程**：try/except + log.warn，不抛
- LangFuse 与 MySQL **互相独立**：一方 down 不影响另一方
- 与 Java/checkpoint 共库，以 langgraph_ 表名前缀隔离

业务订单审计场景：未来按 message_id / thread_id 在 node_trace 查全链路决策。

表结构（sql/init.sql）：
    message_id / thread_id / node_name / step_index /
    input_preview / output_preview / status / error / duration_ms / created_at
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.config import get_settings
from app.graph.safe_node import safe_node
from app.graph.state import AgentState
from app.storage.mysql import NODE_TRACE, SESSION_INIT, connection_args

logger = logging.getLogger(__name__)


_INPUT_PREVIEW_MAX = 2048
_OUTPUT_PREVIEW_MAX = 2048
_ERROR_PREVIEW_MAX = 4096


@safe_node
async def persist(state: AgentState) -> dict[str, Any]:
    """把 state['trace'] 写到 MySQL `langgraph_node_trace` 表。

    幂等：基于 (message_id, step_index) 行内顺序——同一 message 重复写不会冲突，
    但会插入新一组（业务侧按 created_at 取最新）。
    """
    trace = state.get("trace") or []
    if not trace:
        logger.debug("persist: empty trace, skip")
        return {}

    message_id = str(state.get("message_id") or "")
    thread_id = state.get("conversation_id") or ""
    trace_id = state.get("trace_id") or ""

    # 控制台日志（保留 M1 行为）
    logger.info(
        "persist trace_count=%d conversation_id=%s product_type=%s intent=%s",
        len(trace),
        thread_id,
        state.get("product_type"),
        state.get("intent"),
    )

    # MySQL 写入：完全独立 try/except，失败不影响业务
    try:
        await _write_to_mysql(trace, message_id, thread_id, trace_id)
    except Exception as exc:  # noqa: BLE001 - 监控不能影响业务
        logger.warning(
            "persist: MySQL 写入失败（不影响主流程）: %s", exc,
        )

    return {}


async def _write_to_mysql(
    trace: list[Any],
    message_id: str,
    thread_id: str,
    trace_id: str = "",
) -> None:
    """批量写 trace 到 node_trace 表。

    若 MYSQL_URI 未配置或不可达，抛异常被上层捕获。
    """
    settings = get_settings()
    uri = settings.mysql_uri
    if not uri:
        raise RuntimeError("MYSQL_URI 未配置")

    host, port, user, password, db = _parse_mysql_uri(uri)

    rows = [
        _trace_entry_to_row(entry, idx, message_id, thread_id, trace_id)
        for idx, entry in enumerate(trace)
    ]

    # aiomysql 延迟导入：避免无 MySQL 部署的开发场景启动报错
    import aiomysql

    conn = await asyncio.wait_for(
        aiomysql.connect(
            host=host, port=port, user=user, password=password, db=db,
            charset="utf8mb4", init_command=SESSION_INIT, autocommit=True,
        ),
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


def _trace_entry_to_row(
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
    input_preview = _truncate(decision, _INPUT_PREVIEW_MAX)
    output_preview = ""
    if llm_output is not None:
        try:
            output_preview = _truncate(
                json.dumps(llm_output, ensure_ascii=False), _OUTPUT_PREVIEW_MAX,
            )
        except Exception:  # noqa: BLE001
            output_preview = _truncate(repr(llm_output), _OUTPUT_PREVIEW_MAX)

    error_msg: str | None = None
    if status == "error":
        error_msg = _truncate(decision, _ERROR_PREVIEW_MAX)

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


def _truncate(text: str | None, max_len: int) -> str:
    if text is None:
        return ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _parse_mysql_uri(uri: str) -> tuple[str, int, str, str, str]:
    """解析 mysql+aiomysql://user:pass@host:port/db。

    支持的格式：
        mysql://user:pass@host:port/db
        mysql+aiomysql://user:pass@host:port/db
        mysql+aiomysql://user:pass@host:port/db?charset=utf8mb4
    """
    args = connection_args(uri)
    return args["host"], args["port"], args["user"], args["password"], args["db"]


__all__ = ["persist"]
