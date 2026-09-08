"""swap.quote_hints · 互换-规整引用补参摘要 测试（Dify code 节点 1:1）。

覆盖 `app/subgraphs/swap/quote_hints.py`：
- `refine_quote_hints`：把机器人上一条「订单详情 + 请补充参数」消息剥成
  「订单号(多单含序号) + 待补字段名列表」，剥掉订单正文 / 候选标的 / 候选对手
- `_normalize_raw_content`：确定性数字标注（价格关键词/@ 后数字按限价，
  其余英文逗号整数按委托数量），对应 Dify 变量 `raw_content_for_llm`

消费方：`app/subgraphs/swap/place_order.py:106`（`hints = refine_quote_hints(...)`）。
测试方法：G1 纯函数确定性（无 mock / 无 IO）。
"""
from __future__ import annotations

from app.subgraphs.swap.quote_hints import _normalize_raw_content, refine_quote_hints

O1 = "H-20260101-0000000001"
O2 = "H-20260101-0000000002"


# ============================================================
# refine_quote_hints · 无效引用
# ============================================================


class TestInvalidQuote:
    def test_none(self) -> None:
        assert refine_quote_hints(None)["quote_param_hints"] == ""

    def test_empty_string(self) -> None:
        assert refine_quote_hints("")["quote_param_hints"] == ""

    def test_whitespace_only(self) -> None:
        assert refine_quote_hints("   \n\t ")["quote_param_hints"] == ""

    def test_null_literal_case_insensitive(self) -> None:
        assert refine_quote_hints("null")["quote_param_hints"] == ""
        assert refine_quote_hints("NULL")["quote_param_hints"] == ""
        assert refine_quote_hints("  Null  ")["quote_param_hints"] == ""

    def test_raw_content_still_normalized_when_quote_invalid(self) -> None:
        out = refine_quote_hints(None, "买入 TSM2625股")
        assert out["quote_param_hints"] == ""
        assert out["raw_content_for_llm"] == "买入 TSM【委托数量：2625；数量单位：SHARE】"


# ============================================================
# refine_quote_hints · 单订单补参
# ============================================================


class TestSingleOrderHints:
    def test_hint_mark_extracted(self) -> None:
        quote = f"单号：{O1}\n【请补充参数：限定价格】\n请引用本消息补充"
        assert refine_quote_hints(quote)["quote_param_hints"] == (
            f"订单 {O1} 需要补充：限定价格"
        )

    def test_pending_line_fallback(self) -> None:
        """回退形态「X：【待补充】」也识别为待补字段。"""
        quote = f"单号：{O1}\n限定价格：【待补充】"
        assert refine_quote_hints(quote)["quote_param_hints"] == (
            f"订单 {O1} 需要补充：限定价格"
        )

    def test_multiple_fields_joined_and_deduped(self) -> None:
        quote = (
            f"单号：{O1}\n"
            "【请补充参数：限定价格】\n"
            "【请补充参数：价格类型】\n"
            "【请补充参数：限定价格】\n"
        )
        assert refine_quote_hints(quote)["quote_param_hints"] == (
            f"订单 {O1} 需要补充：限定价格、价格类型"
        )

    def test_field_alias_normalized(self) -> None:
        """旧名「可委托数量」归一到「可见委托量」。"""
        quote = f"单号：{O1}\n【请补充参数：可委托数量】"
        assert refine_quote_hints(quote)["quote_param_hints"] == (
            f"订单 {O1} 需要补充：可见委托量"
        )

    def test_no_order_id_omits_head(self) -> None:
        """引用消息里没有单号（如平仓持仓选项卡）时只输出字段行。"""
        quote = "【请补充参数：委托数量】"
        assert refine_quote_hints(quote)["quote_param_hints"] == "需要补充：委托数量"

    def test_close_option_lines_appended(self) -> None:
        """平仓持仓选项卡（第N笔：xxx（yyy））追加在补参行之后。"""
        quote = f"单号：{O1}\n【请补充参数：委托数量】\n第1笔：中信（沪深300看涨）"
        hints = refine_quote_hints(quote)["quote_param_hints"]
        assert hints == f"订单 {O1} 需要补充：委托数量\n第1笔：中信（沪深300看涨）"

    def test_hint_mark_but_no_fields_returns_empty(self) -> None:
        """有补参标记但正则抽不出字段名 → 降级空串。"""
        quote = f"单号：{O1}\n【请补充参数：】"
        assert refine_quote_hints(quote)["quote_param_hints"] == ""


# ============================================================
# refine_quote_hints · 参数齐全（改参语义）
# ============================================================


class TestCompleteParamsMeansModify:
    def test_single_order_without_hint_marker(self) -> None:
        quote = f"-----场外收益互换详情-----\n单号：{O1}\n标的代码：600519.SH"
        assert refine_quote_hints(quote)["quote_param_hints"] == (
            f"订单 {O1}（参数齐全，本次输入按改参处理）"
        )

    def test_seq_pair_variant(self) -> None:
        quote = f"序号：1 单号：{O1}\n序号：2 单号：{O2}"
        assert refine_quote_hints(quote)["quote_param_hints"] == (
            f"订单 {O1}（序号1，参数齐全，本次输入按改参处理）\n"
            f"订单 {O2}（序号2，参数齐全，本次输入按改参处理）"
        )

    def test_multiple_bare_order_ids_deduped(self) -> None:
        quote = f"单号：{O1} 又见 {O1} 还有 {O2}"
        assert refine_quote_hints(quote)["quote_param_hints"] == (
            f"订单 {O1}（参数齐全，本次输入按改参处理）\n"
            f"订单 {O2}（参数齐全，本次输入按改参处理）"
        )


# ============================================================
# refine_quote_hints · 多订单切片
# ============================================================


class TestMultiOrderHints:
    def test_two_orders_sliced_by_head(self) -> None:
        quote = (
            f"订单{O1}（序号1）：\n【请补充参数：限定价格】\n"
            f"订单{O2}（序号2）：\n【请补充参数：交易对手】"
        )
        assert refine_quote_hints(quote)["quote_param_hints"] == (
            f"订单 {O1}（序号1） 需要补充：限定价格\n"
            f"订单 {O2}（序号2） 需要补充：交易对手"
        )

    def test_head_without_seq_uses_seq_pair_fallback(self) -> None:
        """表头没写序号时，用「序号：N 单号：H-...」配对兜底。"""
        quote = f"订单{O1}：\n【请补充参数：限定价格】\n序号：7 单号：{O1}"
        assert refine_quote_hints(quote)["quote_param_hints"] == (
            f"订单 {O1}（序号7） 需要补充：限定价格"
        )

    def test_mixed_state_complete_order_gets_modify_line(self) -> None:
        """一笔待补 + 一笔参数齐全 → 齐全的那笔输出改参行。"""
        quote = f"订单{O1}（序号1）：\n【请补充参数：限定价格】\n序号：2 单号：{O2}"
        assert refine_quote_hints(quote)["quote_param_hints"] == (
            f"订单 {O1}（序号1） 需要补充：限定价格\n"
            f"订单 {O2}（序号2，参数齐全，本次输入按改参处理）"
        )

    def test_heading_without_fields_skipped(self) -> None:
        """多订单切片下，某笔订单头下没有待补字段 → 该单不产生行。"""
        quote = (
            f"订单{O1}（序号1）：\n【请补充参数：限定价格】\n"
            f"订单{O2}（序号2）：\n标的代码：600519.SH"
        )
        assert refine_quote_hints(quote)["quote_param_hints"] == (
            f"订单 {O1}（序号1） 需要补充：限定价格"
        )

    def test_bare_order_id_without_hint_enters_modify_branch(self) -> None:
        """引用里只有订单号、无任何补参标记 → 走「参数齐全」改参分支。"""
        quote = f"订单{O1}（序号1）：\n标的代码：600519.SH"
        assert refine_quote_hints(quote)["quote_param_hints"] == (
            f"订单 {O1}（参数齐全，本次输入按改参处理）"
        )


# ============================================================
# _normalize_raw_content · 数量标注
# ============================================================


class TestNormalizeQuantity:
    def test_glued_alpha_share_quantity(self) -> None:
        assert _normalize_raw_content("TSM2625股") == "TSM【委托数量：2625；数量单位：SHARE】"

    def test_explicit_share_quantity(self) -> None:
        assert _normalize_raw_content("买入5000股") == "买入【委托数量：5000；数量单位：SHARE】"

    def test_hand_unit_maps_to_hand(self) -> None:
        assert _normalize_raw_content("买入1000手") == "买入【委托数量：1000；数量单位：HAND】"

    def test_wan_scale_multiplied(self) -> None:
        assert _normalize_raw_content("1.5万股") == "【委托数量：15000；数量单位：SHARE】"

    def test_wan_scale_with_hand(self) -> None:
        assert _normalize_raw_content("2万手") == "【委托数量：20000；数量单位：HAND】"

    def test_non_integer_quantity_left_untouched(self) -> None:
        """1.5 股不取整 → 原样保留（不猜）。"""
        assert _normalize_raw_content("1.5股") == "1.5股"

    def test_glued_symbol_with_exchange_suffix(self) -> None:
        """带交易所后缀的美股代码紧贴股数（PDD.O100股）。"""
        assert _normalize_raw_content("PDD.O100股") == "PDD.O【委托数量：100；数量单位：SHARE】"

    def test_symbol_then_dot_number_left_untouched(self) -> None:
        """AAPL.100股 不是合法代码形态（点后需字母），不标注。"""
        assert _normalize_raw_content("AAPL.100股") == "AAPL.100股"


# ============================================================
# _normalize_raw_content · 价格标注
# ============================================================


class TestNormalizePrice:
    def test_at_price(self) -> None:
        assert _normalize_raw_content("卖出96000股 @ 8.6835") == (
            "卖出【委托数量：96000；数量单位：SHARE】 【价格类型：LimitOrder；限定价格：8.6835】"
        )

    def test_limit_price_with_comma_integer(self) -> None:
        assert _normalize_raw_content("限价1,234") == "【价格类型：LimitOrder；限定价格：1234】"

    def test_at_price_comma_integer(self) -> None:
        assert _normalize_raw_content("@ 1,234") == "【价格类型：LimitOrder；限定价格：1234】"

    def test_limit_before_quantity_marks_price_missing(self) -> None:
        """「限价 1000股」：限价只表示价格类型，价格本身待补。"""
        assert _normalize_raw_content("限价 1000股") == (
            "【价格类型：LimitOrder；限定价格：未提供】 【委托数量：1000；数量单位：SHARE】"
        )

    def test_bare_comma_integer_becomes_quantity(self) -> None:
        assert _normalize_raw_content("买入 1,000") == "买入 【委托数量：1000】"

    def test_no_limit_marker_leaves_comma_integer_untouched(self) -> None:
        assert _normalize_raw_content("不限价 5,000") == "不限价 5,000"

    def test_plain_integer_without_comma_untouched(self) -> None:
        """没有单位/逗号/价格标记的裸数字不猜（可能是指数点位等）。"""
        assert _normalize_raw_content("买入5000") == "买入5000"

    def test_empty_and_none(self) -> None:
        assert _normalize_raw_content("") == ""
        assert _normalize_raw_content(None) == ""


# ============================================================
# 组合场景
# ============================================================


class TestCombined:
    def test_real_world_modify_message(self) -> None:
        """真实改参场景：引用补参 + 本次输入含限价。"""
        quote = f"单号：{O1}\n【请补充参数：限定价格】"
        out = refine_quote_hints(quote, "改成限价 6.3")
        assert out["quote_param_hints"] == f"订单 {O1} 需要补充：限定价格"
        assert out["raw_content_for_llm"] == "改成限价 6.3"

    def test_real_world_fresh_order(self) -> None:
        quote = ""
        raw = "300750.SZ，POV10，买入100股限价10"
        out = refine_quote_hints(quote, raw)
        assert out["quote_param_hints"] == ""
        assert out["raw_content_for_llm"] == (
            "300750.SZ，POV10，买入【委托数量：100；数量单位：SHARE】限价10"
        )
