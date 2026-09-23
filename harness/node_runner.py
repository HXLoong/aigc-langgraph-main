"""从节点 fixture 直接调用单个 LangGraph 节点。"""

from __future__ import annotations

import importlib
import inspect
import json
from collections.abc import Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from harness.node_annotations import NodeDefinition
from harness.node_mocks import NodeMockError, mock_node_dependencies


class NodeRunnerError(ValueError):
    """节点 fixture 无法安全执行。"""


class NodeFixtureSkipError(NodeRunnerError):
    """节点 fixture 被安全策略跳过，不应计为回归失败。"""


@dataclass(frozen=True, slots=True)
class NodeFieldDiff:
    path: str
    expected: Any
    actual: Any


@dataclass(frozen=True, slots=True)
class NodeRunResult:
    fixture_id: str
    node_name: str
    passed: bool
    actual: dict[str, Any]
    diffs: list[NodeFieldDiff] = field(default_factory=list)


def _load_callable(path: str) -> Any:
    module_name, separator, attribute = path.partition(":")
    if not separator or not module_name or not attribute:
        raise NodeRunnerError(f"节点 callable_path 不合法：{path}")
    module = importlib.import_module(module_name)
    function = getattr(module, attribute, None)
    if not callable(function):
        raise NodeRunnerError(f"节点函数不存在：{path}")
    return function


def _resolve_pointer(value: Any, pointer: str) -> Any:
    if pointer in {"", "/"}:
        return value
    if not pointer.startswith("/"):
        raise NodeRunnerError(f"JSON Pointer 必须以 / 开头：{pointer}")
    current = value
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                raise KeyError(pointer)
            current = current[token]
        elif isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError) as exc:
                raise KeyError(pointer) from exc
        else:
            raise KeyError(pointer)
    return current


def _jsonable(value: Any) -> Any:
    """递归转换 Pydantic 等节点输出，确保报告可直接写成 JSON。"""
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _jsonable(model_dump(mode="json", by_alias=True))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _replayable_definition(
    fixture: Mapping[str, Any], registry: Mapping[str, NodeDefinition]
) -> tuple[str, NodeDefinition]:
    node_name = str(fixture.get("node_name") or "")
    replay = fixture.get("replay")
    if not isinstance(replay, Mapping) or replay.get("enabled") is not True:
        raise NodeFixtureSkipError(f"节点 fixture 禁止回放：{node_name}")
    definition = registry.get(node_name)
    if definition is None:
        raise NodeRunnerError(f"节点未注册：{node_name}")
    if not definition.replayable or definition.side_effect == "write":
        raise NodeRunnerError(f"节点存在写副作用，禁止回放：{node_name}")
    return node_name, definition


def _compare_output(
    fixture: Mapping[str, Any], definition: NodeDefinition, actual: dict[str, Any]
) -> NodeRunResult:
    expected = fixture.get("expected")
    if not isinstance(expected, Mapping):
        raise NodeRunnerError("节点 fixture expected 必须是对象")
    diffs: list[NodeFieldDiff] = []
    mode = expected.get("mode")
    if mode == "fields":
        fields = expected.get("fields")
        if not isinstance(fields, Mapping) or not fields:
            raise NodeRunnerError("字段级 fixture 至少需要一个断言")
        for pointer, expected_value in fields.items():
            try:
                actual_value = _resolve_pointer(actual, str(pointer))
            except KeyError:
                actual_value = None
            if actual_value != expected_value:
                diffs.append(
                    NodeFieldDiff(
                        path=str(pointer),
                        expected=expected_value,
                        actual=actual_value,
                    )
                )
    elif mode == "object":
        expected_value = expected.get("value")
        comparable_actual = {
            output_field: actual[output_field]
            for output_field in definition.output_fields
            if output_field in actual
        }
        if comparable_actual != expected_value:
            diffs.append(NodeFieldDiff(path="/", expected=expected_value, actual=comparable_actual))
    else:
        raise NodeRunnerError(f"不支持的断言模式：{mode}")

    return NodeRunResult(
        fixture_id=str(fixture.get("id") or ""),
        node_name=definition.name,
        passed=not diffs,
        actual=actual,
        diffs=diffs,
    )


async def run_node_fixture(
    fixture: Mapping[str, Any],
    *,
    registry: Mapping[str, NodeDefinition],
    mock_external: bool = False,
) -> NodeRunResult:
    """执行一个明确标记为安全可回放的节点 fixture。"""
    node_name, definition = _replayable_definition(fixture, registry)
    if not definition.callable_path:
        raise NodeRunnerError(f"节点尚未配置单节点执行入口：{node_name}")

    state = fixture.get("input")
    if not isinstance(state, Mapping):
        raise NodeRunnerError("节点 fixture input 必须是对象")
    node = _load_callable(definition.callable_path)
    context = (
        mock_node_dependencies(node_name, fixture.get("mocks")) if mock_external else nullcontext()
    )
    try:
        with context:
            invoked = node(dict(state))
            actual_value = await invoked if inspect.isawaitable(invoked) else invoked
    except NodeMockError as exc:
        raise NodeRunnerError(str(exc)) from exc
    if not isinstance(actual_value, Mapping):
        raise NodeRunnerError(f"节点输出必须是对象：{node_name}")
    actual = _jsonable(dict(actual_value))

    return _compare_output(fixture, definition, actual)


async def run_node_fixture_http(
    fixture: Mapping[str, Any],
    *,
    registry: Mapping[str, NodeDefinition],
    client: httpx.AsyncClient,
    api_key: str,
) -> NodeRunResult:
    """通过受保护的 FastAPI 节点执行面回放 fixture。"""
    node_name, definition = _replayable_definition(fixture, registry)
    state = fixture.get("input")
    if not isinstance(state, Mapping):
        raise NodeRunnerError("节点 fixture input 必须是对象")
    product = "main" if definition.product_type == "common" else definition.product_type
    headers = {"X-Node-Run-Key": api_key}
    try:
        prepare = await client.post(
            "/v1/nodes/prepare",
            headers=headers,
            json={"product": product, "node": node_name, "langfuse_input": dict(state)},
        )
    except httpx.RequestError as exc:
        raise NodeRunnerError(f"节点接口连接失败：{exc}") from exc
    if prepare.status_code != 200:
        raise NodeRunnerError(
            f"节点输入准备失败 HTTP {prepare.status_code}: {_response_detail(prepare)}"
        )
    prepared_request = prepare.json().get("request")
    prepared = prepared_request.get("state") if isinstance(prepared_request, dict) else None
    if not isinstance(prepared, dict):
        raise NodeRunnerError("节点输入准备响应缺少 state 对象")
    try:
        response = await client.post(
            "/v1/nodes/run",
            headers=headers,
            json={"product": product, "node": node_name, "state": prepared},
        )
    except httpx.RequestError as exc:
        raise NodeRunnerError(f"节点接口连接失败：{exc}") from exc
    if response.status_code != 200:
        raise NodeRunnerError(
            f"节点执行失败 HTTP {response.status_code}: {_response_detail(response)}"
        )
    actual_value = response.json().get("output")
    if not isinstance(actual_value, Mapping):
        raise NodeRunnerError(f"节点输出必须是对象：{node_name}")
    return _compare_output(fixture, definition, _jsonable(dict(actual_value)))


def _response_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(body, dict):
        return str(body.get("detail") or body.get("error") or body)[:300]
    return str(body)[:300]


def load_node_fixtures(paths: Sequence[Path]) -> list[dict[str, Any]]:
    """从文件或目录递归加载节点 JSONL fixture。"""
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.rglob("*.jsonl")))
        elif path.is_file() and path.suffix.lower() == ".jsonl":
            files.append(path)
        else:
            raise NodeRunnerError(f"节点 fixture 路径不存在或不是 JSONL：{path}")

    fixtures: list[dict[str, Any]] = []
    for path in files:
        for line_number, raw_line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not raw_line.strip():
                continue
            try:
                fixture = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise NodeRunnerError(f"{path}:{line_number} 不是合法 JSON") from exc
            if not isinstance(fixture, dict):
                raise NodeRunnerError(f"{path}:{line_number} 必须是 JSON 对象")
            fixtures.append(fixture)
    return fixtures


__all__ = [
    "NodeFieldDiff",
    "NodeRunResult",
    "NodeRunnerError",
    "NodeFixtureSkipError",
    "load_node_fixtures",
    "run_node_fixture",
    "run_node_fixture_http",
]
