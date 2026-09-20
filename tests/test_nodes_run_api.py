"""节点执行 HTTP 契约；放在默认 pytest 收集目录。"""

from __future__ import annotations

import httpx
import pytest

from app.main import app


@pytest.fixture(autouse=True)
def node_executor(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.node_execution.executor import NodeExecutor
    from app.node_execution.registry import build_registry

    monkeypatch.setattr(app.state, "node_executor", NodeExecutor(build_registry()), raising=False)


async def post_node(product: str, node: str, state: dict) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post(
            "/v1/nodes/run", json={"product": product, "node": node, "state": state}
        )


async def test_only_target_update_without_input_or_old_trace() -> None:
    response = await post_node(
        "option",
        "option_unknown",
        {
            "raw_text": "test",
            "trace": [{"node": "old"}],
            "history_messages": [],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["product"] == "option"
    assert body["node"] == "option_unknown"
    assert set(body["output"]) == {"trace"}
    assert [entry["node"] for entry in body["output"]["trace"]] == ["option_unknown"]


async def test_ingest_preserves_null_and_unwraps_overwrite() -> None:
    response = await post_node("main", "ingest", {"trace": [{"node": "old"}]})
    assert response.status_code == 200, response.text
    output = response.json()["output"]
    assert output["tickers"] is None
    assert output["reply_text"] is None
    assert [entry["node"] for entry in output["trace"]] == ["ingest"]
    assert "product_type" not in output


@pytest.mark.parametrize(
    "state",
    [
        {"unknown": 1},
        {"raw_text": 1},
        {"message_id": "123"},
        {"at_bot": "false"},
        {"history_messages": [{"role": "bad", "content": "x"}]},
        {"history_messages": [{"role": "user", "content": "x", "unknown": 1}]},
        {"tickers": [{"windCode": 123}]},
        {"trace": [{"node": False}]},
    ],
)
async def test_rejects_unknown_fields_and_wrong_types(state: dict) -> None:
    response = await post_node("option", "option_unknown", state)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    ("product", "node"),
    [
        ("bad", "ingest"),
        ("swap", "option_intent"),
        ("main", "__start__"),
        ("ticker", "fan_out_org_items"),
        ("main", "app.nodes.ingest.ingest"),
    ],
)
async def test_not_registered(product: str, node: str) -> None:
    response = await post_node(product, node, {})
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("product", "node", "state"),
    [
        ("option_close", "place_close_fetch_orders", {}),
        ("ticker", "extract_candidates", {}),
        ("ticker", "infer_codes", {}),
        ("ticker", "resolve_org_item", {"raw_text": "腾讯"}),
        ("option", "inquiry_submit", {}),
        ("swap", "swap_image_order", {}),
        ("swap", "swap_excel_order", {}),
        ("main", "quick_inquiry", {}),
    ],
)
async def test_missing_required_context_is_422(product: str, node: str, state: dict) -> None:
    response = await post_node(product, node, state)
    assert response.status_code == 422, response.text


async def test_ticker_empty_result_has_no_synthetic_trace() -> None:
    response = await post_node("ticker", "assemble", {})
    assert response.status_code == 200, response.text
    assert response.json()["output"] == {"resolved": []}


async def test_ticker_assemble_order_dedup_and_models() -> None:
    response = await post_node(
        "ticker",
        "assemble",
        {
            "candidates": ["腾讯", "腾讯控股", "茅台"],
            "winners": [
                {"index": 2, "org_str": "腾讯控股", "winner": {"windCode": "00700.HK"}},
                {"index": 1, "org_str": "茅台", "winner": {"windCode": "600519.SH"}},
                {"index": 0, "org_str": "腾讯", "winner": {"windCode": "00700.HK"}},
            ],
        },
    )
    assert response.status_code == 200, response.text
    resolved = response.json()["output"]["resolved"]
    assert [item["windCode"] for item in resolved] == ["00700.HK", "600519.SH"]
    assert resolved[0]["sourceKeywords"] == ["腾讯", "腾讯控股"]
    assert all(item["from_goats"] for item in resolved)


async def test_existing_node_error_is_500_and_preserves_output() -> None:
    response = await post_node("swap", "swap_image_order", {"input_files": []})
    assert response.status_code == 500, response.text
    output = response.json()["output"]
    assert output["error"]["type"] == "ValueError"
    assert output["trace"][0]["node"] == "swap_image_order"
