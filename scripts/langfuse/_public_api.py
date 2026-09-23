"""Langfuse Public API 的最小同步客户端。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_dotenv() -> None:
    dotenv = PROJECT_ROOT / ".env"
    if not dotenv.exists():
        return
    for line in dotenv.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().split("#", 1)[0].strip()


class LangfusePublicApi:
    def __init__(
        self,
        *,
        base_url: str,
        public_key: str,
        secret_key: str,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = (public_key, secret_key)
        self._client = client or httpx.Client(timeout=30)

    @classmethod
    def from_env(cls) -> LangfusePublicApi:
        load_dotenv()
        public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
        secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")
        if not public_key or not secret_key:
            raise RuntimeError("缺少 LANGFUSE_PUBLIC_KEY 或 LANGFUSE_SECRET_KEY")
        base_url = os.environ.get(
            "LANGFUSE_BASE_URL",
            os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
        return cls(
            base_url=base_url,
            public_key=public_key,
            secret_key=secret_key,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self._client.request(
            method,
            f"{self._base_url}{path}",
            auth=self._auth,
            params=params,
            json=json,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Langfuse API {method} {path} 失败："
                f"{response.status_code} {response.text[:300]}"
            ) from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Langfuse API {method} {path} 返回的不是 JSON 对象")
        return payload

    def get_dataset(self, name: str) -> dict[str, Any]:
        return self._request("GET", f"/api/public/v2/datasets/{quote(name, safe='')}")

    def _list_cursor(self, path: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            payload = self._request("GET", path, params=params)
            items.extend(item for item in payload.get("data", []) if isinstance(item, dict))
            cursor = payload.get("meta", {}).get("cursor")
            if not cursor:
                return items

    def list_evaluators(self) -> list[dict[str, Any]]:
        return self._list_cursor("/api/public/v2/evaluators")

    def create_evaluator(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/public/v2/evaluators", json=payload)

    def update_evaluator(
        self, evaluator_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/api/public/v2/evaluators/{quote(evaluator_id, safe='')}",
            json=payload,
        )

    def list_evaluation_rules(self) -> list[dict[str, Any]]:
        return self._list_cursor("/api/public/v2/evaluation-rules")

    def create_evaluation_rule(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/public/v2/evaluation-rules", json=payload)

    def update_evaluation_rule(
        self, rule_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/api/public/v2/evaluation-rules/{quote(rule_id, safe='')}",
            json=payload,
        )

    def list_score_configs(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            payload = self._request(
                "GET",
                "/api/public/score-configs",
                params={"page": page, "limit": 100},
            )
            data = [item for item in payload.get("data", []) if isinstance(item, dict)]
            items.extend(data)
            meta = payload.get("meta", {})
            if page >= int(meta.get("totalPages") or page) or not data:
                return items
            page += 1

    def create_score_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/public/score-configs", json=payload)

    def update_score_config(
        self, config_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/api/public/score-configs/{quote(config_id, safe='')}",
            json=payload,
        )
