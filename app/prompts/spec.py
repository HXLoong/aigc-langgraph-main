"""提示词即代码（ADR 0023）：PromptSpec 把一个 LLM 节点的提示词契约声明为代码对象。

一个节点 = 一个 PromptSpec：
- `inputs`        读取的 AgentState 字段（构造时校验必须存在于 AgentState，改 State 就会红）
- `output_model`  with_structured_output 的 Pydantic 模型——输出契约的唯一真源，
                  字段语义写在 Field(description=...)，通过 function calling schema 下发；
                  提示词正文不再维护 JSON 骨架 / 字段表
- `injects`       system 段里由代码渲染的 `{{var}}` 占位符 → 渲染器（AgentState → str），
                  登记的占位符必须在 `.md` system 段真实存在（构造期校验）
- `user_builder`  AgentState → user 消息（规则文本只能住在 .md，代码只拼变量）
- `gray`          是否走 `_versions.yaml` 灰度（resolve_prompt_version）

注册表 `all_specs()` 供测试交叉核对 AgentState / 输出契约。
"""
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, get_type_hints

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from app.graph.state import AgentState
from app.prompts import load_prompt, resolve_prompt_version

Renderer = Callable[[AgentState], str]

_REGISTRY: dict[str, PromptSpec] = {}


def _agent_state_fields() -> frozenset[str]:
    return frozenset(get_type_hints(AgentState))


@dataclass(frozen=True)
class PromptSpec:
    category: str
    name: str
    output_model: type[BaseModel] | None
    inputs: tuple[str, ...]
    user_builder: Renderer
    injects: Mapping[str, Renderer] = field(default_factory=dict)
    gray: bool = False

    def __post_init__(self) -> None:
        unknown = set(self.inputs) - _agent_state_fields()
        if unknown:
            raise ValueError(f"{self.key} 的 inputs 不在 AgentState 中：{sorted(unknown)}")

    @property
    def key(self) -> str:
        return f"{self.category}/{self.name}"

    def resolve_name(self, state: AgentState) -> str:
        if not self.gray:
            return self.name
        return resolve_prompt_version(self.category, self.name, state.get("conversation_id"))

    def render_system(self, state: AgentState) -> tuple[str, str]:
        """(渲染后的 system, 实际加载的 prompt name)。占位符不在 system 里即视为契约错误。"""
        prompt_name = self.resolve_name(state)
        system = load_prompt(self.category, prompt_name).system
        for placeholder, renderer in self.injects.items():
            if placeholder not in system:
                raise ValueError(f"{self.key}（{prompt_name}）的 system 中不存在占位符 {placeholder}")
            system = system.replace(placeholder, renderer(state))
        return system, prompt_name

    def build_messages(self, state: AgentState) -> tuple[list[tuple[str, str]], str]:
        system, prompt_name = self.render_system(state)
        return [("system", system), ("user", self.user_builder(state))], prompt_name


def register(spec: PromptSpec) -> PromptSpec:
    """模块导入时登记；同一 key 重复登记视为编程错误（两个节点抢同一提示词）。"""
    existing = _REGISTRY.get(spec.key)
    if existing is not None and existing is not spec:
        raise ValueError(f"PromptSpec 重复登记：{spec.key}")
    _REGISTRY[spec.key] = spec
    return spec


def all_specs() -> dict[str, PromptSpec]:
    return dict(_REGISTRY)


def iter_fields(model: type[BaseModel] | None) -> Iterator[tuple[type[BaseModel], FieldInfo, str]]:
    """递归遍历模型（含 list[SubModel] 元素）的全部字段：(所属模型, FieldInfo, 字段名)。"""
    if model is None:
        return
    seen: set[type[BaseModel]] = set()

    def _walk(m: type[BaseModel]) -> Iterator[tuple[type[BaseModel], FieldInfo, str]]:
        if m in seen:
            return
        seen.add(m)
        for fname, finfo in m.model_fields.items():
            yield m, finfo, fname
            for sub in _nested_models(finfo.annotation):
                yield from _walk(sub)

    yield from _walk(model)


def _nested_models(annotation: Any) -> list[type[BaseModel]]:
    from typing import get_args

    found: list[type[BaseModel]] = []
    stack = [annotation]
    while stack:
        ann = stack.pop()
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            found.append(ann)
        else:
            stack.extend(get_args(ann))
    return found


__all__ = ["PromptSpec", "Renderer", "all_specs", "iter_fields", "register"]
