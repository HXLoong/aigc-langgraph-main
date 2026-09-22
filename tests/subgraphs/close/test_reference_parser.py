"""close.place_close 链 · 引用消息解析纯函数测试。

引用消息解析规则（原 DSL v2「平仓参数提取-引用消息解析」代码节点，现以本仓实现为准）。
"""
from __future__ import annotations

from app.subgraphs.close.reference_parser import parse_reference_message


class TestEmptyInput:
    def test_no_quote_no_raw(self) -> None:
        result = parse_reference_message(None, None)
        assert result["messageType"] == "holding_list"
        assert result["successOrders"] == []
        assert result["holdingMap"] == []
        assert result["errorOrderIds"] == []
        assert result["fullCloseIds"] == []
        assert result["pureErrorOrderIds"] == []
        assert result["pureErrorOrderCount"] == 0
        assert result["holdingMapCandidateCount"] == 0
        assert result["hasSingleHoldingCandidate"] is False
        assert result["singleHoldingCandidateOrderId"] is None
        assert result["orderIds"] == []
        assert result["contractCodes"] == []

    def test_blank_quote_treated_as_empty(self) -> None:
        result = parse_reference_message("   ", "")
        assert result["messageType"] == "holding_list"
        assert result["holdingMap"] == []


class TestHoldingListPath:
    """路径 A：quote_content 是持仓列表（非平仓结果消息）。"""

    def test_parses_holding_map_with_seq_order_contract(self) -> None:
        quote = (
            "序号：1\n合约编号：OPT-LYAFT20260001\n单号：CO-20260506-85AB8526\n\n"
            "序号：2\n合约编号：OPTG-SZZSCF20260005\n单号：CO-20260506-BBBB0002\n"
        )
        result = parse_reference_message(quote, "")
        assert result["messageType"] == "holding_list"
        assert result["holdingMap"] == [
            {"seq": 1, "orderId": "CO-20260506-85AB8526", "contractId": "OPT-LYAFT20260001"},
            {"seq": 2, "orderId": "CO-20260506-BBBB0002", "contractId": "OPTG-SZZSCF20260005"},
        ]

    def test_single_candidate_facts(self) -> None:
        quote = "序号：1\n合约编号：OPT-AAA\n单号：CO-20260506-AAAA0001\n"
        result = parse_reference_message(quote, "")
        assert result["holdingMapCandidateCount"] == 1
        assert result["hasSingleHoldingCandidate"] is True
        assert result["singleHoldingCandidateOrderId"] == "CO-20260506-AAAA0001"

    def test_multi_candidate_facts_no_single(self) -> None:
        quote = (
            "序号：1\n单号：CO-20260506-AAAA0001\n\n"
            "序号：2\n单号：CO-20260506-BBBB0002\n"
        )
        result = parse_reference_message(quote, "")
        assert result["holdingMapCandidateCount"] == 2
        assert result["hasSingleHoldingCandidate"] is False
        assert result["singleHoldingCandidateOrderId"] is None

    def test_holding_without_order_id_not_a_candidate(self) -> None:
        quote = "序号：1\n合约编号：OPT-AAA\n"  # 无单号
        result = parse_reference_message(quote, "")
        assert result["holdingMapCandidateCount"] == 0
        assert result["hasSingleHoldingCandidate"] is False


class TestCloseResultPath:
    """路径 B：quote_content 是平仓结果消息（成功/参数错误/全部平仓待确认）。"""

    def test_detects_close_result_by_marker(self) -> None:
        quote = "以下平仓申请，请核对详情后确认：\n序号：1\n单号：CO-20260506-AAAA0001\n"
        result = parse_reference_message(quote, "")
        assert result["messageType"] == "close_result"

    def test_parses_success_orders(self) -> None:
        quote = (
            "以下平仓申请，请核对详情后确认：\n\n"
            "-----场外期权平仓详情-----\n"
            "序号：1\n"
            "合约编号：OPT-AAA\n"
            "单号：CO-20260506-AAAA0001\n"
            "平仓价格方式：市价单\n\n"
            "若以上订单执行平仓操作，请回复【确认平仓】"
        )
        result = parse_reference_message(quote, "")
        assert result["successOrders"] == [
            {
                "orderId": "CO-20260506-AAAA0001",
                "closeOrderNotionalDelta": None,
                "closeOrderType": None,
                "closeOrderPrice": None,
                "closeOrderPovRatio": None,
                "closeOrderAlgoStartTime": None,
                "closeOrderAlgoEndTime": None,
                "confirmFullClose": None,
            }
        ]

    def test_pending_param_order_excluded_from_success(self) -> None:
        quote = (
            "以下平仓申请，请核对详情后确认：\n\n"
            "-----场外期权平仓详情-----\n"
            "序号：1\n"
            "单号：CO-20260506-AAAA0001\n"
            "平仓价格【待补充】\n\n"
            "若以上订单执行平仓操作，请回复【确认平仓】"
        )
        result = parse_reference_message(quote, "")
        assert result["successOrders"] == []

    def test_parses_error_order_ids(self) -> None:
        quote = "期权平仓订单[CO-20260506-AACE0EE5]参数需要完善，请补充平仓名义本金"
        result = parse_reference_message(quote, "")
        assert result["messageType"] == "close_result"
        assert result["errorOrderIds"] == ["CO-20260506-AACE0EE5"]
        assert result["pureErrorOrderIds"] == ["CO-20260506-AACE0EE5"]
        assert result["pureErrorOrderCount"] == 1

    def test_parses_full_close_order_ids(self) -> None:
        quote = "期权平仓订单CO-20260306-54948DB0：合约名义本金≤100万，只能全部平仓。"
        result = parse_reference_message(quote, "")
        assert result["fullCloseIds"] == ["CO-20260306-54948DB0"]
        # errorOrderIds = errorIds ∪ fullCloseIds（合并语义）
        assert result["errorOrderIds"] == ["CO-20260306-54948DB0"]
        # pureErrorOrderIds = errorOrderIds - fullCloseIds → 空
        assert result["pureErrorOrderIds"] == []
        assert result["pureErrorOrderCount"] == 0

    def test_error_and_full_close_ids_combined_pure_error_excludes_full_close(
        self,
    ) -> None:
        quote = (
            "期权平仓订单[CO-20260506-AACE0EE5]参数需要完善\n"
            "期权平仓订单CO-20260306-54948DB0：合约名义本金≤100万，只能全部平仓。"
        )
        result = parse_reference_message(quote, "")
        assert set(result["errorOrderIds"]) == {
            "CO-20260506-AACE0EE5",
            "CO-20260306-54948DB0",
        }
        assert result["pureErrorOrderIds"] == ["CO-20260506-AACE0EE5"]
        assert result["pureErrorOrderCount"] == 1


class TestOrderIdsAndContractCodesFromRawContent:
    def test_extracts_order_ids_from_raw_content(self) -> None:
        result = parse_reference_message(None, "平 CO-20260304-AAAA0001 全部")
        assert result["orderIds"] == ["CO-20260304-AAAA0001"]

    def test_extracts_contract_codes_from_raw_content(self) -> None:
        result = parse_reference_message(None, "我想平掉OPTG-SZZSCF20260005")
        assert result["contractCodes"] == ["OPTG-SZZSCF20260005"]

    def test_dedupes_order_ids_across_sources(self) -> None:
        quote = "序号：1\n单号：CO-20260304-AAAA0001\n"
        raw = "平 CO-20260304-AAAA0001 全部"
        result = parse_reference_message(quote, raw)
        assert result["orderIds"].count("CO-20260304-AAAA0001") == 1


__all__: list[str] = []
