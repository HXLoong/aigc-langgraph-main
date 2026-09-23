"""节点回归的外部依赖 mock；只在 harness 显式 mock 模式中使用。"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from pydantic import ValidationError


class NodeMockError(ValueError):
    """节点 fixture 的 mock 配置无效或尚未支持。"""


class _StructuredResult:
    def __init__(self, value: Any) -> None:
        self.value = value

    async def ainvoke(self, _messages: Any) -> Any:
        return self.value


class _StructuredModel:
    def __init__(self, value: Any) -> None:
        self.value = value

    def with_structured_output(self, _model: Any) -> _StructuredResult:
        return _StructuredResult(self.value)


def _required_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise NodeMockError(f"mock 配置缺少对象字段：{field}")
    return dict(value)


@contextmanager
def mock_node_dependencies(
    node_name: str,
    payload: Any,
) -> Iterator[None]:
    """按节点 patch 实际引用位置，只隔离 LLM / 后端等外部依赖。"""
    if node_name != "swap_place_order":
        raise NodeMockError(f"节点尚未提供 mock 适配器：{node_name}")

    mocks = _required_mapping(payload, "mocks")
    llm_output = _required_mapping(mocks.get("llm_output"), "mocks.llm_output")
    from app import config as config_module
    from app.graph import retry as retry_module
    from app.subgraphs.swap import place_order as place_order_module
    from app.subgraphs.swap.place_order import CANDIDATE_MODEL

    try:
        candidates = CANDIDATE_MODEL.model_validate(llm_output)
    except (TypeError, ValidationError) as exc:
        raise NodeMockError(f"swap_place_order mock 数据不合法：{exc}") from exc

    with (
        patch.object(
            place_order_module,
            "get_qwen_complex",
            return_value=_StructuredModel(candidates),
        ),
        patch.object(
            retry_module,
            "get_settings",
            return_value=SimpleNamespace(
                node_retry_max_attempts=1,
                node_retry_initial_interval_seconds=0.01,
            ),
        ),
        patch.object(
            config_module,
            "get_settings",
            return_value=SimpleNamespace(
                enable_langfuse=False,
                use_langfuse_prompts=False,
                environment="test",
            ),
        ),
    ):
        yield


__all__ = ["NodeMockError", "mock_node_dependencies"]
