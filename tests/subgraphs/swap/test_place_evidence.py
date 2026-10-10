"""互换准备图保留模型数值对应的原始单位证据。"""
from app.subgraphs.swap.place_order import build_place_graph, swap_place_order
from tests.joint_support import instruction_data


async def test_interface_quantity_keeps_original_unit_evidence():
    """接口值由模型给出，图内没有单位换算阶段。"""
    raw = "甲证券买入1.5万股"
    parsed = instruction_data("swap", "place_order_request", raw,
        orders=[{"placeOrderWindCode": "甲证券", "placeOrderQuantity": 15000}])
    parsed["fields"][1]["text"] = "1.5万股"
    result = await swap_place_order({"raw_text": raw, "parsed_instruction": parsed})
    assert not result.get("error"), result
    record = result["field_records"]["swap/parse.orderList.0.placeOrderQuantity"]
    assert record.value == 15000 and record.evidence == "1.5万股" and record.locked
    assert set(build_place_graph().get_graph().nodes) == {"__start__", "swap_prepare", "swap_validate", "swap_place_result", "__end__"}
