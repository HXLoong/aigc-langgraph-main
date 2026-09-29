"""节点回归只模拟唯一解析节点的模型出口，确定性节点直接执行。"""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch


class NodeMockError(ValueError):
    """节点样本未提供可执行的外部依赖输出。"""


class _StructuredResult:
    """保留生产结构化校验，仅替换模型响应。"""

    def __init__(self, value: Any) -> None:
        """保存样本中的明确输出，模型类型由实际 PromptSpec 决定。"""
        self.value = value

    async def ainvoke(self, messages: Any) -> Any:
        """返回样本输出，不请求真实模型。"""
        return self.value

    def with_structured_output(self, model: Any) -> _StructuredResult:
        """由生产节点负责输出契约校验，mock 不补默认字段。"""
        return self


@contextmanager
def mock_node_dependencies(node_name: str, payload: Any) -> Iterator[None]:
    """只为 parse_instruction 提供模型出口；其它节点没有隐藏模型分支。"""
    if node_name != "parse_instruction":
        raise NodeMockError(f"节点没有模型 mock 适配器：{node_name}")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("llm_output"), Mapping):
        raise NodeMockError("mock 配置缺少 mocks.llm_output")
    with patch("app.nodes.parse_instruction.get_llm_standard", return_value=_StructuredResult(dict(payload["llm_output"]))):
        yield


__all__ = ["NodeMockError", "mock_node_dependencies"]
