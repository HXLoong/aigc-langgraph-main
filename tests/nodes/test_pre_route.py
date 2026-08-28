"""pre_route(DSL v2「交易对手、候选标的提取」移植)单测。

对照源:主干工作流 code 节点——option/trs 后端预查对手 JSON + 引用消息候选标的块解析。
"""
from __future__ import annotations

from app.nodes.pre_route import parse_candidates, parse_counterparties


class TestParseCounterparties:
    def test_valid_list(self):
        raw = '[{"ctptyId": "C1", "shortName": "中信", "longName": "中信证券", "sort": "A", "extra": 1}]'
        out = parse_counterparties(raw)
        assert out == [{"ctptyId": "C1", "shortName": "中信", "longName": "中信证券", "sort": "A"}]

    def test_invalid_json(self):
        assert parse_counterparties("not json") == []

    def test_none_and_empty(self):
        assert parse_counterparties(None) == []
        assert parse_counterparties("") == []

    def test_non_list(self):
        assert parse_counterparties('{"a": 1}') == []


class TestParseCandidates:
    QUOTE = (
        "-----场外收益互换详情-----\n"
        "订单号: H-20260101-0000000001 序号: 2\n"
        "匹配到其他标的\n"
        "1. 600519.SH - 贵州茅台（已默认）\n"
        "2. 000858.SZ - 五粮液\n"
        "如果以上都不对请重新输入"
    )

    def test_basic_block(self):
        out = parse_candidates(self.QUOTE)
        assert len(out) == 1
        block = out[0]
        assert block["orderId"] == "H-20260101-0000000001"
        assert block["orderSeq"] == 2
        assert block["candidates"] == [
            {"seq": 1, "code": "600519.SH", "name": "贵州茅台"},
            {"seq": 2, "code": "000858.SZ", "name": "五粮液"},
        ]

    def test_single_line_quote(self):
        # 单行(候选间仅空格)也不把后续候选并入前一个 name
        quote = "匹配到其他标的 1. 600519.SH - 贵州茅台 2. 000858.SZ - 五粮液 如果以上都不对"
        out = parse_candidates(quote)
        assert out[0]["candidates"][0]["name"] == "贵州茅台"
        assert out[0]["candidates"][1]["name"] == "五粮液"

    def test_no_candidate_block(self):
        assert parse_candidates("普通引用消息") == []

    def test_empty(self):
        assert parse_candidates(None) == []
        assert parse_candidates("") == []
