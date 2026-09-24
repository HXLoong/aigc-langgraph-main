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


def resolve_base_url(override: str | None = None) -> str | None:
    """命令行 > LANGFUSE_BASE_URL > LANGFUSE_HOST；都没有返回 None，由调用方决定是否报错。"""
    return (
        override
        or os.environ.get("LANGFUSE_BASE_URL")
        or os.environ.get("LANGFUSE_HOST")
        or None
    )


def missing_langfuse_config(base_url: str | None, *, require_base_url: bool) -> list[str]:
    """列出缺失的 Langfuse 连接配置（base URL 与两把密钥）。"""
    missing = [
        key for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY") if not os.environ.get(key)
    ]
    if require_base_url and not base_url:
        missing.insert(0, "LANGFUSE_BASE_URL (or --base-url)")
    return missing


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
        base_url = resolve_base_url() or "http://127.0.0.1:3000"
        return cls(
            base_url=base_url,
            public_key=public_key,
            secret_key=secret_key,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> LangfusePublicApi:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
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
        return response

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = self._send(method, path, params=params, json=json).json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Langfuse API {method} {path} 返回的不是 JSON 对象")
        return payload

    def get_dataset(self, name: str) -> dict[str, Any]:
        return self._request("GET", f"/api/public/v2/datasets/{quote(name, safe='')}")

    def list_dataset_item_ids(self, dataset_name: str) -> list[str]:
        item_ids: list[str] = []
        page = 1
        while True:
            payload = self._request(
                "GET",
                "/api/public/dataset-items",
                params={"datasetName": dataset_name, "limit": 100, "page": page},
            )
            data = [item for item in payload.get("data", []) if isinstance(item, dict)]
            item_ids.extend(str(item["id"]) for item in data if item.get("id"))
            if len(data) < 100:
                return item_ids
            page += 1

    def delete_dataset_item(self, item_id: str) -> None:
        self._send("DELETE", f"/api/public/dataset-items/{quote(item_id, safe='')}")

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
