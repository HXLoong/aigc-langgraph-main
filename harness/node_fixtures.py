"""节点级人工标注 fixture 的 JSONL 持久化。"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harness.node_annotations import (
    NodeDefinition,
    NodeObservation,
    definition_for_observation,
)

_WRITE_LOCK = threading.RLock()

_SENSITIVE_KEY_SUFFIXES = (
    "apikey",
    "authorization",
    "cookie",
    "password",
    "privatekey",
    "secret",
    "secretkey",
    "accesstoken",
    "refreshtoken",
)
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{7,}\b"),
    re.compile(
        r"(?i)\b[A-Za-z0-9_-]*(?:api[_-]?key|secret|cookie|authorization|"
        r"access[_-]?token|refresh[_-]?token|password)\s*[:=]\s*[^\s,;]+"
    ),
)


def _pointer_root(pointer: str) -> str:
    """返回 JSON Pointer 的首层字段名。"""
    if not pointer.startswith("/") or pointer == "/":
        raise NodeFixtureError(f"输出字段必须使用 JSON Pointer：{pointer}")
    return pointer[1:].split("/", maxsplit=1)[0].replace("~1", "/").replace("~0", "~")


def _is_observed_output_pointer(output: Mapping[str, Any], pointer: str) -> bool:
    """只允许标注本次节点实际输出中存在的非内部路径。"""
    root = _pointer_root(pointer)
    if root == "trace" or root.startswith("_"):
        return False
    current: Any = output
    for raw_token in pointer[1:].split("/"):
        if re.search(r"~(?![01])", raw_token):
            return False
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                return False
            current = current[token]
        elif isinstance(current, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", token) or int(token) >= len(current):
                return False
            current = current[int(token)]
        else:
            return False
    return True


class NodeFixtureError(ValueError):
    """节点 fixture 请求或文件内容不合法。"""


def _normalized_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _sensitive_path(value: Any, path: str = "$") -> str | None:
    """返回首个敏感字段路径；fixture 必须 fail-closed，不能用脱敏值回放节点。"""
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_path = f"{path}.{key}"
            normalized = _normalized_key(key)
            if item not in (None, "") and normalized.endswith(_SENSITIVE_KEY_SUFFIXES):
                return key_path
            found = _sensitive_path(item, key_path)
            if found:
                return found
        return None
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found = _sensitive_path(item, f"{path}[{index}]")
            if found:
                return found
        return None
    if isinstance(value, str) and any(
        pattern.search(value) for pattern in _SENSITIVE_VALUE_PATTERNS
    ):
        return path
    return None


class NodeFixtureStore:
    """按产品和节点维护一行一条记录的节点级 JSONL。"""

    def __init__(
        self,
        root: Path,
        *,
        registry: Mapping[str, NodeDefinition],
    ) -> None:
        self.root = root
        self.registry = registry

    def save(
        self,
        observation: NodeObservation,
        *,
        case_id: str,
        annotator: str,
        mode: str,
        expected_fields: Mapping[str, Any] | None = None,
        expected_object: Mapping[str, Any] | None = None,
    ) -> Path:
        definition = definition_for_observation(observation, self.registry)
        if not definition.annotatable:
            reason = definition.annotation_reason or "没有稳定业务输出"
            raise NodeFixtureError(f"该节点仅支持查看，不能保存标注：{reason}")
        if mode == "fields":
            fields = dict(expected_fields or {})
            if not fields:
                raise NodeFixtureError("字段级标注至少需要一个期望字段")
            invalid = sorted(
                pointer
                for pointer in fields
                if not _is_observed_output_pointer(observation.output, str(pointer))
            )
            if invalid:
                raise NodeFixtureError(
                    f"不允许标注的输出字段：{', '.join(str(item) for item in invalid)}"
                )
            expected: dict[str, Any] = {"mode": "fields", "fields": fields}
        elif mode == "object":
            source = dict(expected_object or {})
            expected = {
                "mode": "object",
                "value": {
                    field: source[field]
                    for field in definition.output_fields
                    if field in source
                },
            }
        else:
            raise NodeFixtureError(f"不支持的标注模式：{mode}")

        projected_input = {
            field: observation.input[field]
            for field in definition.input_fields
            if field in observation.input
        }
        fixture_id = (
            f"{observation.name}-{case_id}-t{observation.turn}-"
            f"{observation.observation_id[:12]}"
        )
        record = {
            "schema_version": 1,
            "id": fixture_id,
            "product_type": definition.product_type,
            "node_name": definition.name,
            "source": {
                "case_id": case_id,
                "trace_id": observation.trace_id,
                "observation_id": observation.observation_id,
                "turn": observation.turn,
            },
            "input": projected_input,
            "expected": expected,
            "replay": {
                "enabled": definition.replayable,
                "side_effect": definition.side_effect,
            },
            "annotation": {
                "status": "completed",
                "annotator": annotator,
                "updated_at": datetime.now(UTC).isoformat(),
            },
        }
        sensitive_path = _sensitive_path(record)
        if sensitive_path:
            raise NodeFixtureError(
                f"节点用例包含敏感信息，已拒绝保存：{sensitive_path}"
            )
        path = self.root / definition.product_type / f"{definition.name}.jsonl"
        with _WRITE_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            records = self._read(path)
            for index, existing in enumerate(records):
                existing_source = existing.get("source")
                if (
                    isinstance(existing_source, dict)
                    and existing_source.get("observation_id") == observation.observation_id
                ):
                    records[index] = record
                    break
            else:
                records.append(record)
            content = "".join(
                json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n"
                for item in records
            )
            temporary: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=path.parent,
                    prefix=f".{path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    temporary = Path(handle.name)
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                temporary.replace(path)
            finally:
                if temporary is not None and temporary.exists():
                    temporary.unlink()
        return path

    @staticmethod
    def _read(path: Path) -> list[dict[str, Any]]:
        if not path.is_file():
            return []
        records: list[dict[str, Any]] = []
        for line_number, raw_line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not raw_line.strip():
                continue
            try:
                value = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise NodeFixtureError(f"{path}:{line_number} 不是合法 JSON") from exc
            if not isinstance(value, dict):
                raise NodeFixtureError(f"{path}:{line_number} 必须是 JSON 对象")
            records.append(value)
        return records


__all__ = ["NodeFixtureError", "NodeFixtureStore"]
