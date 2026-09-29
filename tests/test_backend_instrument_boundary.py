"""标的表达原样交 Java，本地不识别证券或补全代码。"""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.nodes.prepare_input import prepare_input
from app.subgraphs.option import extract_inquiry as inquiry
from app.subgraphs.swap import place_order
from app.tools.ticker_client import TickerClientHttpx
from tests.joint_support import instruction_data


def test_business_graphs_do_not_import_local_instrument_resolution() -> None:
    """从实际依赖面阻止证券查询重新进入业务链。"""
    pattern = re.compile(r"resolve_ticker|TickerClient|ticker_client|from_goats=True")
    roots = (Path("app/subgraphs"), Path("app/nodes"), Path("app/graph"))
    assert not [str(path) for root in roots for path in root.rglob("*.py") if pattern.search(path.read_text())]


@pytest.mark.parametrize("instrument", ["沪铜主力", "9月沪铜", "宁德时代", "2333长城汽车", "cu2609.shf", "00700"])
async def test_swap_preserves_instrument_at_submit(monkeypatch, instrument: str) -> None:
    """名称、月份和完整代码都不在客户端补全。"""
    raw = f"{instrument} 买入 8万股"
    state = {"raw_text": raw, "parsed_instruction": instruction_data("swap", "place_order_request", raw,
             orders=[{"placeOrderWindCode": instrument, "placeOrderQuantity": 80000}])}
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "后端处理结果"})
    monkeypatch.setattr(place_order, "prepare_swap_request", backend)
    prepared = await place_order.swap_place_order(state)
    assert not prepared.get("error")
    result = await place_order.swap_place_order_submit({**state, **prepared})
    assert backend.await_args.kwargs["order_list"][0]["placeOrderWindCode"] == instrument
    assert result["api_result"] == "后端处理结果"


@pytest.mark.parametrize("instrument", ["宁德时代", "2333长城汽车", "000000.SZ"])
async def test_inquiry_reaches_backend_even_for_unknown_instrument(monkeypatch, instrument: str) -> None:
    """本地证券池没有命中不构成拦截理由，权威识别由 Java 完成。"""
    raw = f"{instrument} 欧式看涨 1个月 80%"
    parsed = instruction_data("option", "new_inquiry", raw, orders=[{"stockCode": instrument, "tenor": "1M"}])
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "后端：标的待核实"})
    monkeypatch.setattr(inquiry, "prepare_option_request", backend)
    result = await inquiry.option_extract_inquiry({"raw_text": raw, "parsed_instruction": parsed})
    assert not result.get("error")
    assert backend.await_args.kwargs["order_list"][0]["stockCode"] == instrument
    assert result["api_result"] == "后端：标的待核实"


async def test_image_is_rejected_without_security_lookup() -> None:
    """本阶段图片不进入证券或 OCR 工具。"""
    result = await prepare_input({"input_files": [{"type": "image", "url": "http://image.invalid/a.png"}]})
    assert "图片" in result["reply_text"]


def test_ticker_client_has_no_security_resolution_interface() -> None:
    """授权对手列表客户端不提供本地证券识别能力。"""
    for name in ("search_securities_instrument", "get_inference_prompt"):
        assert not hasattr(TickerClientHttpx, name)


def test_local_mock_does_not_expose_forbidden_security_endpoint():
    """仅检查路由表，不通过实际调用验证禁止接口。"""
    from mock_api.server import app

    assert not any("securities-instrument" in getattr(route, "path", "") for route in app.routes)
