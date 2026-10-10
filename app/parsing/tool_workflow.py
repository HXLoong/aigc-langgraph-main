"""独立模型工具的结构化调用和并行错误合并。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, TypeVar

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel

from app.graph.state import ErrorInfo
from app.llm.clients import ModelOutputCapacityError, get_llm_instrument_tool
from app.prompts.spec import PromptSpec

StateT = TypeVar("StateT", bound=Mapping[str, Any])
OutputT = TypeVar("OutputT", bound=BaseModel)


def merge_tool_errors(left: ErrorInfo | None, right: ErrorInfo | None) -> ErrorInfo | None:
    """safe_node 错误并行归并，保留各分支节点、类型、原因和堆栈。"""
    if left is None:
        return right
    if right is None:
        return left
    return ErrorInfo(
        node=f"{left.node}, {right.node}",
        type=f"{left.type}, {right.type}",
        message=f"{left.message}; {right.message}",
        traceback=f"{left.traceback or ''}\n{right.traceback or ''}",
    )


def parse_list(value: str) -> list[Any]:
    """与 YAML 一致：损坏 JSON 或非列表输入回退空列表。"""
    try:
        result = json.loads(value)
    except (ValueError, TypeError):
        return []
    return result if isinstance(result, list) else []


async def invoke_tool_model(
    spec: PromptSpec[StateT],
    state: StateT,
    output_model: type[OutputT],
    config: RunnableConfig,
) -> OutputT:
    """一次结构化请求；解析错误与截断均失败，不修复、不降级为空结果。"""
    messages, _ = spec.build_messages(state)
    response = (
        await get_llm_instrument_tool()
        .with_structured_output(
            output_model,
            method="function_calling",
            include_raw=True,
        )
        .ainvoke(messages, config=config)
    )
    if not isinstance(response, dict):
        raise ValueError("结构化响应缺少原始消息与解析结果")
    raw = response.get("raw")
    if getattr(raw, "response_metadata", {}).get("finish_reason") == "length":
        raise ModelOutputCapacityError("模型输出超出单次解析容量")
    if response.get("parsing_error") is not None:
        raise ValueError(f"结构化解析失败: {response['parsing_error']}")
    parsed = response.get("parsed")
    if not isinstance(parsed, output_model):
        raise ValueError("结构化解析结果缺失或类型错误")
    return parsed
