"""去 LLM 化节点的守护：模块不得再持有任何 LLM 工厂符号。

旧写法 `monkeypatch.setattr(module, "get_qwen_thinking", _forbid, raising=False)` 在目标
模块根本没有该名字时只是新建一个没人读的属性，守卫形同虚设；`raising=False` 把"目标不存在"
这一信号吞掉了。这里改为两层：先断言模块没有导入任何 LLM 工厂（结构性证据），再把仍存在的
工厂替换为一调用即失败的桩（行为性证据）。
"""
from __future__ import annotations

from types import ModuleType
from typing import Any

import pytest

LLM_FACTORY_PREFIXES: tuple[str, ...] = ("get_qwen_", "get_standard_llm", "get_deepseek")


def llm_factory_names(module: ModuleType) -> list[str]:
    return sorted(name for name in vars(module) if name.startswith(LLM_FACTORY_PREFIXES))


def forbid_llm(monkeypatch: pytest.MonkeyPatch, *modules: ModuleType) -> None:
    """断言去 LLM 化模块没有 LLM 工厂；若有，替换为调用即失败的桩并让测试失败可见。"""

    def _forbid(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("去 LLM 化节点不应调用 LLM")

    for module in modules:
        names = llm_factory_names(module)
        for name in names:
            monkeypatch.setattr(module, name, _forbid)
        assert not names, f"{module.__name__} 已去 LLM 化，不应再导入 LLM 工厂: {names}"
