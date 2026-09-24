"""app/ 分层依赖守护：禁止下层依赖上层、子图之间互相依赖（结构说明见 docs/architecture/README.md）。

规则按包（子图按 app.subgraphs.<产品>）统计模块内全部 `from app... import`，
含函数内延迟导入，不含 `if TYPE_CHECKING:` 下的纯类型导入。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1] / "app"

#: 包 → 只允许依赖的 app 内包（未列出的包不受白名单约束，由下方黑名单约束）
_ALLOWED: dict[str, set[str]] = {
    "domain": {"extraction"},
    "extraction": {"wire_model"},
    "storage": {"config"},
    "llm": {"config"},
    "tools": {"config", "domain", "observability", "wire_model"},
    "prompts": {"config", "extraction", "graph"},
    "subgraphs.common": {"graph"},
}

#: 包 → 禁止依赖的 app 内包（前缀匹配，subgraphs 覆盖三个子图）
_FORBIDDEN: dict[str, tuple[str, ...]] = {
    "nodes": ("subgraphs", "api", "node_execution"),
    "api": ("subgraphs",),
    "subgraphs.swap": ("subgraphs.option", "subgraphs.close", "nodes", "api", "node_execution", "storage"),
    "subgraphs.option": ("subgraphs.swap", "subgraphs.close", "nodes", "api", "node_execution", "storage"),
    "subgraphs.close": ("subgraphs.swap", "subgraphs.option", "nodes", "api", "node_execution", "storage"),
}

#: graph 包除主图组装入口外都是基础设施，不得依赖业务节点
_GRAPH_ASSEMBLY = "app.graph.main"


def _package(module: str) -> str:
    parts = module.split(".")
    if len(parts) > 2 and parts[1] == "subgraphs":
        return "subgraphs." + parts[2]
    return parts[1]


def _imports() -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for path in _APP.rglob("*.py"):
        module = ".".join(path.relative_to(_APP.parent).with_suffix("").parts)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        type_only = {
            id(node)
            for block in ast.walk(tree)
            if isinstance(block, ast.If) and getattr(block.test, "id", "") == "TYPE_CHECKING"
            for node in ast.walk(block)
        }
        result[module] = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
            and node.module.startswith("app.") and id(node) not in type_only
        }
    return result


_IMPORTS = _imports()


@pytest.mark.parametrize("package", sorted(_ALLOWED))
def test_lower_layers_only_depend_on_allowed_packages(package: str) -> None:
    violations = sorted(
        f"{module} → {target}"
        for module, targets in _IMPORTS.items() if _package(module) == package
        for target in targets
        if _package(target) != package and _package(target) not in _ALLOWED[package]
    )
    assert violations == []


@pytest.mark.parametrize("package", sorted(_FORBIDDEN))
def test_forbidden_upward_or_sideways_imports(package: str) -> None:
    violations = sorted(
        f"{module} → {target}"
        for module, targets in _IMPORTS.items() if _package(module) == package
        for target in targets
        if _package(target).startswith(_FORBIDDEN[package])
    )
    assert violations == []


def test_graph_infrastructure_does_not_depend_on_business_nodes() -> None:
    violations = sorted(
        f"{module} → {target}"
        for module, targets in _IMPORTS.items()
        if _package(module) == "graph" and module != _GRAPH_ASSEMBLY
        for target in targets
        if _package(target).startswith(("nodes", "subgraphs", "api", "node_execution"))
    )
    assert violations == []
