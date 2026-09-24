"""Attachment candidates must pass the same Code and GOATS boundary as text orders."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.extraction.candidates import candidate_model
from app.subgraphs.swap import multimodal as mm
from app.subgraphs.swap.models import SwapPlaceOrderParams

IMAGE_TEXT = "甲证券 买入 1.5万股 限价20"
IMAGE_REF = "file:0:image"


def field(value, reference=IMAGE_REF):
    return {"value": value, "evidence": value, "confidence": .9,
            "origin": "attachment", "reference": reference}


def patch_models(monkeypatch, orders, text=IMAGE_TEXT, tickers=None):
    vl = MagicMock()
    vl.ainvoke = AsyncMock(return_value=SimpleNamespace(content=text))
    vl.with_structured_output.return_value.ainvoke = AsyncMock(return_value={"text": text})
    monkeypatch.setattr(mm, "get_qwen_vl", lambda: vl)
    model = MagicMock()
    model.with_structured_output.return_value.ainvoke = AsyncMock(
        return_value=candidate_model(SwapPlaceOrderParams).model_validate({"orderList": orders})
    )
    monkeypatch.setattr(mm, "get_qwen_structured", lambda: model)
    return vl, model


def order():
    return {"placeOrderWindCode": field("甲证券"), "placeOrderQuantity": field("1.5万股"),
            "placeOrderOrderDirection": field("买入"), "placeOrderPrice": field("20")}


async def test_image_candidates_normalized_bound_and_locked(monkeypatch):
    _, model = patch_models(monkeypatch, [order()])
    out = await mm.swap_image_order({"input_files": [{"type": "image", "url": "https://file/img"}]})
    assert not out.get("error")
    row = out["place_params"]["orderList"][0]
    assert row["placeOrderQuantity"] == 15000
    assert row["placeOrderOrderDirection"] == "BUY"
    assert row["placeOrderWindCode"] == "甲证券"
    records = out["field_records"]
    quantity = records["swap/place_order.orderList.0.placeOrderQuantity"]
    assert quantity.value == 15000 and quantity.locked
    assert quantity.origin == "attachment:" + IMAGE_REF
    assert quantity.evidence == "1.5万股"
    ticker = records["swap/place_order.orderList.0.placeOrderWindCode"]
    assert ticker.source == "user"
    assert ticker.origin == quantity.origin
    assert "attachment:" + IMAGE_REF in model.with_structured_output.return_value.ainvoke.call_args.args[0][-1][1]


async def test_unknown_ticker_is_delegated_to_backend(monkeypatch):
    patch_models(monkeypatch, [order()], tickers=[])
    out = await mm.swap_image_order({"input_files": [{"type": "image", "url": "https://file/img"}]})
    assert not out.get("error")
    assert out["place_params"]["orderList"][0]["placeOrderWindCode"] == "甲证券"


async def test_empty_attachment_orders_do_not_reach_submit(monkeypatch):
    patch_models(monkeypatch, [], text="")
    out = await mm.swap_image_order({"input_files": [{"type": "image", "url": "https://file/img"}]})
    assert out.get("error") is not None


async def test_foreign_attachment_reference_is_rejected(monkeypatch):
    wrong = order()
    wrong["placeOrderQuantity"] = field("1.5万股", "file:99:image")
    patch_models(monkeypatch, [wrong])
    with pytest.raises(ValueError, match="invalid field evidence"):
        await mm.swap_image_order({"input_files": [{"type": "image", "url": "https://file/img"}]})


def excel_bytes(headers, rows):
    import io

    import openpyxl

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    output = io.BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


@pytest.mark.parametrize("quantity_reference", ["file:0:sheet:0:row:2:column:B", "file:0:sheet:0:row:2"])
async def test_excel_header_unit_is_applied_by_code_and_keeps_cell_reference(monkeypatch, quantity_reference):
    ref = "file:0:sheet:0:row:2:column:"
    row = {"placeOrderWindCode": field("甲证券", ref + "A"),
           "placeOrderQuantity": field("1.5", quantity_reference),
           "placeOrderOrderDirection": field("买入", ref + "C")}
    patch_models(monkeypatch, [row])
    monkeypatch.setattr(mm, "_fetch_bytes", AsyncMock(return_value=excel_bytes(
        ["标的", "数量(万股)", "方向"], [["甲证券", 1.5, "买入"]],
    )))
    out = await mm.swap_excel_order({"input_files": [{"url": "https://file/orders.xlsx"}]})
    assert not out.get("error")
    assert out["place_params"]["orderList"][0]["placeOrderQuantity"] == 15000
    record = out["field_records"]["swap/place_order.orderList.0.placeOrderQuantity"]
    assert record.origin == "attachment:" + ref + "B" and record.locked
    assert "1.5" in record.evidence and "万股" in record.evidence
    assert out["field_records"]["swap/place_order.orderList.0.placeOrderQuantityUnit"].value == "SHARE"


async def test_excel_two_rows_keep_separate_evidence_and_orders(monkeypatch):
    _, model = patch_models(monkeypatch, [])
    model.with_structured_output.return_value.ainvoke.side_effect = [
        candidate_model(SwapPlaceOrderParams).model_validate({"orderList": [{
            "placeOrderWindCode": field("甲证券", f"file:0:sheet:0:row:{index}:column:A"),
            "placeOrderQuantity": field(value, f"file:0:sheet:0:row:{index}:column:B"),
        }]}) for index, value in [(2, "100股"), (3, "200股")]
    ]
    monkeypatch.setattr(mm, "_fetch_bytes", AsyncMock(return_value=excel_bytes(
        ["标的", "数量"], [["甲证券", "100股"], ["甲证券", "200股"]],
    )))
    out = await mm.swap_excel_order({"input_files": [{"url": "https://file/orders.xlsx"}]})
    assert not out.get("error")
    assert [row["placeOrderQuantity"] for row in out["place_params"]["orderList"]] == [100, 200]
    records = out["field_records"]
    assert records["swap/place_order.orderList.0.placeOrderQuantity"].origin.endswith("row:2:column:B")
    assert records["swap/place_order.orderList.1.placeOrderQuantity"].origin.endswith("row:3:column:B")


async def test_authorized_counterparty_is_bound_and_locked(monkeypatch):
    data = order()
    data["placeOrderShortname"] = field("甲账户全称")
    patch_models(monkeypatch, [data], text=IMAGE_TEXT + " 甲账户全称")
    out = await mm.swap_image_order({
        "input_files": [{"type": "image", "url": "https://file/img"}],
        "swap_counterparties": [{"shortName": "甲账户", "longName": "甲账户全称"}],
    })
    assert not out.get("error")
    assert out["place_params"]["orderList"][0]["placeOrderShortname"] == "甲账户"
    record = out["field_records"]["swap/place_order.orderList.0.placeOrderShortname"]
    assert record.source == "goats" and record.locked


async def test_unrecognized_account_blocks_attachment_order(monkeypatch):
    data = order()
    data["placeOrderShortname"] = field("甲账户")
    patch_models(monkeypatch, [data], text=IMAGE_TEXT + " 甲账户")
    out = await mm.swap_image_order({
        "input_files": [{"type": "image", "url": "https://file/img"}],
        "swap_counterparties": [{"shortName": "其他账户"}],
    })
    assert out.get("error") is not None
