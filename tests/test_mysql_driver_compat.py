"""aiomysql ↔ PyMySQL 版本兼容守护（CI slow job 2026-09-22 首次暴露）。

PyMySQL 1.2 把 `pymysql.converters.escape_bytes_prefixed` 换成了一个字符串哨兵
（"DO NOT IMPORT THIS!!!"），而 aiomysql 0.3.x 仍 `from pymysql.converters import
escape_bytes_prefixed` 并在 `Connection.escape(bytes)` 里调用它——任何 bytes 参数
（checkpoint 的 msgpack blob、node_trace 的二进制列）都会以 `TypeError: 'str' object
is not callable` 失败。生产 AIOMySQLSaver 走同一条路径，因此这里在单测层就钉死：
aiomysql 看到的 escape 助手必须是可调用对象，且能正确转义 bytes。
"""
from __future__ import annotations

import aiomysql.connection as aiomysql_connection


def test_aiomysql_bytes_escape_helper_is_callable() -> None:
    helper = aiomysql_connection.escape_bytes_prefixed
    assert callable(helper), (
        f"aiomysql 引用到的 escape_bytes_prefixed 不是函数：{helper!r}；"
        "PyMySQL 版本与 aiomysql 不兼容，检查 pyproject 的 PyMySQL 上限"
    )
    assert helper(b"\x00'\\") == "_binary'\\0\\'\\\\'"
