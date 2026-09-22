"""swap 图片/Excel 多模态链测试(DSL v2 互换-图片 / 互换-Excel 分支)。

覆盖 `app/subgraphs/swap/multimodal.py`：
- `parse_excel_rows`：openpyxl 解析 + 「产品」列改名「交易对手」（确定性代码规则）
- `_image_urls`：remote_url / url / base64 三键取值
- `swap_image_order`：VL OCR → 参数提取 → place_params
- `swap_excel_order`：下载 → 解析 → 参数提取 → place_params

测试方法：G2 节点单测（mock VL / structured 工厂，patch 打在**使用点**模块 `mm`）。
"""
from __future__ import annotations

import io
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import openpyxl
import pytest

import app.subgraphs.swap.multimodal as mm
from app.extraction.candidates import candidate_model
from app.subgraphs.swap.models import SwapOrderItem, SwapPlaceOrderParams
from app.subgraphs.swap.multimodal import (
    _image_urls,
    parse_excel_rows,
    swap_excel_order,
    swap_image_order,
)


def _make_excel_bytes(headers: list[str], rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ============================================================
# LLM 工厂打桩（patch 使用点 mm）
# ============================================================


def _patch_vl(
    monkeypatch: pytest.MonkeyPatch,
    ocr_text: str = "OCR 文本:买入 600519.SH 100股 H-20260101-0000000001 限价350",
    *,
    error: Exception | None = None,
) -> MagicMock:
    ocr_llm = MagicMock()
    ocr_llm.ainvoke = (
        AsyncMock(side_effect=error)
        if error is not None
        else AsyncMock(return_value={"text": ocr_text})
    )
    factory = MagicMock()
    factory.with_structured_output.return_value = ocr_llm
    monkeypatch.setattr(mm, "get_qwen_vl", lambda: factory)
    return ocr_llm


def _patch_extract(
    monkeypatch: pytest.MonkeyPatch,
    result: SwapPlaceOrderParams | None = None,
    *,
    error: Exception | None = None,
) -> MagicMock:
    async def extract(messages):
        if error is not None:
            raise error
        sources = json.loads(messages[-1][1])["sources"]
        params = result if result is not None else _PARAMS
        orders = []
        for item in params.order_list:
            row = {}
            for key, value in item.model_dump().items():
                if value is None:
                    continue
                literal = str(value)
                if isinstance(value, float) and value.is_integer():
                    literal = str(int(value))
                reference = next((key.removeprefix("attachment:") for key, text in sources.items()
                                  if key.startswith("attachment:") and literal in text), "missing")
                row[key] = {"value": literal, "evidence": literal, "origin": "attachment",
                            "reference": reference, "confidence": 1.0}
            orders.append(row)
        return candidate_model(SwapPlaceOrderParams).model_validate({"orderList": orders})

    extract_llm = MagicMock()
    extract_llm.ainvoke = AsyncMock(side_effect=extract)
    factory = MagicMock()
    factory.with_structured_output.return_value = extract_llm
    monkeypatch.setattr(mm, "get_qwen_structured", lambda: factory)
    return extract_llm


def _mock_llm(
    monkeypatch: pytest.MonkeyPatch, structured_result: SwapPlaceOrderParams
) -> tuple[MagicMock, MagicMock]:
    """mock VL 与 structured 两个工厂（patch 使用点）。"""
    return _patch_vl(monkeypatch), _patch_extract(monkeypatch, structured_result)


_PARAMS = SwapPlaceOrderParams(
    orderList=[SwapOrderItem(placeOrderWindCode="600519.SH", placeOrderQuantity=100)]
)

_MODIFY_PARAMS = SwapPlaceOrderParams(
    orderList=[SwapOrderItem(orderId="H-20260101-0000000001", placeOrderPrice=350)]
)


# ============================================================
# parse_excel_rows
# ============================================================


class TestParseExcelRows:
    def test_product_column_renamed(self) -> None:
        data = _make_excel_bytes(["产品", "数量"], [["中信", 100]])
        rows = parse_excel_rows(data)
        assert rows == [{"交易对手": "中信", "数量": 100}]

    def test_product_column_renamed_in_middle(self) -> None:
        data = _make_excel_bytes(["标的", "产品", "方向"], [["600519.SH", "中信", "买入"]])
        rows = parse_excel_rows(data)
        assert rows == [{"标的": "600519.SH", "交易对手": "中信", "方向": "买入"}]

    def test_no_product_column(self) -> None:
        data = _make_excel_bytes(["标的", "方向"], [["600519.SH", "买入"]])
        rows = parse_excel_rows(data)
        assert rows == [{"标的": "600519.SH", "方向": "买入"}]

    def test_empty_sheet(self) -> None:
        data = _make_excel_bytes(["A"], [])
        assert parse_excel_rows(data) == []

    def test_fully_empty_row_skipped(self) -> None:
        data = _make_excel_bytes(["A", "B"], [["x", "y"], [None, None]])
        assert parse_excel_rows(data) == [{"A": "x", "B": "y"}]

    def test_multiple_rows(self) -> None:
        data = _make_excel_bytes(["产品", "数量"], [["中信", 100], ["华泰", 200]])
        assert parse_excel_rows(data) == [
            {"交易对手": "中信", "数量": 100},
            {"交易对手": "华泰", "数量": 200},
        ]


# ============================================================
# _image_urls
# ============================================================


class TestImageUrls:
    def test_remote_url_preferred(self) -> None:
        files = [{"remote_url": "http://r/1.png", "url": "http://u/1.png"}]
        assert _image_urls(files) == ["http://r/1.png"]

    def test_url_fallback(self) -> None:
        assert _image_urls([{"url": "http://u/1.png"}]) == ["http://u/1.png"]

    def test_base64_fallback(self) -> None:
        assert _image_urls([{"base64": "data:image/png;base64,AAA"}]) == [
            "data:image/png;base64,AAA"
        ]

    def test_empty_values_skipped(self) -> None:
        files = [{"remote_url": "", "url": None}, {"url": "http://u/2.png"}]
        assert _image_urls(files) == ["http://u/2.png"]

    def test_multiple_files_preserve_order(self) -> None:
        files = [{"url": "http://u/1.png"}, {"url": "http://u/2.png"}]
        assert _image_urls(files) == ["http://u/1.png", "http://u/2.png"]

    def test_no_files(self) -> None:
        assert _image_urls([]) == []


# ============================================================
# swap_image_order
# ============================================================


class TestImageOrder:
    @pytest.mark.asyncio
    async def test_ocr_then_extract(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ocr_llm, extract_llm = _mock_llm(monkeypatch, _PARAMS)
        out = await swap_image_order(
            {
                "raw_text": "",
                "input_files": [{"type": "image", "url": "http://img/1.png"}],
            }
        )
        assert out["expected_action"] == "place"
        assert "expected_action" not in out["place_params"]
        assert out["place_params"]["orderList"][0]["placeOrderWindCode"] == "600519.SH"
        assert out["intent"] == "place_order_request"
        assert ocr_llm.ainvoke.await_count == 1
        assert extract_llm.ainvoke.await_count == 1

    @pytest.mark.asyncio
    async def test_vl_message_contains_text_and_image_parts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """VL 消息必须是 [text, image_url] 多模态结构（原恒真断言的正确版本）。"""
        ocr_llm, _ = _mock_llm(monkeypatch, _PARAMS)
        await swap_image_order(
            {
                "raw_text": "",
                "input_files": [{"type": "image", "url": "http://img/1.png"}],
            }
        )
        (msgs,), _ = ocr_llm.ainvoke.call_args
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        content = msgs[0]["content"]
        assert content[0]["type"] == "text"
        assert content[0]["text"]  # OCR 提示词 system 文本非空
        assert content[1] == {"type": "image_url", "image_url": {"url": "http://img/1.png"}}

    @pytest.mark.asyncio
    async def test_multiple_images_all_sent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ocr_llm, _ = _mock_llm(monkeypatch, _PARAMS)
        out = await swap_image_order(
            {
                "raw_text": "",
                "input_files": [
                    {"type": "image", "url": "http://img/1.png"},
                    {"type": "image", "url": "http://img/2.png"},
                ],
            }
        )
        image_urls = [call.args[0][0]["content"][1]["image_url"]["url"]
                      for call in ocr_llm.ainvoke.call_args_list]
        assert image_urls == ["http://img/1.png", "http://img/2.png"]
        assert out["trace"][0].decision == "images=2"

    @pytest.mark.asyncio
    async def test_non_image_files_filtered_out(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ocr_llm, _ = _mock_llm(monkeypatch, _PARAMS)
        await swap_image_order(
            {
                "raw_text": "",
                "input_files": [
                    {"type": "document", "url": "http://f/x.xlsx"},
                    {"type": "image", "url": "http://img/1.png"},
                ],
            }
        )
        (msgs,), _ = ocr_llm.ainvoke.call_args
        image_urls = [
            c["image_url"]["url"] for c in msgs[0]["content"] if c["type"] == "image_url"
        ]
        assert image_urls == ["http://img/1.png"]

    @pytest.mark.asyncio
    async def test_no_image_files_error(self) -> None:
        out = await swap_image_order({"raw_text": "", "input_files": []})
        assert out.get("error") is not None
        assert out["error"].node == "swap_image_order"

    @pytest.mark.asyncio
    async def test_image_without_url_error(self) -> None:
        out = await swap_image_order({"raw_text": "", "input_files": [{"type": "image"}]})
        assert out.get("error") is not None

    @pytest.mark.asyncio
    async def test_ocr_error_writes_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_vl(monkeypatch, error=RuntimeError("VL down"))
        _patch_extract(monkeypatch)
        out = await swap_image_order(
            {"raw_text": "", "input_files": [{"type": "image", "url": "http://i/1.png"}]}
        )
        assert out["error"] is not None
        assert out["error"].node == "swap_image_order"
        assert "VL down" in out["error"].message

    @pytest.mark.asyncio
    async def test_extract_error_writes_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_vl(monkeypatch)
        _patch_extract(monkeypatch, error=RuntimeError("extract down"))
        out = await swap_image_order(
            {"raw_text": "", "input_files": [{"type": "image", "url": "http://i/1.png"}]}
        )
        assert out["error"] is not None
        assert out["error"].node == "swap_image_order"

    @pytest.mark.asyncio
    async def test_ocr_text_and_raw_text_passed_to_extract(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_vl(monkeypatch, ocr_text="OCR内容XYZ 买入600519.SH 100股")
        extract_llm = _patch_extract(monkeypatch, _PARAMS)
        await swap_image_order(
            {
                "raw_text": "用户附言ABC",
                "input_files": [{"type": "image", "url": "http://i/1.png"}],
            }
        )
        (msgs,), _ = extract_llm.ainvoke.call_args
        user_text = msgs[-1][1]
        assert "OCR内容XYZ" in user_text
        assert "用户附言ABC" in user_text

    @pytest.mark.asyncio
    async def test_modify_when_order_id_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OCR 出的参数带 orderId → expected_action=modify。"""
        _patch_vl(monkeypatch)
        _patch_extract(monkeypatch, _MODIFY_PARAMS)
        out = await swap_image_order(
            {"raw_text": "", "input_files": [{"type": "image", "url": "http://i/1.png"}]}
        )
        assert out["expected_action"] == "modify"

    @pytest.mark.asyncio
    async def test_trace_node_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_llm(monkeypatch, _PARAMS)
        out = await swap_image_order(
            {"raw_text": "", "input_files": [{"type": "image", "url": "http://i/1.png"}]}
        )
        assert out["trace"][0].node == "swap_image_order"
        assert out["trace"][0].llm_output["prompt_name"] == "image_extract"


# ============================================================
# swap_excel_order
# ============================================================


def _patch_fetch(
    monkeypatch: pytest.MonkeyPatch,
    data: bytes = b"",
    *,
    error: Exception | None = None,
) -> None:
    async def fake(url: str) -> bytes:
        if error is not None:
            raise error
        return data

    monkeypatch.setattr(mm, "_fetch_bytes", fake)


class TestExcelOrder:
    @pytest.mark.asyncio
    async def test_download_parse_extract(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, extract_llm = _mock_llm(monkeypatch, _PARAMS)
        _patch_fetch(monkeypatch, _make_excel_bytes(["产品", "数量", "标的"], [["中信", 100, "600519.SH"]]))

        out = await swap_excel_order(
            {
                "raw_text": "",
                "input_files": [
                    {"type": "document", "extension": ".xlsx", "remote_url": "http://f/x.xlsx"}
                ],
            }
        )
        assert out["place_params"]["orderList"][0]["placeOrderWindCode"] == "600519.SH"
        assert out["intent"] == "place_order_request"
        # LLM user message 里带上了改名后的行数据
        (msgs,), _ = extract_llm.ainvoke.call_args
        user_text = msgs[-1][1]
        assert "交易对手" in user_text
        assert "中信" in user_text

    @pytest.mark.asyncio
    async def test_url_key_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """input_files 用 url 而非 remote_url 也能下载。"""
        _, extract_llm = _mock_llm(monkeypatch, _PARAMS)
        _patch_fetch(monkeypatch, _make_excel_bytes(["产品", "数量", "标的", "订单号", "限价"], [["中信", 100, "600519.SH", "H-20260101-0000000001", 350]]))
        out = await swap_excel_order(
            {"raw_text": "", "input_files": [{"url": "http://f/x.xlsx"}]}
        )
        assert out["place_params"]["orderList"][0]["placeOrderWindCode"] == "600519.SH"
        assert extract_llm.ainvoke.await_count == 1

    @pytest.mark.asyncio
    async def test_no_url_error(self) -> None:
        out = await swap_excel_order(
            {"raw_text": "", "input_files": [{"type": "document", "extension": ".xlsx"}]}
        )
        assert out.get("error") is not None
        assert out["error"].node == "swap_excel_order"

    @pytest.mark.asyncio
    async def test_empty_input_files_error(self) -> None:
        out = await swap_excel_order({"raw_text": ""})
        assert out.get("error") is not None

    @pytest.mark.asyncio
    async def test_fetch_error_writes_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_llm(monkeypatch, _PARAMS)
        _patch_fetch(monkeypatch, error=RuntimeError("download failed"))
        out = await swap_excel_order(
            {"raw_text": "", "input_files": [{"remote_url": "http://f/x.xlsx"}]}
        )
        assert out["error"] is not None
        assert out["error"].node == "swap_excel_order"
        assert "download failed" in out["error"].message

    @pytest.mark.asyncio
    async def test_extract_error_writes_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_vl(monkeypatch)
        _patch_extract(monkeypatch, error=RuntimeError("extract down"))
        _patch_fetch(monkeypatch, _make_excel_bytes(["产品", "数量", "标的", "订单号", "限价"], [["中信", 100, "600519.SH", "H-20260101-0000000001", 350]]))
        out = await swap_excel_order(
            {"raw_text": "", "input_files": [{"remote_url": "http://f/x.xlsx"}]}
        )
        assert out["error"] is not None
        assert out["error"].node == "swap_excel_order"

    @pytest.mark.asyncio
    async def test_empty_sheet_yields_zero_rows(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, extract_llm = _mock_llm(monkeypatch, _PARAMS)
        _patch_fetch(monkeypatch, _make_excel_bytes(["产品"], []))
        out = await swap_excel_order(
            {"raw_text": "", "input_files": [{"remote_url": "http://f/x.xlsx"}]}
        )
        assert out.get("error") is not None
        assert not out.get("place_params")
        extract_llm.ainvoke.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rows_serialized_as_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, extract_llm = _mock_llm(monkeypatch, _PARAMS)
        _patch_fetch(monkeypatch, _make_excel_bytes(["产品", "数量", "标的"], [["中信", 100, "600519.SH"]]))
        await swap_excel_order(
            {"raw_text": "", "input_files": [{"remote_url": "http://f/x.xlsx"}]}
        )
        (msgs,), _ = extract_llm.ainvoke.call_args
        user_text = msgs[-1][1]
        sources = json.loads(user_text)["sources"]
        assert json.loads(sources["attachment:file:0:sheet:0:row:2"]) == {
            "交易对手": "中信", "数量": 100, "标的": "600519.SH",
        }

    @pytest.mark.asyncio
    async def test_modify_when_order_id_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_vl(monkeypatch)
        _patch_extract(monkeypatch, _MODIFY_PARAMS)
        _patch_fetch(monkeypatch, _make_excel_bytes(["产品", "数量", "标的", "订单号", "限价"], [["中信", 100, "600519.SH", "H-20260101-0000000001", 350]]))
        out = await swap_excel_order(
            {"raw_text": "", "input_files": [{"remote_url": "http://f/x.xlsx"}]}
        )
        assert out["expected_action"] == "modify"

    @pytest.mark.asyncio
    async def test_trace_node_and_row_count(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_llm(monkeypatch, _PARAMS)
        _patch_fetch(monkeypatch, _make_excel_bytes(["产品", "数量", "标的"], [["中信", 100, "600519.SH"], ["华泰", 100, "600519.SH"]]))
        out = await swap_excel_order(
            {"raw_text": "", "input_files": [{"remote_url": "http://f/x.xlsx"}]}
        )
        assert out["trace"][0].node == "swap_excel_order"
        assert out["trace"][0].decision == "rows=2"
        assert out["trace"][0].llm_output["prompt_name"] == "excel_extract"


# ============================================================
# _params_update 共用行为（经节点间接验证）
# ============================================================


class TestParamsUpdateShape:
    @pytest.mark.asyncio
    async def test_order_list_serialized_to_dicts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_llm(monkeypatch, _PARAMS)
        out = await swap_image_order(
            {"raw_text": "", "input_files": [{"type": "image", "url": "http://i/1.png"}]}
        )
        order_list: list[dict[str, Any]] = out["place_params"]["orderList"]
        assert isinstance(order_list, list)
        assert isinstance(order_list[0], dict)
        assert order_list[0]["placeOrderQuantity"] == 100


@pytest.mark.asyncio
class TestOcrTranscriptionBoundary:
    """转写只看图片；授权账户上下文留在 Code 绑定层，避免 OCR 凭提示补字。"""

    async def test_ocr_has_no_counterparty_inference_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ocr_llm, _ = _mock_llm(monkeypatch, _PARAMS)
        await swap_image_order(
            {
                "raw_text": "",
                "input_files": [{"type": "image", "url": "http://img/1.png"}],
                "swap_counterparties": [{"ctptyId": 7, "shortName": "对手甲", "longName": None, "sort": "A"}],
            }
        )
        text = ocr_llm.ainvoke.call_args.args[0][0]["content"][0]["text"]
        assert "{{#" not in text
        assert "对手甲" not in text  # OCR cannot turn an account hint into invented pixel text.
