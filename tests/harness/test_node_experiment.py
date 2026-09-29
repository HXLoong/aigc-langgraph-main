"""节点平台回归遵守同一字段断言和禁止交易节点回放的边界。"""
from __future__ import annotations

import importlib
import importlib.util
import json

import httpx
import pytest


def _module():
    """新入口缺失时明确显示 RED，而不是静默不执行。"""
    assert importlib.util.find_spec("harness.node_experiment") is not None
    return importlib.import_module("harness.node_experiment")


def fixture(node="parse_instruction"):
    """有效人工标注携带来源 observation 与稳定字段断言。"""
    return {"id": "reviewed-1", "node_name": node, "input": {"raw_text": "期权询价"},
        "expected": {"mode": "fields", "fields": {"/intent": "new_inquiry"}},
        "source": {"trace_id": "a" * 32, "observation_id": "b" * 16},
        "annotation": {"status": "completed", "annotator": "reviewer"},
        "replay": {"enabled": True}}


async def test_node_experiment_scores_http_output_and_keeps_source():
    """字段差异来自真实 HTTP 输出，来源追踪不被新执行覆盖。"""
    module = _module()
    requests = []

    def response(request):
        """模拟准备与执行两个外部入口，返回故意不同的意图。"""
        body = json.loads(request.content)
        requests.append(request.url.path)
        if request.url.path.endswith("prepare"):
            return httpx.Response(200, json={"request": {"state": body["langfuse_input"]}})
        return httpx.Response(200, json={"output": {"intent": "unknown_intent"}})

    async with httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(response)) as client:
        result = await module.run_node_case(fixture(), client=client)
    assert requests == ["/v1/nodes/prepare", "/v1/nodes/run"]
    assert result["status"] == "FAIL"
    assert result["diffs"][0]["path"] == "/intent"
    assert result["source"]["observation_id"] == "b" * 16


async def test_write_node_is_skipped_even_if_platform_replay_flag_is_true():
    """平台元数据不能绕过本仓库的写副作用清单。"""
    module = _module()

    def forbidden(request):
        """任何请求都意味着写节点安全门被绕过。"""
        raise AssertionError("write node must not execute")

    async with httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(forbidden)) as client:
        result = await module.run_node_case(fixture("option_submit"), client=client)
    assert result["status"] == "SKIP"
    assert not result["passed"]


@pytest.mark.parametrize("expected", [{}, {"mode": "fields", "fields": {}}, {"mode": "object", "value": {}}])
def test_empty_annotation_cannot_be_published(expected):
    """平台节点 Dataset 不能用空期望制造通过样本。"""
    module = _module()
    data = {**fixture(), "expected": expected}
    with pytest.raises(ValueError):
        module.dataset_record(data, reviewer="reviewer", dataset_name="nodes/test")


def test_same_observation_in_two_datasets_has_distinct_item_identity():
    """数据集彼此独立，发布同一来源不能覆盖另一套回归基线。"""
    module = _module()
    first = module.dataset_record(fixture(), reviewer="reviewer", dataset_name="nodes/train")
    second = module.dataset_record(fixture(), reviewer="reviewer", dataset_name="nodes/regression")
    assert first["id"] != second["id"]
