"""读取 Langfuse 本地资源定义文件。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_definition_files(directory: Path) -> list[tuple[Path, dict[str, Any]]]:
    if not directory.is_dir():
        raise RuntimeError(f"Langfuse 定义目录不存在：{directory}")

    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise RuntimeError(f"Langfuse 定义目录中没有 JSON：{directory}")

    definitions: list[tuple[Path, dict[str, Any]]] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Langfuse 定义不是有效 JSON：{path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"Langfuse 定义必须是 JSON 对象：{path}")
        definitions.append((path, payload))
    return definitions


def load_definition_list(path: Path, key: str) -> list[tuple[Path, dict[str, Any]]]:
    if not path.is_file():
        raise RuntimeError(f"Langfuse 定义文件不存在：{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Langfuse 定义不是有效 JSON：{path}: {exc}") from exc
    items = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise RuntimeError(f"Langfuse 定义字段 {key} 必须是对象数组：{path}")
    return [(path, item) for item in items]
