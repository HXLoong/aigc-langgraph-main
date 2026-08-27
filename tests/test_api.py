"""api/ 单元测试 — 验证 Dify Workflow Run API 兼容（ADR 0001 D3）。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    # 必须用 contextmanager 触发 lifespan（编译主图到 app.state）
    with TestClient(app) as c:
        yield c


def test_health_endpoint(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_workflows_run_returns_dify_compatible_schema(client: TestClient) -> None:
    """ADR 0001 D3：response 必须符合 Dify 协议形态。"""
    r = client.post(
        "/v1/workflows/run",
        json={
            "inputs": {
                "rawContent": "测试 - 互换下单",
                "conversationId": "c-test-001",
                "messageId": 42,
                "userId": "u-1",
                "roomId": "r-1",
                "messageContent": "测试 - 互换下单",
            },
            "response_mode": "blocking",
            "user": "c-test-001",
        },
    )
    assert r.status_code == 200, r.text

    body = r.json()
    # Dify schema: workflow_run_id / task_id / data
    assert "workflow_run_id" in body
    assert "task_id" in body
    assert "data" in body

    data = body["data"]
    assert data["status"] == "succeeded"
    assert "outputs" in data
    assert data["total_steps"] >= 1  # 至少跑过 ingest

    # outputs 含 product_type / intent
    outputs = data["outputs"]
    assert outputs["product_type"] == "swap"  # M1 默认
    assert outputs["intent"] is not None


def test_streaming_mode_rejected(client: TestClient) -> None:
    """blocking only（contracts §3：Java StockBotMessageServiceImpl.java:1646）。"""
    r = client.post(
        "/v1/workflows/run",
        json={
            "inputs": {},
            "response_mode": "streaming",
            "user": "c-test",
        },
    )
    assert r.status_code == 400


def test_inputs_field_passthrough(client: TestClient) -> None:
    """Dify inputs 字段名应该兼容 camelCase 和 snake_case。"""
    r = client.post(
        "/v1/workflows/run",
        json={
            "inputs": {
                "raw_content": "snake_case 兼容性测试",  # 注意是 snake
                "conversationId": "c-snake",
                "messageId": 1,
                "userId": "u",
                "roomId": "r",
                "messageContent": "snake_case 兼容性测试",
            },
            "response_mode": "blocking",
            "user": "c-snake",
        },
    )
    assert r.status_code == 200


def test_workflows_run_emits_end_to_end_latency(client: TestClient) -> None:
    """#157：请求出口必须写端到端延迟直方图（无 node label，区别于节点级样本）。"""
    client.post(
        "/v1/workflows/run",
        json={
            "inputs": {
                "rawContent": "测试 - 互换下单",
                "conversationId": "c-metrics-001",
                "messageId": 43,
                "userId": "u-1",
                "roomId": "r-1",
                "messageContent": "测试 - 互换下单",
            },
            "response_mode": "blocking",
            "user": "c-metrics-001",
        },
    )
    metrics_text = client.get("/metrics").text
    e2e_lines = [
        line
        for line in metrics_text.splitlines()
        if line.startswith("otc_agent_intent_latency_ms_count")
        and 'node="' not in line
        and 'product_type="swap"' in line
    ]
    assert e2e_lines, "端到端延迟样本（product_type=swap 且无 node label）未写入"
