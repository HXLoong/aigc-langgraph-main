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
