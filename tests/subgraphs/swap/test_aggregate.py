"""swap.aggregate · 互换-标的对手覆盖聚合 纯函数测试（Dify code 节点 1:1）。

覆盖 `app/subgraphs/swap/aggregate.py` 的 7 个纯函数：
`build_id_to_seq` / `match_order_index` / `resolve_candidate_block` /
`windcode_from_pick` / `shortname_from_pick` / `apply_underlying` / `apply_counterparty`。

对齐 Dify「互换-标的对手覆盖聚合」code 节点（spec/code_nodes/互换-标的对手覆盖聚合.py）。
核心不变量：**非破坏性覆盖** —— 指针解析不到值时保留原值，绝不置 None。

测试方法：G1 纯函数确定性（无 mock / 无 IO / 直接断言输入输出）。
"""
from __future__ import annotations

from app.subgraphs.swap.aggregate import (
    apply_counterparty,
    apply_underlying,
    build_id_to_seq,
    match_order_index,
    resolve_candidate_block,
    shortname_from_pick,
    windcode_from_pick,
)

# ============================================================
# 固定夹具：2 笔订单的候选标的块 + 3 个交易对手
# ============================================================

#: candidate_list：订单 H-1 有 2 个候选标的，H-2 有 1 个
_CANDIDATES: list[dict] = [
    {
        "orderId": "H-1",
        "orderSeq": 1,
        "candidates": [
            {"seq": 1, "code": "600519.SH", "name": "贵州茅台"},
            {"seq": 2, "code": "00700.HK", "name": "腾讯控股"},
        ],
    },
    {
        "orderId": "H-2",
        "orderSeq": 2,
        "candidates": [{"seq": 1, "code": "NVDA.O", "name": "NVIDIA"}],
    },
]

#: swap_counterparties（shortname_list）
_TRS: list[dict] = [
    {"ctptyId": "1", "shortName": "临沂阿凡提", "longName": "临沂阿凡提有限公司", "sort": "A"},
    {"ctptyId": "2", "shortName": "测试111", "longName": "测试有限公司", "sort": "B"},
    {"ctptyId": "3", "shortName": "23", "longName": "二十三", "sort": "D"},
]


# ============================================================
# build_id_to_seq
# ============================================================


class TestBuildIdToSeq:
    def test_empty_list(self) -> None:
        assert build_id_to_seq([]) == {}

    def test_maps_order_id_to_order_seq(self) -> None:
        assert build_id_to_seq(_CANDIDATES) == {"H-1": 1, "H-2": 2}

    def test_skips_block_without_order_id(self) -> None:
        blocks = [{"orderSeq": 9}, {"orderId": "H-9", "orderSeq": 3}]
        assert build_id_to_seq(blocks) == {"H-9": 3}

    def test_order_id_none_is_skipped(self) -> None:
        blocks = [{"orderId": None, "orderSeq": 1}]
        assert build_id_to_seq(blocks) == {}


# ============================================================
# match_order_index
# ============================================================


class TestMatchOrderIndex:
    def test_single_order_rejects_foreign_identity(self) -> None:
        """单订单也必须匹配显式订单号，不能越过用户指定范围。"""
        assert match_order_index({"orderId": "X"}, [{"orderId": "H-1"}], {}, single=True) == -1

    def test_match_by_order_id(self) -> None:
        orders = [{"orderId": "H-1"}, {"orderId": "H-2"}]
        assert match_order_index({"orderId": "H-2"}, orders, {}, single=False) == 1

    def test_match_by_order_seq_via_reverse_lookup(self) -> None:
        """orderId 对不上时用 orderSeq 反查 id_to_seq。"""
        orders = [{"orderId": "H-1"}, {"orderId": "H-2"}]
        id_to_seq = build_id_to_seq(_CANDIDATES)
        assert match_order_index({"orderSeq": 2}, orders, id_to_seq, single=False) == 1

    def test_match_by_idx_fallback(self) -> None:
        orders = [{"orderId": "H-1"}, {"orderId": "H-2"}]
        assert match_order_index({"idx": 1}, orders, {}, single=False) == 1

    def test_idx_out_of_range_returns_minus_one(self) -> None:
        orders = [{"orderId": "H-1"}]
        assert match_order_index({"idx": 5}, orders, {}, single=False) == -1

    def test_idx_non_int_ignored(self) -> None:
        orders = [{"orderId": "H-1"}]
        assert match_order_index({"idx": "0"}, orders, {}, single=False) == -1

    def test_no_signal_returns_minus_one(self) -> None:
        orders = [{"orderId": "H-1"}]
        assert match_order_index({}, orders, {}, single=False) == -1

    def test_conflicting_order_id_and_idx_rejected(self) -> None:
        orders = [{"orderId": "H-1"}, {"orderId": "H-2"}]
        assert match_order_index({"orderId": "H-2", "idx": 0}, orders, {}, single=False) == -1


# ============================================================
# resolve_candidate_block
# ============================================================


class TestResolveCandidateBlock:
    def test_by_order_id(self) -> None:
        assert resolve_candidate_block({"orderId": "H-2"}, _CANDIDATES) is _CANDIDATES[1]

    def test_by_order_seq(self) -> None:
        assert resolve_candidate_block({"orderSeq": 2}, _CANDIDATES) is _CANDIDATES[1]

    def test_by_idx(self) -> None:
        assert resolve_candidate_block({"idx": 1}, _CANDIDATES) is _CANDIDATES[1]

    def test_single_candidate_fallback(self) -> None:
        """候选块只有一个时，无指针也回落到它。"""
        one = [{"orderId": "H-1", "candidates": [{"seq": 1, "code": "A"}]}]
        assert resolve_candidate_block({}, one) is one[0]

    def test_no_match_returns_none(self) -> None:
        assert resolve_candidate_block({"orderId": "NOPE"}, _CANDIDATES) is None


# ============================================================
# windcode_from_pick（LLM-A 指针 → 真实 windCode）
# ============================================================


class TestWindcodeFromPick:
    def test_seq_resolves_to_candidate_code(self) -> None:
        pick = {"orderId": "H-1", "seq": 2}
        assert windcode_from_pick(pick, _CANDIDATES) == "00700.HK"

    def test_seq_not_found_returns_none(self) -> None:
        """seq 在块内找不到 → None（非破坏，调用方保留原值）。"""
        pick = {"orderId": "H-1", "seq": 99}
        assert windcode_from_pick(pick, _CANDIDATES) is None

    def test_seq_without_block_returns_none(self) -> None:
        assert windcode_from_pick({"seq": 1}, _CANDIDATES) is None

    def test_direct_ref_exact_code(self) -> None:
        pick = {"orderId": "H-1", "directRef": "600519.SH"}
        assert windcode_from_pick(pick, _CANDIDATES) == "600519.SH"

    def test_direct_ref_exact_name(self) -> None:
        pick = {"orderId": "H-1", "directRef": "腾讯控股"}
        assert windcode_from_pick(pick, _CANDIDATES) == "00700.HK"

    def test_direct_ref_fuzzy_name(self) -> None:
        """name 与 ref 互相包含即命中。"""
        pick = {"orderId": "H-1", "directRef": "腾讯"}
        assert windcode_from_pick(pick, _CANDIDATES) == "00700.HK"

    def test_direct_ref_unmatched_returns_raw_ref(self) -> None:
        """匹配不到候选时原样返回用户输入（Dify 行为）。"""
        pick = {"orderId": "H-1", "directRef": " 999999.SH "}
        assert windcode_from_pick(pick, _CANDIDATES) is None

    def test_no_seq_no_ref_returns_none(self) -> None:
        assert windcode_from_pick({"orderId": "H-1"}, _CANDIDATES) is None


# ============================================================
# shortname_from_pick（LLM-B 指针 → 真实 shortName）
# ============================================================


class TestShortnameFromPick:
    def test_direct_name_exact(self) -> None:
        assert shortname_from_pick({"directName": "临沂阿凡提"}, _TRS) == "临沂阿凡提"

    def test_direct_name_fuzzy(self) -> None:
        assert shortname_from_pick({"directName": "阿凡提"}, _TRS) == "临沂阿凡提"

    def test_direct_name_not_found_returns_none(self) -> None:
        assert shortname_from_pick({"directName": "不存在"}, _TRS) is None

    def test_letter_maps_to_sort(self) -> None:
        assert shortname_from_pick({"letter": "b"}, _TRS) == "测试111"
        assert shortname_from_pick({"letter": "D"}, _TRS) == "23"

    def test_ordinal_maps_to_letter(self) -> None:
        """ordinal N → 第 N 个选项字母（1 → 'A'，2 → 'B'）。"""
        assert shortname_from_pick({"ordinal": 1}, _TRS) == "临沂阿凡提"
        assert shortname_from_pick({"ordinal": 2}, _TRS) == "测试111"

    def test_ordinal_beyond_option_count_returns_none(self) -> None:
        """ordinal 上界是候选数量（3），不是 26 —— 第 4 个选项不存在。"""
        assert shortname_from_pick({"ordinal": 4}, _TRS) is None
        assert shortname_from_pick({"ordinal": 9}, _TRS) is None
        assert shortname_from_pick({"ordinal": 0}, _TRS) is None

    def test_sort_not_found_returns_none(self) -> None:
        assert shortname_from_pick({"letter": "Z"}, _TRS) is None

    def test_no_signal_returns_none(self) -> None:
        assert shortname_from_pick({}, _TRS) is None


# ============================================================
# apply_underlying（标的覆盖，就地修改）
# ============================================================


class TestApplyUnderlying:
    def test_empty_candidate_list_skips(self) -> None:
        orders = [{"placeOrderWindCode": "OLD"}]
        apply_underlying(orders, [{"seq": 1}], [])
        assert orders == [{"placeOrderWindCode": "OLD"}]

    def test_seq_pick_overwrites_windcode(self) -> None:
        orders = [{"orderId": "H-1", "placeOrderWindCode": "OLD"}]
        apply_underlying(orders, [{"orderId": "H-1", "seq": 2}], _CANDIDATES)
        assert orders[0]["placeOrderWindCode"] == "00700.HK"

    def test_unresolved_pick_keeps_original(self) -> None:
        """非破坏性：解析为空 → 保留原值，绝不置 None。"""
        orders = [{"orderId": "H-1", "placeOrderWindCode": "OLD"}]
        apply_underlying(orders, [{"orderId": "H-1", "seq": 99}], _CANDIDATES)
        assert orders[0]["placeOrderWindCode"] == "OLD"

    def test_no_pick_keeps_original(self) -> None:
        orders = [{"orderId": "H-1", "placeOrderWindCode": "OLD"}]
        apply_underlying(orders, [], _CANDIDATES)
        assert orders[0]["placeOrderWindCode"] == "OLD"

    def test_multiple_picks_first_non_empty_wins(self) -> None:
        orders = [{"orderId": "H-1", "placeOrderWindCode": "OLD"}]
        picks = [
            {"orderId": "H-1", "seq": 99},  # 解析不到
            {"orderId": "H-1", "seq": 1},  # 命中
        ]
        apply_underlying(orders, picks, _CANDIDATES)
        assert orders[0]["placeOrderWindCode"] == "600519.SH"

    def test_single_order_pick_without_id_uses_single_block_fallback(self) -> None:
        """单订单 + 单候选块：指针无 orderId 时靠 resolve_candidate_block 的单块回落。"""
        one_block = [
            {
                "orderId": "H-1",
                "candidates": [{"seq": 1, "code": "600519.SH", "name": "贵州茅台"}],
            }
        ]
        orders = [{"placeOrderWindCode": "OLD"}]
        apply_underlying(orders, [{"seq": 1}], one_block)
        assert orders[0]["placeOrderWindCode"] == "600519.SH"

    def test_single_order_ambiguous_pick_keeps_original(self) -> None:
        """单订单 + 多候选块 + 无定位指针 → 无法解析，保留原值。"""
        orders = [{"placeOrderWindCode": "OLD"}]
        apply_underlying(orders, [{"seq": 1}], _CANDIDATES)
        assert orders[0]["placeOrderWindCode"] == "OLD"

    def test_multi_order_routed_by_order_id(self) -> None:
        orders = [
            {"orderId": "H-1", "placeOrderWindCode": "OLD-1"},
            {"orderId": "H-2", "placeOrderWindCode": "OLD-2"},
        ]
        apply_underlying(orders, [{"orderId": "H-2", "seq": 1}], _CANDIDATES)
        assert orders[0]["placeOrderWindCode"] == "OLD-1"
        assert orders[1]["placeOrderWindCode"] == "NVDA.O"

    def test_preserves_other_fields(self) -> None:
        orders = [{"orderId": "H-1", "placeOrderWindCode": "OLD", "placeOrderQuantity": 100}]
        apply_underlying(orders, [{"orderId": "H-1", "seq": 1}], _CANDIDATES)
        assert orders[0]["placeOrderQuantity"] == 100


# ============================================================
# apply_counterparty（对手覆盖，就地修改）
# ============================================================


class TestApplyCounterparty:
    def test_no_signal_skips(self) -> None:
        orders = [{"placeOrderShortname": "OLD"}]
        apply_counterparty(orders, False, [{"letter": "A"}], _TRS)
        assert orders == [{"placeOrderShortname": "OLD"}]

    def test_empty_order_list_skips(self) -> None:
        orders: list[dict] = []
        apply_counterparty(orders, True, [{"letter": "A"}], _TRS)
        assert orders == []

    def test_letter_pick_overwrites_shortname(self) -> None:
        orders = [{"placeOrderShortname": "OLD"}]
        apply_counterparty(orders, True, [{"letter": "B"}], _TRS)
        assert orders[0]["placeOrderShortname"] == "测试111"

    def test_direct_name_pick_overwrites(self) -> None:
        orders = [{"placeOrderShortname": "OLD"}]
        apply_counterparty(orders, True, [{"directName": "23"}], _TRS)
        assert orders[0]["placeOrderShortname"] == "23"

    def test_unresolved_pick_keeps_original(self) -> None:
        orders = [{"placeOrderShortname": "OLD"}]
        apply_counterparty(orders, True, [{"letter": "Z"}], _TRS)
        assert orders[0]["placeOrderShortname"] == "OLD"

    def test_multiple_picks_first_non_empty_wins(self) -> None:
        orders = [{"placeOrderShortname": "OLD"}]
        picks = [{"letter": "Z"}, {"letter": "A"}]
        apply_counterparty(orders, True, picks, _TRS)
        assert orders[0]["placeOrderShortname"] == "临沂阿凡提"

    def test_multi_order_routed_by_order_id(self) -> None:
        orders = [
            {"orderId": "H-1", "placeOrderShortname": "OLD-1"},
            {"orderId": "H-2", "placeOrderShortname": "OLD-2"},
        ]
        apply_counterparty(orders, True, [{"orderId": "H-2", "letter": "A"}], _TRS)
        assert orders[0]["placeOrderShortname"] == "OLD-1"
        assert orders[1]["placeOrderShortname"] == "临沂阿凡提"

    def test_multi_order_routed_by_idx(self) -> None:
        orders = [{"placeOrderShortname": "OLD-1"}, {"placeOrderShortname": "OLD-2"}]
        apply_counterparty(orders, True, [{"idx": 1, "letter": "A"}], _TRS)
        assert orders[1]["placeOrderShortname"] == "临沂阿凡提"

    def test_preserves_other_fields(self) -> None:
        orders = [{"placeOrderShortname": "OLD", "placeOrderQuantity": 100}]
        apply_counterparty(orders, True, [{"letter": "A"}], _TRS)
        assert orders[0]["placeOrderQuantity"] == 100


class TestShortnameFromPickUniqueness:
    """提示词治理评估 SW-INC-06：select_counterparty.md 2026-09-11 版把唯一性判断交给代码
    （|M|=1 才是唯一简写，多命中不得按列表顺序取第一项），对齐 Dify code 节点 1780652971845
    shortname_from_pick：精确 → 唯一连续子串 → None。"""

    _AMBIGUOUS = [
        {"ctptyId": "1", "shortName": "测试111", "longName": "测试一", "sort": "A"},
        {"ctptyId": "2", "shortName": "测试222", "longName": "测试二", "sort": "B"},
        {"ctptyId": "3", "shortName": "临沂阿凡提", "longName": "临沂阿凡提有限公司", "sort": "C"},
    ]

    def test_multi_match_returns_none_not_first(self) -> None:
        assert shortname_from_pick({"directName": "测试"}, self._AMBIGUOUS) is None

    def test_unique_substring_matches(self) -> None:
        assert shortname_from_pick({"directName": "阿凡提"}, self._AMBIGUOUS) == "临沂阿凡提"

    def test_exact_wins_over_substring(self) -> None:
        assert shortname_from_pick({"directName": "测试111"}, self._AMBIGUOUS) == "测试111"
