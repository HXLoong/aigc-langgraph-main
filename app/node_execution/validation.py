"""从现有 State 派生严格的 JSON 边界，不给可选 State 字段填默认值。"""

from __future__ import annotations

import functools
import operator
import types
from typing import (
    Annotated,
    Any,
    Literal,
    NotRequired,
    Required,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from pydantic import BaseModel, ConfigDict, TypeAdapter, create_model
from typing_extensions import TypedDict, is_typeddict


@functools.cache
def wire_type(schema: Any) -> Any:
    """去掉 reducer 元数据，兼容 Python 3.11 的 stdlib TypedDict。"""
    origin, args = get_origin(schema), get_args(schema)
    if origin in (Annotated, Required, NotRequired):
        return wire_type(args[0])
    if is_typeddict(schema):
        fields = {
            key: Required[wire_type(value)]
            if key in schema.__required_keys__
            else NotRequired[wire_type(value)]
            for key, value in get_type_hints(schema, include_extras=True).items()
        }
        result = TypedDict(f"{schema.__name__}Input", fields)  # type: ignore[misc]
        result.__pydantic_config__ = ConfigDict(extra="forbid", strict=True)  # type: ignore[attr-defined]
        return result
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return create_model(
            f"{schema.__name__}Input",
            __base__=schema,
            __config__=ConfigDict(extra="forbid", strict=True),
        )
    if origin in (Union, types.UnionType):
        return functools.reduce(operator.or_, (wire_type(a) for a in args))
    if origin is not None and origin is not Literal:
        return origin[tuple(wire_type(a) for a in args)]
    return schema


@functools.cache
def state_adapter(schema: Any) -> TypeAdapter[Any]:
    return TypeAdapter(wire_type(schema))
