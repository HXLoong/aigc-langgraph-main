"""route_rules（DSL v2「脚本判断期权、互换、其他查询指令」移植）单测。

规则真源：app/nodes/route_rules.py（DSL v2 迁移后代码即真源，ADR 0024 D1）。
标签约定与 DSL 完全一致:互换-文本 / 期权-文本 / 期权平仓-文本 / 互换-图片 / 互换-Excel /
无法识别文件类型 / unknown。
"""
from __future__ import annotations

import pytest

from app.nodes.route_rules import classify_trade_type, is_swap_transaction


class TestOrderNoPriority:
    """订单号正则:互换(H-) > 期权开仓(Q-) > 期权平仓(CO-/OPT)。"""

    def test_swap_order_no(self):
        assert classify_trade_type("撤掉 H-20260101-0000000001") == "互换-文本"

    def test_option_open_order_no(self):
        assert classify_trade_type("Q-20260101-0000000001 确认") == "期权-文本"

    def test_close_order_no(self):
        assert classify_trade_type("平仓单 CO-20260101-0A1B2C3D") == "期权平仓-文本"

    def test_close_contract_no(self):
        assert classify_trade_type("OPTG-SZZSCF20250030 全部平掉") == "期权平仓-文本"

    def test_swap_beats_option_open(self):
        text = "H-20260101-0000000001 和 Q-20260101-0000000002"
        assert classify_trade_type(text) == "互换-文本"

    def test_order_no_in_quote_content(self):
        assert classify_trade_type("确认", quote_content="订单 Q-20260101-0000000001") == "期权-文本"


class TestColloquialSwapClose:
    """口语化平仓表达 → 互换-文本(无平仓单号时)。"""

    @pytest.mark.parametrize("text", ["平30%", "平掉 30.5%", "平三成", "平一半", "半仓", "全平", "平三分之一", "平1/4", "平700", "平仓300"])
    def test_colloquial(self, text):
        assert classify_trade_type(text) == "互换-文本"

    def test_close_order_no_wins_over_colloquial(self):
        assert classify_trade_type("全平 CO-20260101-0A1B2C3D") == "期权平仓-文本"


class TestQuoteSystemMsg:
    def test_swap_system_quote(self):
        assert classify_trade_type("确认", quote_content="-----场外收益互换详情-----") == "互换-文本"

    def test_null_string_quote_ignored(self):
        assert classify_trade_type("", quote_content="null") == "unknown"


class TestSwapExplicitFeature:
    """方向+数量/算法 且无期权特征 → 互换-文本。"""

    def test_direction_plus_quantity(self):
        assert classify_trade_type("买入 贵州茅台 1000股 限价") == "互换-文本"

    def test_direction_plus_algo(self):
        assert classify_trade_type("卖出 中国平安 TWAP") == "互换-文本"

    def test_option_feature_blocks_step4(self):
        # 含期权特征时第 4 层(方向+数量)不触发,落入关键词计数;
        # DSL 语义:计数打平且无 数字+M 信号 → 维持互换(源节点 tie-break 规则)
        assert classify_trade_type("买入 看涨期权 1000股") == "互换-文本"
        # 含月期限信号则打平判期权
        assert classify_trade_type("买入 看涨期权 1000股 3M") == "期权-文本"


class TestCloseQueryKeywords:
    def test_holding_query(self):
        assert classify_trade_type("我想平仓,查询持仓") == "期权平仓-文本"

    def test_holding_with_swap_signal_skipped(self):
        # "持仓" + 明确互换下单信号(数量+股) → 不走平仓
        assert classify_trade_type("持仓 买入 10000股") == "互换-文本"


class TestKeywordCounting:
    def test_option_keywords(self):
        assert classify_trade_type("参与型看涨 腾讯 1个月") == "期权-文本"

    def test_swap_keywords(self):
        assert classify_trade_type("收益互换 A股 开仓") == "互换-文本"

    def test_tie_break_month_signal(self):
        # 打平且含 数字+M → 期权
        assert classify_trade_type("买 结构 3M") == "期权-文本"

    def test_genliang_swap_regression(self):
        # 历史回归(Round 12):"跟量"曾在旧 option_close 关键词表导致误路由;
        # DSL v2 规则层无此关键词,swap 单含"跟量"应路由互换
        assert classify_trade_type("标的:1357.HK 买入 跟量比例20%") == "互换-文本"

    def test_no_keyword_unknown(self):
        assert classify_trade_type("你好") == "unknown"

    def test_empty_unknown(self):
        assert classify_trade_type("") == "unknown"


class TestFiles:
    def test_all_images(self):
        assert is_swap_transaction("", files=[{"type": "image"}, {"type": "image"}]) == "互换-图片"

    def test_all_excel(self):
        files = [{"type": "document", "extension": ".xlsx"}]
        assert is_swap_transaction("", files=files) == "互换-Excel"

    def test_mixed_unrecognized(self):
        files = [{"type": "image"}, {"type": "document", "extension": ".pdf"}]
        assert is_swap_transaction("", files=files) == "无法识别文件类型"

    def test_no_files_falls_back_to_text(self):
        assert is_swap_transaction("收益互换 A股", files=[]) == "互换-文本"
