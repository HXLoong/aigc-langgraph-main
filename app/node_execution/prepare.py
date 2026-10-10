"""把 Langfuse 节点 State 清理为可提交给 `/v1/nodes/run` 的请求 State。"""

from __future__ import annotations

import copy
import json
import re
import types
from dataclasses import dataclass
from typing import (
    Annotated,
    Any,
    NotRequired,
    Required,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from pydantic import AliasChoices, AliasPath, BaseModel, TypeAdapter, ValidationError
from typing_extensions import is_typeddict

from app.node_execution.registry import NodeRegistration
from app.node_execution.validation import missing_node_context, state_adapter, wire_type

_INTEGER_RE = re.compile(r"[+-]?\d+")
_NONE_TYPE = type(None)


@dataclass(frozen=True)
class PrepareResult:
    state: dict[str, Any]
    dropped_fields: list[str]
    conversions: list[dict[str, str]]
    missing_fields: list[str]
    detail: list[dict[str, Any]]

    @property
    def valid(self) -> bool:
        return not self.detail and not self.missing_fields


@dataclass
class _Diagnostics:
    dropped_fields: list[str]
    conversions: list[dict[str, str]]


def prepare_state(
    registration: NodeRegistration, langfuse_input: dict[str, Any]
) -> PrepareResult:
    """无副作用地裁剪、转换并校验一个注册节点的输入。"""
    source = copy.deepcopy(langfuse_input)
    annotations = get_type_hints(registration.input_schema, include_extras=True)
    allowed = set(registration.effective_input_fields)
    diagnostics = _Diagnostics(dropped_fields=[], conversions=[])
    cleaned: dict[str, Any] = {}

    for key, value in source.items():
        if key not in annotations or key not in allowed:
            diagnostics.dropped_fields.append(key)
            continue
        cleaned[key] = _prepare_value(value, annotations[key], key, diagnostics)

    validation_detail: list[dict[str, Any]] = []
    try:
        state_adapter(registration.input_schema).validate_python(cleaned)
    except ValidationError as exc:
        for item in exc.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        ):
            validation_detail.append({**item, "loc": ["state", *item["loc"]]})

    validation_missing = [
        _loc_to_path(item["loc"][1:])
        for item in validation_detail
        if item["type"] == "missing"
    ]
    context_missing = missing_node_context(
        cleaned,
        required=registration.required,
        backend_context=registration.backend_context,
    )
    missing_fields = list(dict.fromkeys([*validation_missing, *context_missing]))
    for field in context_missing:
        validation_detail.append(
            {
                "loc": ["state", field],
                "type": "missing",
                "msg": "Required node context is missing or empty",
            }
        )

    return PrepareResult(
        state=cleaned,
        dropped_fields=diagnostics.dropped_fields,
        conversions=diagnostics.conversions,
        missing_fields=missing_fields,
        detail=_deduplicate_detail(validation_detail),
    )


def _prepare_value(
    value: Any,
    annotation: Any,
    path: str,
    diagnostics: _Diagnostics,
) -> Any:
    annotation = _unwrap(annotation)
    if annotation is Any:
        return value

    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        branch = _select_union_branch(value, get_args(annotation))
        return _prepare_value(value, branch, path, diagnostics)

    converted = _convert_scalar(value, annotation, path, diagnostics)
    if converted is not value:
        value = converted

    if _is_container_annotation(annotation) and isinstance(value, str):
        parsed = _parse_json_container(value, annotation)
        if parsed is not None:
            diagnostics.conversions.append(
                {
                    "field": path,
                    "from_type": "string",
                    "to_type": _json_type(parsed),
                    "rule": "json_string",
                }
            )
            value = parsed

    if is_typeddict(annotation) and isinstance(value, dict):
        hints = get_type_hints(annotation, include_extras=True)
        result: dict[str, Any] = {}
        for key, item in value.items():
            item_path = _child_path(path, key)
            if key not in hints:
                diagnostics.dropped_fields.append(item_path)
                continue
            result[key] = _prepare_value(item, hints[key], item_path, diagnostics)
        return result

    if isinstance(annotation, type) and issubclass(annotation, BaseModel) and isinstance(value, dict):
        accepted = _model_input_fields(annotation)
        result = {}
        for key, item in value.items():
            item_path = _child_path(path, key)
            field_info = accepted.get(key)
            if field_info is None:
                diagnostics.dropped_fields.append(item_path)
                continue
            result[key] = _prepare_value(item, field_info.annotation, item_path, diagnostics)
        return result

    if origin in (list, tuple, set, frozenset) and isinstance(value, list):
        args = get_args(annotation)
        item_type = args[0] if args else Any
        return [
            _prepare_value(item, item_type, f"{path}[{index}]", diagnostics)
            for index, item in enumerate(value)
        ]

    if origin is dict and isinstance(value, dict):
        key_type, value_type = get_args(annotation) or (Any, Any)
        if key_type is str and value_type is Any:
            return value
        return {
            key: _prepare_value(item, value_type, _child_path(path, key), diagnostics)
            for key, item in value.items()
        }

    return value


def _unwrap(annotation: Any) -> Any:
    while get_origin(annotation) in (Annotated, Required, NotRequired):
        annotation = get_args(annotation)[0]
    return annotation


def _select_union_branch(value: Any, branches: tuple[Any, ...]) -> Any:
    for branch in branches:
        unwrapped = _unwrap(branch)
        try:
            TypeAdapter(wire_type(unwrapped)).validate_python(value)
        except (ValidationError, TypeError):
            continue
        return unwrapped

    if isinstance(value, str):
        if _INTEGER_RE.fullmatch(value):
            integer = next((branch for branch in branches if _unwrap(branch) is int), None)
            if integer is not None:
                return _unwrap(integer)
        if value.strip().lower() in ("true", "false"):
            boolean = next((branch for branch in branches if _unwrap(branch) is bool), None)
            if boolean is not None:
                return _unwrap(boolean)
        container = next(
            (branch for branch in branches if _is_container_annotation(_unwrap(branch))),
            None,
        )
        if container is not None:
            return _unwrap(container)

    for branch in branches:
        unwrapped = _unwrap(branch)
        if value is None and unwrapped is _NONE_TYPE:
            return unwrapped
        if isinstance(value, dict) and _is_object_annotation(unwrapped):
            return unwrapped
        if isinstance(value, list) and _is_array_annotation(unwrapped):
            return unwrapped
    return _unwrap(next((branch for branch in branches if _unwrap(branch) is not _NONE_TYPE), branches[0]))


def _convert_scalar(
    value: Any,
    annotation: Any,
    path: str,
    diagnostics: _Diagnostics,
) -> Any:
    if annotation is int and isinstance(value, str) and _INTEGER_RE.fullmatch(value):
        diagnostics.conversions.append(
            {
                "field": path,
                "from_type": "string",
                "to_type": "integer",
                "rule": "integer_string",
            }
        )
        return int(value)
    if annotation is bool and isinstance(value, str) and value.strip().lower() in (
        "true",
        "false",
    ):
        diagnostics.conversions.append(
            {
                "field": path,
                "from_type": "string",
                "to_type": "boolean",
                "rule": "boolean_string",
            }
        )
        return value.strip().lower() == "true"
    return value


def _parse_json_container(value: str, annotation: Any) -> Any | None:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    if _is_object_annotation(annotation) and isinstance(parsed, dict):
        return parsed
    if _is_array_annotation(annotation) and isinstance(parsed, list):
        return parsed
    return None


def _is_container_annotation(annotation: Any) -> bool:
    return _is_object_annotation(annotation) or _is_array_annotation(annotation)


def _is_object_annotation(annotation: Any) -> bool:
    origin = get_origin(annotation)
    return (
        is_typeddict(annotation)
        or (isinstance(annotation, type) and issubclass(annotation, BaseModel))
        or origin is dict
    )


def _is_array_annotation(annotation: Any) -> bool:
    return get_origin(annotation) in (list, tuple, set, frozenset)


def _model_input_fields(model: type[BaseModel]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    populate_by_name = bool(
        model.model_config.get("populate_by_name") or model.model_config.get("validate_by_name")
    )
    for name, info in model.model_fields.items():
        if info.alias is None or populate_by_name:
            result[name] = info
        if isinstance(info.alias, str):
            result[info.alias] = info
        validation_alias = info.validation_alias
        if isinstance(validation_alias, str):
            result[validation_alias] = info
        elif isinstance(validation_alias, AliasChoices):
            for choice in validation_alias.choices:
                if isinstance(choice, str):
                    result[choice] = info
        elif isinstance(validation_alias, AliasPath) and len(validation_alias.path) == 1:
            key = validation_alias.path[0]
            if isinstance(key, str):
                result[key] = info
    return result


def _child_path(parent: str, key: Any) -> str:
    return f"{parent}.{key}"


def _json_type(value: Any) -> str:
    return "array" if isinstance(value, list) else "object"


def _loc_to_path(loc: list[Any] | tuple[Any, ...]) -> str:
    path = ""
    for part in loc:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}" if path else str(part)
    return path


def _deduplicate_detail(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[tuple[Any, ...], str]] = set()
    for item in items:
        key = (tuple(item["loc"]), item["type"])
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


__all__ = ["PrepareResult", "prepare_state"]
