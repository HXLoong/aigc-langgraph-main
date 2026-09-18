"""LangGraph checkpoint 表清理(架构体检 2026-08 改进 B · 客户现场运维)。

背景:AIOMySQLSaver 的 checkpoints/checkpoint_blobs/checkpoint_writes 三表
只增不减,长期运行持续膨胀。本脚本按「线程最近一次 checkpoint 的时间」清理:
最新 ts 早于 N 天前的 thread,其三表数据整体删除(保留活跃会话完整历史)。

判据:表无时间戳列,用 checkpoint JSON 内的 $.ts(ISO8601,字典序可比较)。

用法(默认 dry-run,只报数不删):
    python scripts/cleanup_checkpoints.py --days 30
    python scripts/cleanup_checkpoints.py --days 30 --execute   # 真删

建议客户现场以 cron 每日执行(见 docs/on-call-runbook.md「checkpoint 清理」节)。
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import UTC, datetime, timedelta

from app.storage.mysql import CHECKPOINT_TABLES, connection_args

logger = logging.getLogger(__name__)

#: 按删除依赖排序:writes/blobs 先删,checkpoints 最后

#: 线程过期判定:该 thread 最新 checkpoint 的 $.ts 早于 cutoff
STALE_THREADS_SQL = (
    "SELECT thread_id, MAX(JSON_UNQUOTE(JSON_EXTRACT(checkpoint, '$.ts'))) AS last_ts "
    "FROM langgraph_checkpoints GROUP BY thread_id "
    "HAVING last_ts < %s OR last_ts IS NULL"
)


def cutoff_iso(days: int, now: datetime | None = None) -> str:
    """N 天前的 UTC ISO8601 时间串(与 checkpoint $.ts 同格式前缀,可字典序比较)。"""
    base = now or datetime.now(UTC)
    return (base - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")


def chunked(items: list[str], size: int = 200) -> list[list[str]]:
    """thread_id 分批,避免超长 IN 子句。"""
    return [items[i:i + size] for i in range(0, len(items), size)]


def delete_sql(table: str, batch_size: int) -> str:
    assert table in CHECKPOINT_TABLES  # 防注入:表名只能来自白名单
    placeholders = ", ".join(["%s"] * batch_size)
    return f"DELETE FROM {table} WHERE thread_id IN ({placeholders})"  # noqa: S608


def _parse_mysql_uri(uri: str) -> dict:
    return connection_args(uri)


async def run(days: int, execute: bool) -> dict[str, int]:
    import aiomysql

    from app.config import get_settings

    cutoff = cutoff_iso(days)
    conn_kw = _parse_mysql_uri(get_settings().checkpoint_mysql_uri)
    conn = await aiomysql.connect(autocommit=False, **conn_kw)
    stats: dict[str, int] = {"stale_threads": 0}
    try:
        async with conn.cursor() as cur:
            await cur.execute(STALE_THREADS_SQL, (cutoff,))
            threads = [row[0] for row in await cur.fetchall()]
            stats["stale_threads"] = len(threads)
            print(f"cutoff(UTC)={cutoff}  过期线程数={len(threads)}  execute={execute}")
            if not threads:
                return stats
            for batch in chunked(threads):
                for table in CHECKPOINT_TABLES:
                    if execute:
                        await cur.execute(delete_sql(table, len(batch)), batch)
                        stats[table] = stats.get(table, 0) + cur.rowcount
                    else:
                        await cur.execute(
                            f"SELECT COUNT(*) FROM {table} WHERE thread_id IN "  # noqa: S608
                            f"({', '.join(['%s'] * len(batch))})",
                            batch,
                        )
                        (n,) = await cur.fetchone()
                        stats[table] = stats.get(table, 0) + n
            if execute:
                await conn.commit()
        for table in CHECKPOINT_TABLES:
            verb = "已删除" if execute else "将删除(dry-run)"
            print(f"{table}: {verb} {stats.get(table, 0)} 行")
        return stats
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="LangGraph checkpoint 表按线程时效清理")
    parser.add_argument("--days", type=int, default=30, help="保留最近 N 天活跃的线程(默认 30)")
    parser.add_argument("--execute", action="store_true", help="真正删除(缺省为 dry-run)")
    args = parser.parse_args()
    asyncio.run(run(days=args.days, execute=args.execute))


if __name__ == "__main__":
    main()
