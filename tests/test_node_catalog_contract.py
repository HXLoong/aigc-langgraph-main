"""应用执行与评测回放共享节点契约，保留各自的执行范围（#224）。"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from app.node_execution.executor import NodeExecutor
from app.node_execution.prepare import prepare_state
from app.node_execution.registry import build_registry
from app.nodes.render import render
from app.tools.receipts import SERVICE_UNAVAILABLE
from harness.node_registry import DEFAULT_NODE_REGISTRY


async def test_render_preparation_retains_business_code_and_matches_direct_execution() -> None:
    spec = next(node for node in build_registry() if node.name == "render")
    state: dict[str, Any] = {"product_type": "option", "api_code": 500, "api_result": "内部异常"}
    prepared = prepare_state(spec, state)
    assert prepared.valid
    assert prepared.state.get("api_code") == 500, prepared.dropped_fields
    direct = await render(state)
    replay = await NodeExecutor([spec]).run("main", "render", prepared.state)
    assert replay["reply_text"] == direct["reply_text"] == SERVICE_UNAVAILABLE
    assert prepared.state["api_result"] == "内部异常"


@pytest.mark.parametrize("name", [
    "render", "intent_route", "swap_select_counterparty", "swap_select_ticker",
    "inquiry_extract", "place_close_extract",
])
def test_shared_nodes_have_one_input_contract(name: str) -> None:
    spec = next(node for node in build_registry() if node.name == name)
    view = DEFAULT_NODE_REGISTRY[name]
    assert set(spec.effective_input_fields) == set(view.input_fields)


def test_execution_and_evaluation_keep_their_distinct_exposure() -> None:
    application = {node.name for node in build_registry()}
    evaluation = set(DEFAULT_NODE_REGISTRY)
    assert application - evaluation == {"entry_route", "swap", "option", "option_close"}
    assert evaluation - application == {"swap_extract_candidates", "swap_normalize", "swap_place_result"}
    assert all(not node.replayable for node in DEFAULT_NODE_REGISTRY.values() if node.side_effect == "write")


def test_catalogue_import_does_not_load_config_or_graph(tmp_path: Path) -> None:
    env = {key: os.environ[key] for key in ("PATH", "HOME", "SYSTEMROOT") if key in os.environ}
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    code = (
        "import sys; from app.node_execution.catalog import NODE_CATALOG; "
        "assert NODE_CATALOG; assert 'app.config' not in sys.modules; "
        "assert 'app.graph.state' not in sys.modules; "
        "assert not any(m.startswith('app.subgraphs') for m in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr


def test_catalogue_defines_all_shared_fields_and_exposure() -> None:
    from app.node_execution.catalog import NODE_CATALOG

    applications = {node.name: node for node in build_registry()}
    assert applications.keys() == {
        node.name for node in NODE_CATALOG.values() if "execution" in node.surfaces
    }
    for name, node in NODE_CATALOG.items():
        assert len(node.input_fields) == len(set(node.input_fields)), name
        if name in applications:
            assert set(applications[name].effective_input_fields) == set(node.input_fields), name
        if name in DEFAULT_NODE_REGISTRY:
            view = DEFAULT_NODE_REGISTRY[name]
            assert view.input_fields == node.input_fields, name
            assert view.output_fields == node.output_fields, name
            assert view.callable_path == node.callable_path, name
            assert view.side_effect == node.side_effect, name


def test_retired_multi_action_nodes_are_not_exposed() -> None:
    from app.node_execution.catalog import NODE_CATALOG

    retired = {"plan_instructions", "instructions"}
    assert not retired.intersection(NODE_CATALOG)
    assert not retired.intersection(DEFAULT_NODE_REGISTRY)
    assert not retired.intersection(node.name for node in build_registry())


def test_main_registry_matches_current_graph() -> None:
    from app.graph.main import build_main_graph

    registered = {node.name for node in build_registry() if node.product == "main"}
    assert registered == set(build_main_graph().nodes) - {"__start__"}
