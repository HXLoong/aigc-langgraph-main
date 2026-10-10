"""persist 节点单元测试。

验证：
- 空 trace 不写 MySQL（return 早退）
- 非空 trace 调用 storage.node_trace.write_node_trace 一次
- MySQL 写失败被 catch（不抛、不阻塞）
- TraceEntry / dict / 其他对象都能正确转 row（app/storage/node_trace.py）
- mysql URI 解析正确（app/storage/mysql.py::connection_args）
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.graph.state import TraceEntry
from app.nodes.persist import persist
from app.storage.mysql import connection_args
from app.storage.node_trace import trace_entry_to_row as _trace_entry_to_row
from app.storage.node_trace import truncate_preview as _truncate


def _parse_mysql_uri(uri: str) -> tuple[str, int, str, str, str]:
    args = connection_args(uri)
    return args["host"], args["port"], args["user"], args["password"], args["db"]


def test_truncate_short_string_unchanged() -> None:
    assert _truncate("hello", 100) == "hello"


def test_truncate_long_string_with_ellipsis() -> None:
    result = _truncate("a" * 100, 10)
    assert result == "aaaaaaa..."
    assert len(result) == 10


def test_truncate_none_returns_empty() -> None:
    assert _truncate(None, 100) == ""


def test_parse_mysql_uri_basic() -> None:
    host, port, user, pwd, db = _parse_mysql_uri("mysql://u:p@h:3306/d")
    assert host == "h"
    assert port == 3306
    assert user == "u"
    assert pwd == "p"
    assert db == "d"


def test_parse_mysql_uri_aiomysql_prefix() -> None:
    host, port, user, pwd, db = _parse_mysql_uri("mysql+aiomysql://u:p@h:3306/d")
    assert host == "h"
    assert db == "d"


def test_parse_mysql_uri_with_query() -> None:
    host, port, user, pwd, db = _parse_mysql_uri(
        "mysql+aiomysql://u:p@h:3306/d?charset=utf8mb4"
    )
    assert db == "d"


def test_parse_mysql_uri_default_port() -> None:
    _, port, *_ = _parse_mysql_uri("mysql://u:p@h/d")
    assert port == 3306


def test_trace_entry_to_row_from_pydantic() -> None:
    entry = TraceEntry(node="swap.intent", decision="place_order_request", elapsed_ms=150)
    row = _trace_entry_to_row(entry, 0, "msg-1", "conv-1", "tid-1")
    assert row == (
        "msg-1",          # message_id
        "conv-1",         # thread_id
        "tid-1",          # trace_id
        "swap.intent",    # node_name
        0,                # step_index
        "place_order_request",  # input_preview
        "",               # output_preview
        "success",        # status
        None,             # error
        150,              # duration_ms
    )


def test_trace_entry_to_row_error_status() -> None:
    entry = TraceEntry(node="bad.node", decision="error", elapsed_ms=50)
    row = _trace_entry_to_row(entry, 1, "msg-1", "conv-1")
    assert row[7] == "error"
    assert row[8] == "error"  # error_msg = decision when status=error


def test_trace_entry_to_row_from_dict() -> None:
    row = _trace_entry_to_row(
        {"node": "render", "decision": "fallback", "elapsed_ms": 5},
        2, "msg-1", "conv-1",
    )
    assert row[3] == "render"
    assert row[4] == 2
    assert row[5] == "fallback"


def test_trace_entry_to_row_with_llm_output() -> None:
    entry = TraceEntry(
        node="option.intent",
        decision="inquiry",
        elapsed_ms=200,
        llm_output={"type": "inquiry", "tickers": ["600519.SH"]},
    )
    row = _trace_entry_to_row(entry, 0, "msg-1", "conv-1")
    assert "inquiry" in row[6]
    assert "600519" in row[6]


@pytest.mark.asyncio
async def test_persist_empty_trace_skips_mysql() -> None:
    """空 trace 不应调 MySQL。"""
    with patch("app.nodes.persist.write_node_trace", new=AsyncMock()) as mock_write:
        result = await persist({"trace": []})
    # safe_node 装饰器会附加 persist 自己的 trace 条目，所以 result 含 trace 但无 error
    assert "error" not in result
    mock_write.assert_not_called()


@pytest.mark.asyncio
async def test_persist_writes_to_mysql_on_success() -> None:
    """非空 trace 应调一次 MySQL。"""
    trace = [TraceEntry(node="intent_route", decision="swap")]
    with patch("app.nodes.persist.write_node_trace", new=AsyncMock()) as mock_write:
        result = await persist({
            "trace": trace,
            "message_id": "m1",
            "conversation_id": "c1",
        })
    assert "error" not in result
    mock_write.assert_awaited_once()


@pytest.mark.asyncio
async def test_persist_mysql_failure_does_not_break() -> None:
    """MySQL 写失败不抛、不影响业务返回（业务路径正常完成）。"""
    trace = [TraceEntry(node="swap.intent")]
    with patch(
        "app.nodes.persist.write_node_trace",
        new=AsyncMock(side_effect=RuntimeError("DB down")),
    ):
        result = await persist({"trace": trace, "message_id": "m1", "conversation_id": "c1"})
    # 关键断言：error 字段不应被设置（业务流程正常）
    assert "error" not in result


@pytest.mark.asyncio
async def test_persist_missing_mysql_uri_does_not_crash() -> None:
    """MYSQL_URI 未配置时也不应崩。"""
    trace = [TraceEntry(node="swap.intent")]
    with patch("app.storage.node_trace.get_settings") as mock_settings:
        mock_settings.return_value.mysql_uri = ""
        result = await persist({"trace": trace, "message_id": "m1", "conversation_id": "c1"})
    # 业务流程仍然正常
    assert "error" not in result
