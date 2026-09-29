"""把审阅后的节点样本投影到 Dataset，并经 HTTP 做确定性节点回归。"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx

from harness.langfuse_client import case_trace, http_turn_trace
from harness.node_fixtures import _sensitive_path
from harness.node_registry import DEFAULT_NODE_REGISTRY
from harness.node_runner import run_node_fixture_http


def validate_expected(node_name: str, expected: dict[str, Any]) -> None:
    """只接受非空稳定输出断言；动态 trace 和未注册节点不能成为放行依据。"""
    definition = DEFAULT_NODE_REGISTRY.get(node_name)
    if definition is None or not definition.annotatable:
        raise ValueError("节点尚无可标注的稳定输出契约")
    mode = expected.get("mode")
    values = expected.get("fields" if mode == "fields" else "value")
    if mode not in {"fields", "object"} or not isinstance(values, dict) or not values:
        raise ValueError("节点标注必须包含非空字段或对象断言")
    for key in values:
        if mode == "fields" and (not key.startswith("/") or key == "/"):
            raise ValueError("字段断言必须使用非空 JSON Pointer")
        root = key[1:].split("/", 1)[0] if mode == "fields" else key
        if root not in definition.output_fields or root == "trace":
            raise ValueError(f"字段不属于节点稳定输出：{key}")


def dataset_record(fixture: dict[str, Any], *, reviewer: str, dataset_name: str) -> dict[str, Any]:
    """发布只读投影，保留原始来源与审阅者，不修改 git 的业务基线。"""
    # 1. 发布前验证来源、审阅与有效断言，写节点也可以留存标注。
    name = str(fixture.get("node_name") or "")
    expected = fixture.get("expected") or {}
    validate_expected(name, expected)
    source = fixture.get("source") or {}
    if not reviewer.strip() or not source.get("trace_id") or not source.get("observation_id"):
        raise ValueError("节点样本需要审阅者及来源 trace/observation")
    if not isinstance(fixture.get("input"), dict):
        raise ValueError("节点输入必须是对象")
    if _sensitive_path(fixture):
        raise ValueError("节点样本含凭据，不能上传")
    definition = DEFAULT_NODE_REGISTRY[name]
    # 2. 稳定身份由数据集、节点和来源共同决定；重复发布更新同一条。
    identity = str(uuid5(NAMESPACE_URL, f"node:{dataset_name}:{name}:{source['trace_id']}:{source['observation_id']}"))
    content_hash = hashlib.sha256(json.dumps(
        {"input": fixture["input"], "expected": expected}, ensure_ascii=False, sort_keys=True,
    ).encode()).hexdigest()
    return {"id": identity, "input": {"node_name": name, "state": fixture["input"]},
        "expected_output": expected, "source_trace_id": source["trace_id"],
        "source_observation_id": source["observation_id"],
        "metadata": {"case_id": fixture.get("id") or identity, "suite": "node", "source": source,
            "reviewer": reviewer, "review_status": "approved", "content_hash": content_hash,
            "replay": {"enabled": definition.replayable and definition.side_effect != "write"},
            "assertion_version": "node-fields-v1"}}


def item_fixture(item: Any) -> dict[str, Any]:
    """平台 input 与 expected 分离，来源不被当前实验覆盖。"""
    def value(name: str, default: Any = None) -> Any:
        """本地 SDK 字典与 DatasetItem 读取同一字段。"""
        return item.get(name, default) if isinstance(item, dict) else getattr(item, name, default)

    inp, metadata = value("input", {}), value("metadata", {})
    if not isinstance(inp, dict) or not isinstance(metadata, dict):
        raise ValueError("节点 Dataset 输入或元数据不是对象")
    if metadata.get("review_status") != "approved":
        raise ValueError("节点 Dataset 尚未人工审阅")
    return {"id": metadata.get("case_id") or value("id"), "node_name": inp.get("node_name"),
        "input": inp.get("state"), "expected": value("expected_output"),
        "source": metadata.get("source") or {}, "replay": metadata.get("replay") or {}}


async def run_node_case(fixture: dict[str, Any], *, client: httpx.AsyncClient) -> dict[str, Any]:
    """写节点先 SKIP；可回放节点始终通过服务端准备和执行入口。"""
    name = str(fixture.get("node_name") or "")
    definition = DEFAULT_NODE_REGISTRY.get(name)
    report: dict[str, Any] = {"id": fixture.get("id"), "case_id": fixture.get("id"),
        "node_name": name, "source": fixture.get("source") or {}, "passed": False, "diffs": []}
    # 1. 平台标记不能扩大本仓库允许回放的范围。
    if definition and (definition.side_effect == "write" or not definition.replayable):
        return {**report, "status": "SKIP", "reason": "该节点仅保留标注，不允许自动回放"}
    if not (fixture.get("replay") or {}).get("enabled"):
        return {**report, "status": "SKIP", "reason": "样本未开启回放"}
    session_id = f"node-eval-{uuid4().hex}"
    with case_trace(str(fixture.get("id")), session_id, "node-evaluation") as trace:
        try:
            validate_expected(name, fixture.get("expected") or {})
            # 2. 新执行使用独立 Session，原始 source 保持可追溯。
            with http_turn_trace(1) as headers:
                result = await run_node_fixture_http(fixture, registry=DEFAULT_NODE_REGISTRY,
                    client=client, api_key="", trace_headers=headers)
            report.update(status="PASS" if result.passed else "FAIL", passed=result.passed,
                          actual=result.actual, diffs=[asdict(diff) for diff in result.diffs],
                          tracing=result.tracing)
        except Exception as exc:
            report.update(status="FAIL", error=f"{type(exc).__name__}: {exc}")
        report.update(langfuse_trace_id=trace.trace_id, observation_id=trace.observation_id)
        report["evaluations"] = [{"name": "det_node_pass", "value": float(report["passed"]),
                                  "comment": "节点字段断言"}]
        trace.update(report)
    return report
