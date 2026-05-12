#!/usr/bin/env python3
"""真后端连通性探测（D2.1 启动验证）。

按 ADR 0016 的 read-first 灰度顺序，只跑最安全的 3 个 read endpoint：
- counterparty/info/list             —— 完全 read，无副作用
- counterparty/info/instrument-inference-prompt —— 完全 read
- integration/securities-instrument/select with empty body —— 完全 read

每个 endpoint 输出：
- HTTP status
- 响应是否 JSON
- CommonResult envelope 是否合法（code / message / data 三字段是否存在）
- code 值（0 = 成功；非 0 = 业务拒绝，需对 message 看是什么原因）
- data 类型与长度（不打印内容，仅结构）

**绝不打印**：URL secret 部分、token、签名、响应业务数据。

使用：
    python scripts/probe_real_backend.py
    python scripts/probe_real_backend.py --ticker SH600000
    python scripts/probe_real_backend.py --json    # 机器可读输出
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse

import httpx


@dataclass
class ProbeResult:
    name: str
    method: str
    path: str
    http_status: int | None = None
    is_json: bool = False
    envelope_ok: bool = False
    code: int | None = None
    message: str | None = None
    data_type: str | None = None
    data_len: int | None = None
    error: str | None = None
    latency_ms: int | None = None


async def _probe_one(
    client: httpx.AsyncClient,
    name: str,
    method: str,
    base_url: str,
    path: str,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> ProbeResult:
    import time

    result = ProbeResult(name=name, method=method, path=path)
    url = f"{base_url}{path}"
    t0 = time.monotonic()
    try:
        if method == "GET":
            if body is not None:
                r = await client.request("GET", url, json=body, headers=headers)
            else:
                r = await client.get(url, params=params, headers=headers)
        else:
            r = await client.post(url, json=body, headers=headers)
        result.latency_ms = int((time.monotonic() - t0) * 1000)
        result.http_status = r.status_code

        try:
            payload = r.json()
            result.is_json = True
        except json.JSONDecodeError:
            result.error = f"response not JSON (first 80 chars): {r.text[:80]!r}"
            return result

        # CommonResult envelope 合法判定：有 code 字段 + 有 msg 或 message 任一
        keys = set(payload.keys()) if isinstance(payload, dict) else set()
        if "code" in keys and ("msg" in keys or "message" in keys):
            result.envelope_ok = True
            result.code = payload.get("code")
            result.message = payload.get("msg") or payload.get("message")
            data = payload.get("data")
            if data is None:
                result.data_type = "null"
            elif isinstance(data, list):
                result.data_type = "list"
                result.data_len = len(data)
            elif isinstance(data, dict):
                result.data_type = "dict"
                result.data_len = len(data)
            else:
                result.data_type = type(data).__name__
        else:
            preview = list(keys)[:5] if keys else type(payload).__name__
            result.error = f"envelope missing code/msg keys; keys: {preview}"
    except httpx.TimeoutException:
        result.error = "TIMEOUT"
    except httpx.ConnectError as exc:
        result.error = f"CONNECT_ERROR: {type(exc).__name__}"
    except Exception as exc:  # noqa: BLE001
        result.error = f"{type(exc).__name__}: {str(exc)[:120]}"
    return result


async def main(ticker_code: str | None, output_json: bool) -> int:
    from app.config import get_settings
    from app.tools.auth import get_goats_auth_headers

    settings = get_settings()
    base_url = settings.otc_api_base_url.rstrip("/")
    host = urlparse(base_url).hostname or "<unknown>"

    headers = {"Content-Type": "application/json"}
    if settings.otc_api_secret:
        headers["Authorization"] = f"Bearer {settings.otc_api_secret}"
    headers.update(get_goats_auth_headers())

    probes = [
        {
            "name": "counterparty.list",
            "method": "GET",
            "path": "/admin-api/counterparty/info/list",
        },
        {
            "name": "counterparty.inference_prompt",
            "method": "GET",
            "path": "/admin-api/counterparty/info/instrument-inference-prompt",
        },
        {
            "name": "ticker.select",
            "method": "GET",
            "path": "/admin-api/integration/securities-instrument/select",
            "body": {
                "keywordItems": [
                    {"keyword": ticker_code or "贵州茅台", "isFull": False}
                ]
            },
        },
    ]

    results: list[ProbeResult] = []
    async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
        for p in probes:
            results.append(
                await _probe_one(
                    client,
                    name=p["name"],
                    method=p["method"],
                    base_url=base_url,
                    path=p["path"],
                    headers=headers,
                    body=p.get("body"),
                )
            )

    if output_json:
        print(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2))
        return 0 if all(r.envelope_ok and r.code == 0 for r in results) else 1

    print(f"=== 真后端探测 · host={host} ===")
    print(f"{'name':<32} {'status':<8} {'code':<6} {'data':<14} {'lat ms':<8} {'note'}")
    print("-" * 100)
    any_fail = False
    for r in results:
        status = str(r.http_status) if r.http_status is not None else "—"
        code = str(r.code) if r.code is not None else "—"
        data_info = (
            f"{r.data_type}({r.data_len})"
            if r.data_len is not None
            else (r.data_type or "—")
        )
        lat = str(r.latency_ms) if r.latency_ms is not None else "—"
        note_parts = []
        if r.error:
            note_parts.append(f"ERR={r.error}")
        if r.envelope_ok and r.code != 0:
            note_parts.append(f"业务拒绝: {r.message or '(no msg)'}")
        note = " | ".join(note_parts) if note_parts else "OK"

        if r.error or (r.envelope_ok and r.code != 0):
            any_fail = True

        print(f"{r.name:<32} {status:<8} {code:<6} {data_info:<14} {lat:<8} {note}")

    print()
    print("退出门检查（D2.1 §阶段 2 退出门第 1-3 条）：")
    http_5xx = sum(1 for r in results if r.http_status and 500 <= r.http_status < 600)
    http_4xx = sum(1 for r in results if r.http_status and 400 <= r.http_status < 500)
    business_reject = sum(
        1 for r in results if r.envelope_ok and r.code is not None and r.code != 0
    )
    timeouts = sum(1 for r in results if r.error == "TIMEOUT")
    print(f"  HTTP 5xx       : {http_5xx} (退出门要求 = 0)")
    print(f"  HTTP 4xx       : {http_4xx} (退出门要求 = 0)")
    print(f"  业务拒绝(code≠0): {business_reject} (退出门要求：必须有对应 fallback)")
    print(f"  TIMEOUT        : {timeouts}")

    return 0 if not any_fail else 1


def cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", default=None, help="ticker.select 探测用的关键词")
    parser.add_argument("--json", action="store_true", help="机器可读 JSON 输出")
    args = parser.parse_args()
    return asyncio.run(main(args.ticker, args.json))


if __name__ == "__main__":
    sys.exit(cli())
