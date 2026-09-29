"""联合选择后的字段写回与锁定测试。"""
import pytest

from app.subgraphs.swap.apply_picks import swap_apply_picks

_TRS: list[dict] = [
    {"ctptyId": "1", "shortName": "临沂阿凡提", "longName": "临沂阿凡提有限公司", "sort": "A"},
    {"ctptyId": "2", "shortName": "测试111", "longName": "测试有限公司", "sort": "B"},
]

_CANDIDATES: list[dict] = [
    {
        "orderId": "H-1",
        "orderSeq": 1,
        "candidates": [
            {"seq": 1, "code": "600519.SH", "name": "贵州茅台"},
            {"seq": 2, "code": "00700.HK", "name": "腾讯控股"},
        ],
    }
]


def _ap_state(**overrides: object) -> dict:
    state: dict = {
        "swap_counterparties": _TRS,
        "quote_ticker_candidates": _CANDIDATES,
        "tickers": [{"windCode": "600519.SH", "from_goats": True}, {"windCode": "00700.HK", "from_goats": True}],
        "place_params": {
            "orderList": [{"orderId": "H-1", "placeOrderShortname": "旧对手",
                           "placeOrderWindCode": "旧标的"}],
        },
        "swap_counterparty_picks": {"hasSignal": False, "picks": []},
        "swap_ticker_picks": [],
    }
    state.update(overrides)
    return state


class TestSwapApplyPicks:
    @pytest.mark.asyncio
    async def test_applies_both_picks_without_touching_expected_action(self) -> None:
        """expected_action 是顶层字段（ADR 0024 D2），汇合节点只改 orderList，不碰它。"""
        out = await swap_apply_picks(_ap_state(
            raw_text="对手B，标的2",
            swap_counterparty_picks={"hasSignal": True, "picks": [{"orderId": "H-1", "letter": "B", "evidence": "对手B", "confidence": 1.0}]},
            swap_ticker_picks=[{"orderId": "H-1", "seq": 2, "evidence": "标的2", "confidence": 1.0}],
        ))
        order = out["place_params"]["orderList"][0]
        assert order["placeOrderShortname"] == "测试111"
        assert order["placeOrderWindCode"] == "00700.HK"
        assert "expected_action" not in out["place_params"]
        assert "expected_action" not in out

    @pytest.mark.asyncio
    async def test_direct_name_and_direct_ref(self) -> None:
        out = await swap_apply_picks(_ap_state(
            raw_text="临沂阿凡提，贵州茅台",
            swap_counterparty_picks={"hasSignal": True, "picks": [{"orderId": "H-1", "directName": "临沂阿凡提", "evidence": "临沂阿凡提", "confidence": 1.0}]},
            swap_ticker_picks=[{"orderId": "H-1", "directRef": "贵州茅台", "evidence": "贵州茅台", "confidence": 1.0}],
        ))
        order = out["place_params"]["orderList"][0]
        assert order["placeOrderShortname"] == "临沂阿凡提"
        assert order["placeOrderWindCode"] == "600519.SH"

    @pytest.mark.asyncio
    async def test_no_signal_and_empty_picks_keep_original(self) -> None:
        out = await swap_apply_picks(_ap_state())
        order = out["place_params"]["orderList"][0]
        assert order["placeOrderShortname"] == "旧对手"
        assert order["placeOrderWindCode"] == "旧标的"

    @pytest.mark.asyncio
    async def test_unresolvable_picks_block_submit(self) -> None:
        out = await swap_apply_picks(_ap_state(
            raw_text="对手Z，标的99",
            swap_counterparty_picks={"hasSignal": True, "picks": [{"orderId": "H-1", "letter": "Z", "evidence": "对手Z", "confidence": 1.0}]},
            swap_ticker_picks=[{"orderId": "H-1", "seq": 99, "evidence": "标的99", "confidence": 1.0}],
        ))
        assert out.get("error") is not None
        assert "place_params" not in out

    @pytest.mark.asyncio
    async def test_missing_picks_and_place_params_default_empty(self) -> None:
        out = await swap_apply_picks({"raw_text": "x"})
        assert out["place_params"] == {"orderList": []}

    @pytest.mark.asyncio
    async def test_clears_pick_channels_after_apply(self) -> None:
        out = await swap_apply_picks(_ap_state())
        assert out["swap_counterparty_picks"] is None
        assert out["swap_ticker_picks"] is None
