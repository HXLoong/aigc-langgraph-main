"""GOATS / OTC 后端鉴权工具。"""
from __future__ import annotations

import hashlib
import hmac
import time


def get_goats_auth_headers() -> dict[str, str]:
    """生成 GOATS 签名鉴权头。

    签名算法：HMAC-SHA256(client_id + timestamp + client_secret + extapp_salt)
    """
    from app.config import get_settings
    settings = get_settings()
    client_id = settings.goats_client_id
    client_secret = settings.goats_client_secret
    extapp_salt = settings.goats_extapp_salt

    if not client_id or not client_secret:
        return {}

    ts = str(int(time.time() * 1000))
    raw = client_id + ts + client_secret + extapp_salt
    sign = hmac.new(
        client_secret.encode("utf-8"),
        raw.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return {
        "x-goats-clientid": client_id,
        "x-goats-timestamp": ts,
        "x-goats-signature": sign,
    }
