"""option.extract_place 节点测试（请求下单，确定性提取，无 LLM）。

行为 1:1 对照原提示词规约：

- A 类（orderType / notionalAmount / limitPrice / povRatio / twap / shortName /
  hasFastExecutionIntent）只取自 raw_content
- B 类（orderId / stockCode / optionType / tenor / strikePercentage）raw 优先、引用回执兜底
- orderType 关键词优先级 TWAP > POV（含"跟量"）> 限价单 > 市价单，与出现顺序无关
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.subgraphs.option import extract_place as ep_module
from app.subgraphs.option.extract_place import option_extract_place

_QUOTE_CARD = (
    "-----场外期权询价详情-----\r\n"
    "Q-20250616-000011\r\n"
    "标的代码：300098.SZ；欧式看涨；80%\r\n"
    "期限待补充，请引用本消息回复期限。如需下单，请提供建仓参数。"
)

#: 批量询价卡（1M/2M 两笔订单 + 对手选项列表，case-026 形态）
_BATCH_QUOTE_CARD = (
    "-----场外期权询价详情-----\r\n"
    "Q-20250616-000011\r\n"
    "标的代码：600519.SH；欧式看涨；80%\r\n"
    "期限：1M\r\n"
    "Q-20250616-000012\r\n"
    "期限：2M\r\n"
    "本群可选交易对手列表：A.临沂阿凡提 B.11125测试短名(张天琪专用)\r\n"
)


def _patch(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """patch 后端调用 + 禁止 LLM。"""
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "backend reply"})
    monkeypatch.setattr(ep_module, "call_option_backend", backend)

    def _forbid(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("去 LLM 化节点不应调用 LLM")

    monkeypatch.setattr(ep_module, "get_qwen_thinking", _forbid, raising=False)
    return backend


def _item(result: dict[str, Any], index: int = 0) -> dict[str, Any]:
    return result["place_params"]["orderList"][index]


@pytest.mark.asyncio
class TestOptionExtractPlaceNode:
    async def test_market_order_with_amount(self, monkeypatch: pytest.MonkeyPatch) -> None:
        backend = _patch(monkeypatch)
        result = await option_extract_place(
            {"raw_text": "市价下单100万", "quote_content": "Q-20250616-000011"}
        )
        item = _item(result)
        assert item["orderId"] == "Q-20250616-000011"
        assert item["orderType"] == "市价单"
        assert item["notionalAmount"] == "1000000"
        assert item["hasFastExecutionIntent"] is False
        assert backend.await_args.kwargs["intent"] == "place_order_from_quote"

    @pytest.mark.parametrize(
        ("raw", "order_type", "limit_price", "pov_ratio"),
        [
            ("100W，限价12，POV", "POV", 12.0, None),
            ("100W，POV，限价12", "POV", 12.0, None),
            ("100W，POV25，限价6.3", "POV", 6.3, 25.0),
            ("100W，限价6.3，POV25", "POV", 6.3, 25.0),
            ("100W，限价12", "限价单", 12.0, None),
        ],
    )
    async def test_keyword_priority_order_independent(
        self,
        monkeypatch: pytest.MonkeyPatch,
        raw: str,
        order_type: str,
        limit_price: float,
        pov_ratio: float | None,
    ) -> None:
        _patch(monkeypatch)
        result = await option_extract_place(
            {"raw_text": raw, "quote_content": "Q-20250616-000011"}
        )
        item = _item(result)
        assert item["orderType"] == order_type
        assert item["limitPrice"] == limit_price
        assert item["povRatio"] == pov_ratio
        assert item["notionalAmount"] == "1000000"

    async def test_twap_normalizes_times(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch)
        result = await option_extract_place(
            {"raw_text": "200W，限价8，TWAP 9:30-15:00", "quote_content": "Q-1"}
        )
        item = _item(result)
        assert item["orderType"] == "TWAP"
        assert item["limitPrice"] == 8.0
        assert item["twapStartTime"] == "09:30"
        assert item["twapEndTime"] == "15:00"
        assert item["notionalAmount"] == "2000000"

    async def test_limit_keyword_without_number_yields_null(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch)
        result = await option_extract_place(
            {"raw_text": "1W 限价下单", "quote_content": "Q-1"}
        )
        item = _item(result)
        assert item["orderType"] == "限价单"
        assert item["limitPrice"] is None
        assert item["notionalAmount"] == "10000"

    async def test_limit_then_amount_is_not_price(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch)
        result = await option_extract_place(
            {"raw_text": "限价 100万 下单", "quote_content": "Q-1"}
        )
        item = _item(result)
        assert item["limitPrice"] is None
        assert item["notionalAmount"] == "1000000"

    async def test_pov_without_ratio_is_null(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch)
        result = await option_extract_place(
            {"raw_text": "50万 POV 下单", "quote_content": "Q-1"}
        )
        item = _item(result)
        assert item["orderType"] == "POV"
        assert item["povRatio"] is None

    @pytest.mark.parametrize(
        ("raw", "order_type", "fast"),
        [
            ("最大跟量 100万 市价下单", "POV", True),
            ("尽快成交 100万", None, True),
            ("跟量25 100万市价", "POV", False),
            ("市价跟量 100万", "POV", False),
        ],
    )
    async def test_fast_execution_intent(
        self,
        monkeypatch: pytest.MonkeyPatch,
        raw: str,
        order_type: str | None,
        fast: bool,
    ) -> None:
        _patch(monkeypatch)
        result = await option_extract_place({"raw_text": raw, "quote_content": "Q-1"})
        item = _item(result)
        assert item["hasFastExecutionIntent"] is fast
        assert item["orderType"] == order_type

    async def test_multiple_order_ids_from_quote(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch)
        result = await option_extract_place(
            {
                "raw_text": "市价下单",
                "quote_content": "Q-20250616-000011、Q-20250616-000012",
            }
        )
        order_list = result["place_params"]["orderList"]
        assert [o["orderId"] for o in order_list] == [
            "Q-20250616-000011",
            "Q-20250616-000012",
        ]
        assert all(o["orderType"] == "市价单" for o in order_list)

    async def test_ordinal_segments_map_each_order_params(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """多单批量补参（case-026）：第 N 个单段 → 引用回执第 N 个订单，含各自对手字母。"""
        _patch(monkeypatch)
        result = await option_extract_place(
            {
                "raw_text": "第一个单 最大跟量，200万，A，限价10\n第二个单 限价6，100万，B",
                "quote_content": _BATCH_QUOTE_CARD,
            }
        )
        order_list = result["place_params"]["orderList"]
        assert [o["orderId"] for o in order_list] == [
            "Q-20250616-000011",
            "Q-20250616-000012",
        ]
        first, second = order_list
        assert first["orderType"] == "POV"
        assert first["notionalAmount"] == "2000000"
        assert first["limitPrice"] == 10.0
        assert first["shortName"] == "临沂阿凡提"
        assert first["hasFastExecutionIntent"] is True
        assert second["orderType"] == "限价单"
        assert second["notionalAmount"] == "1000000"
        assert second["limitPrice"] == 6.0
        assert second["shortName"] == "11125测试短名(张天琪专用)"
        assert second["hasFastExecutionIntent"] is False

    async def test_ordinal_segments_require_matching_order_ids(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """越界序号给出确定性纠错，不能把整段参数扩散到已有订单。"""
        _patch(monkeypatch)
        result = await option_extract_place(
            {
                "raw_text": "第一个单 限价10，200万\n第二个单 市价 100万",
                "quote_content": "Q-20250616-000011",
            }
        )
        assert not result.get("place_params")
        assert "序号" in result["reply_text"]

    async def test_b_class_from_card(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch)
        result = await option_extract_place(
            {"raw_text": "市价下单", "quote_content": _QUOTE_CARD}
        )
        item = _item(result)
        assert item["orderId"] == "Q-20250616-000011"
        assert item["stockCode"] == "300098.SZ"
        assert item["optionType"] == "欧式看涨"
        assert item["strikePercentage"] == 80.0
        assert item["tenor"] is None

    async def test_raw_tenor_overrides_card(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch)
        result = await option_extract_place(
            {"raw_text": "换成2M 市价下单", "quote_content": _QUOTE_CARD}
        )
        item = _item(result)
        assert item["tenor"] == "2M"
        assert item["stockCode"] == "300098.SZ"

    async def test_short_name_label_full_capture(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch)
        result = await option_extract_place(
            {
                "raw_text": "交易对手：11125测试短名(张天琪专用) 市价下单",
                "quote_content": "Q-1",
            }
        )
        assert _item(result)["shortName"] == "11125测试短名(张天琪专用)"

    async def test_short_name_option_letter_resolves_from_quote(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch)
        result = await option_extract_place(
            {
                "raw_text": "市价下单 B",
                "quote_content": (
                    "本群可选交易对手列表：A.临沂阿凡提 B.11125测试短名(张天琪专用)"
                ),
            }
        )
        assert _item(result)["shortName"] == "11125测试短名(张天琪专用)"

    @pytest.mark.parametrize(
        ("raw", "expected_short_name"),
        [
            ("200万，市价下单，交易对手选A", "临沂阿凡提"),
            ("交易对手：A，市价下单", "临沂阿凡提"),
            ("100万 市价下单 交易对手选择B", "11125测试短名(张天琪专用)"),
        ],
    )
    async def test_short_name_select_letter_resolves_from_quote(
        self,
        monkeypatch: pytest.MonkeyPatch,
        raw: str,
        expected_short_name: str,
    ) -> None:
        """标签 / 选择动词后的选项字母（case-029「交易对手选A」）必须解析成完整名称，不能原样透传。"""
        _patch(monkeypatch)
        result = await option_extract_place(
            {"raw_text": raw, "quote_content": _BATCH_QUOTE_CARD}
        )
        assert _item(result)["shortName"] == expected_short_name

    async def test_no_order_keeps_placeholder_item(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch)
        result = await option_extract_place({"raw_text": "市价下单100万"})
        order_list = result["place_params"]["orderList"]
        assert len(order_list) == 1
        assert order_list[0]["orderId"] is None
        assert order_list[0]["orderType"] == "市价单"

    async def test_writes_trace_and_passes_backend_order_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _patch(monkeypatch)
        result = await option_extract_place(
            {
                "raw_text": "市价下单",
                "quote_content": "Q-20250616-000011、Q-20250616-000012",
            }
        )
        trace = result["trace"]
        assert trace[0].node == "option_extract_place"
        assert "deterministic" in trace[0].decision
        assert "action=place" in trace[0].decision
        assert "orders=2" in trace[0].decision
        assert backend.await_args.kwargs["order_list"] == result["place_params"]["orderList"]
