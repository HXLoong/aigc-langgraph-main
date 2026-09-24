#!/usr/bin/env python3
"""Inspect one uncertain message; --apply persists verified original Java replies only."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.storage.idempotency import MySQLIdempotencyStore  # noqa: E402
from app.storage.reconciliation import JavaAuditReader, reconcile_request  # noqa: E402
from app.config import get_settings  # noqa: E402

logger = logging.getLogger(__name__)


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if urlsplit(settings.mysql_uri).hostname not in {"localhost", "127.0.0.1", "::1"}:
        logger.error("reconciliation_failed error_type=NonLocalDatabase")
        return 2
    store = MySQLIdempotencyStore(settings.mysql_uri)
    reader = JavaAuditReader(settings.mysql_uri)
    try:
        async with asyncio.timeout(settings.request_timeout_seconds):
            result = await reconcile_request(
                store, reader, args.message_id, user_id=args.user_id, room_id=args.room_id,
                apply=args.apply,
            )
    except Exception as exc:  # noqa: BLE001 - no credentials, raw requests or responses in CLI logs
        logger.error("reconciliation_failed error_type=%s", type(exc).__name__)
        return 2
    logger.info("reconciliation=%s", json.dumps(asdict(result), ensure_ascii=False))
    return 0 if result.outcome in {"response_found", "already_done"} else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--message-id", required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--room-id", required=True)
    parser.add_argument("--apply", action="store_true", help="更新仍未完成的幂等记录；默认仅检查")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
