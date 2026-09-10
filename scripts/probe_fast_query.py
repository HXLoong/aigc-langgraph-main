"""交互式验证真实 GOATS 快速询价解析，不调用后端询价接口。

在项目根目录运行：.venv/Scripts/python.exe -m scripts.probe_fast_query
"""
from __future__ import annotations

import argparse
import asyncio
import json

from app.config import get_settings
from app.tools.goats_agent_client import build_agent_headers, make_goats_agent_client


def validate_identity(value: str, label: str) -> str:
    value = value.strip()
    if not value or not value.isascii() or any(c.isspace() for c in value):
        raise ValueError(f"{label} 必须填写真实 ID，不能包含中文、空白或示例占位符。")
    return value


async def probe(query: str, room_id: str, user_id: str) -> int:
    room_id = validate_identity(room_id, "群 ID")
    user_id = validate_identity(user_id, "用户 ID（Dify sys.user_id）")
    if not query.strip() or "替换为" in query:
        raise ValueError("请填写原来失败的真实询价原文。")

    settings = get_settings()
    for name in ("goats_base_url", "goats_client_id", "goats_client_secret", "goats_extapp_salt"):
        if not getattr(settings, name):
            raise ValueError(f"请先核对 .env 中的 {name.upper()}，当前未配置。")
    headers = build_agent_headers(
        room_id=room_id, user_id=user_id,
        client_id=settings.goats_client_id,
        client_secret=settings.goats_client_secret,
        extapp_salt=settings.goats_extapp_salt,
    )
    for name, value in headers.items():
        if not value.isascii() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError(f"请求头 {name} 包含非 ASCII 字符或控制字符，请核对对应配置。")

    print("正在调用 GOATS 解析接口，最多等待 60 秒……", flush=True)
    result = await make_goats_agent_client().parse_rfq_instrument(query, room_id, user_id)
    print(json.dumps({
        k: result.get(k)
        for k in ("http_status", "code", "errMsg", "api_data_result_obj")
    }, ensure_ascii=False, indent=2))
    if result["code"] == 0:
        print("GOATS 解析成功；完整询价还需在原业务入口验证后端返回结果。")
        return 0
    if result["code"] == 50001:
        print("GOATS 要求静默忽略，本次没有返回询价参数。")
    elif result["http_status"] is None:
        print("未收到 HTTP 响应，请检查网络、VPN、DNS 或超时。")
    elif result["http_status"] != 200:
        print("HTTP 请求失败，请检查接口地址和网关状态。")
    else:
        print("未解析成功，请根据业务错误码和 errMsg 核对鉴权、参数或响应格式。")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", help="原来失败的真实询价原文")
    parser.add_argument("--room-id", help="真实群 ID（不带自动追加的 @tl）")
    parser.add_argument("--user-id", help="对应 Dify sys.user_id 的真实用户 ID")
    args = parser.parse_args()
    try:
        query = args.query if args.query is not None else input("询价原文：")
        room_id = args.room_id if args.room_id is not None else input("真实群 ID：")
        user_id = args.user_id if args.user_id is not None else input("真实用户 ID（Dify sys.user_id）：")
        return asyncio.run(probe(query, room_id, user_id))
    except ValueError as exc:
        # Settings 校验错误可能带凭据，只输出字段名。
        from pydantic import ValidationError

        if isinstance(exc, ValidationError):
            fields = ", ".join(".".join(map(str, e["loc"])) for e in exc.errors())
            print(f"配置校验失败，请核对这些字段：{fields}")
        else:
            print(f"未发送请求：{exc}")
        return 2
    except (EOFError, KeyboardInterrupt):
        print("\n已取消。")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
