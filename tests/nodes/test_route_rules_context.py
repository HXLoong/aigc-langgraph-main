"""#167 P0-1/P0-2：规则层引用语境测试（真实卡片文案 fixture，非 quote_desc 占位符）。

修复对象：口语化平仓(step2)/互换下单特征(step4)在关键词计数层之前截胡、
不消费 quote 的期权语境——引用期权卡后的跟进指令被错分互换（golden 45 条实锤）。
"""
from __future__ import annotations

from app.nodes.route_rules import classify_trade_type

# ---- 真实卡片文案 fixture（P0-2：替代 golden quote_desc 占位符的评估口径）----

INQUIRY_CARD = (
    "-----场外期权询价详情-----\n"
    "标的代码: 300033.SZ\n期权类型: 欧式看涨\n期限: 3M\n执行价格: 100%\n"
    "期权费率: 6.9%\n名义本金: 待补充\n建仓指令: 待补充\n交易对手: 待补充\n\n"
    "如需下单，请引用本消息补充【交易对手】【名义本金】【建仓指令】。"
)

HOLDING_CARD = (
    "您的期权持仓如下：\n"
    "序号1 | 300033.SZ 同花顺 | 欧式看涨 | 名义本金 500万 | 期限 3M\n"
    "序号2 | 510050.SH 50ETF | 雪球 | 名义本金 300万 | 期限 6M\n"
    "如需平仓，请引用本消息回复序号与平仓指令。"
)

SWAP_ORDER_CARD = (
    "-----互换下单确认-----\n"
    "## 订单参数（1 笔）\n"
    "新单号: H-20260827-1234567890\n"
    "标的: 600519.SH\n方向: BUY\n数量: 10000 股\n算法: POV"
)


class TestOptionContextYields:
    """引用期权卡/明写期权时，step2/step4 必须让位给期权链。"""

    def test_holding_card_colloquial_close_routes_close(self) -> None:
        assert classify_trade_type("序号1市价全平", HOLDING_CARD) == "期权平仓-文本"

    def test_holding_card_close_half(self) -> None:
        assert classify_trade_type("序号1市价平一半", HOLDING_CARD) == "期权平仓-文本"

    def test_raw_explicit_option_close_half(self) -> None:
        # 最恶劣样本：raw 明写"期权"仍被 step2 判互换（opt_close-009）
        assert classify_trade_type("序号1 市价把这张期权平一半", None) == "期权平仓-文本"

    def test_holding_card_close_remaining_notional(self) -> None:
        # opt_close-010：平剩到 X 名本
        assert classify_trade_type("序号1市价平剩到 200 万名本", HOLDING_CARD) == "期权平仓-文本"

    def test_inquiry_card_market_buy_routes_option(self) -> None:
        # opt-089：引用询价卡后"按市价买入"被 step4 判互换
        assert classify_trade_type("本金200万，现在就按市价买入", INQUIRY_CARD) == "期权-文本"

    def test_inquiry_card_algo_followup_routes_option(self) -> None:
        # opt-136 类：无方向词跟进（step6 计数应救回，回归保护）
        assert classify_trade_type("200万 POV25 限价10", INQUIRY_CARD) == "期权-文本"


class TestSwapBehaviorPreserved:
    """无期权语境时 DSL 原语义保持不变。"""

    def test_bare_colloquial_close_still_swap(self) -> None:
        assert classify_trade_type("平掉 50%", None) == "互换-文本"

    def test_swap_order_features_still_swap(self) -> None:
        assert classify_trade_type("卖出 10000股 POV 20%", None) == "互换-文本"

    def test_swap_card_colloquial_close_still_swap(self) -> None:
        assert classify_trade_type("序号1市价全平", SWAP_ORDER_CARD) == "互换-文本"

    def test_swap_card_confirm_still_swap(self) -> None:
        assert classify_trade_type("确认下单", SWAP_ORDER_CARD) == "互换-文本"


class TestHoldingQuoteFollowup:
    """引用期权持仓卡后的序号/减仓跟进 → 期权平仓链（#167 修复第二层，57 条实锤）。"""

    def test_close_remaining(self) -> None:
        assert classify_trade_type("序号1市价平留300万", HOLDING_CARD) == "期权平仓-文本"

    def test_close_exceed_part(self) -> None:
        assert classify_trade_type("序号1市价平掉超过 200 万的部分", HOLDING_CARD) == "期权平仓-文本"

    def test_seq_with_amount_only(self) -> None:
        assert classify_trade_type("序号1，限价10，200w", HOLDING_CARD) == "期权平仓-文本"

    def test_seq_with_algo(self) -> None:
        assert classify_trade_type("序号1，100 万，拉满跟量", HOLDING_CARD) == "期权平仓-文本"

    def test_inquiry_card_not_affected(self) -> None:
        # 询价卡引用（非持仓）不受本规则影响，仍走计数 → option
        assert classify_trade_type("200万 POV25 限价10", INQUIRY_CARD) == "期权-文本"

    def test_swap_position_card_not_affected(self) -> None:
        # 互换持仓类引用（无期权特征）不受影响
        swap_holding = "您的收益互换存量持仓：\n序号1 | 600519.SH 贵州茅台 | 多头 10000股"
        assert classify_trade_type("序号1 平掉一半", swap_holding) == "互换-文本"
