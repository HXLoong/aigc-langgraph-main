#!/usr/bin/env python3
"""Shadow 双跑：同时请求 LangGraph 和 Dify，对比差异写入 shadow_compare 表。

用于阶段 4（灰度切换期）的差异监控。

用法：
    python scripts/shadow_compare.py \
        --langgraph http://localhost:8000/v1/message \
        --dify http://localhost:5000/v1/workflows/run \
        --sample tests/fixtures/golden.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path

import aiomysql
import httpx


async def call_endpoint(client: httpx.AsyncClient, url: str, payload: dict) -> dict:
    try:
        r = await client.post(url, json=payload, timeout=60.0)
        return {"status": r.status_code, "body": r.json()}
    except Exception as e:
        return {"status": -1, "body": {"error": str(e)}}


def compare_results(a: dict, b: dict) -> tuple[bool, dict]:
    """语义对比两个响应。"""
    diffs = {}
    for key in ("product_type", "intent", "api_code"):
        a_val = a.get("body", {}).get(key)
        b_val = b.get("body", {}).get(key)
        if a_val != b_val:
            diffs[key] = {"langgraph": a_val, "dify": b_val}
    return (not diffs, diffs)


async def save_diff(pool: aiomysql.Pool, record: dict) -> None:
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO shadow_compare
                (message_id, primary_path, primary_result, shadow_result,
                 is_equal, diff_detail, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                record["message_id"],
                "langgraph",
                json.dumps(record["langgraph"], ensure_ascii=False),
                json.dumps(record["dify"], ensure_ascii=False),
                1 if record["is_equal"] else 0,
                json.dumps(record["diffs"], ensure_ascii=False),
                datetime.now(),
            ))
            await conn.commit()


async def main(args):
    with open(args.sample, encoding="utf-8") as f:
        cases = [json.loads(line) for line in f if line.strip()]

    pool = await aiomysql.create_pool(
        host=args.mysql_host, port=args.mysql_port,
        user=args.mysql_user, password=args.mysql_password,
        db=args.mysql_db, autocommit=False,
    )

    async with httpx.AsyncClient() as client:
        for case in cases:
            payload = {
                "conversation_id": f"shadow-{case['id']}",
                "message_id": f"shadow-m-{case['id']}",
                "room_id": "shadow-room",
                "user_id": "shadow-user",
                "guid": "",
                "raw_content": case["raw_content"],
                "quote_content": case.get("quote_content"),
            }

            # 并行调两个端点
            langgraph_task = call_endpoint(client, args.langgraph, payload)
            dify_task = call_endpoint(client, args.dify, payload)
            langgraph_resp, dify_resp = await asyncio.gather(langgraph_task, dify_task)

            is_equal, diffs = compare_results(langgraph_resp, dify_resp)

            print(f"[{case['id']}] {'=' if is_equal else '≠'}  diffs={diffs}")

            await save_diff(pool, {
                "message_id": payload["message_id"],
                "langgraph": langgraph_resp,
                "dify": dify_resp,
                "is_equal": is_equal,
                "diffs": diffs,
            })

    pool.close()
    await pool.wait_closed()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--langgraph", required=True, help="LangGraph endpoint")
    parser.add_argument("--dify", required=True, help="Dify endpoint")
    parser.add_argument("--sample", required=True, type=Path)
    parser.add_argument("--mysql-host", default="localhost")
    parser.add_argument("--mysql-port", type=int, default=3306)
    parser.add_argument("--mysql-user", default="otc_agent")
    parser.add_argument("--mysql-password", default="password")
    parser.add_argument("--mysql-db", default="otc_agent_business")
    args = parser.parse_args()

    asyncio.run(main(args))
