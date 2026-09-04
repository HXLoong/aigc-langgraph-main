"""intent_route 关键词配置回归测试。

Round 12 trace 暴露："跟量" 在 option_close 关键词列表里，导致 swap 单
"标的:1357.HK 买入 跟量比例20%" 被错误路由到 option_close → unknown_intent → 空回复。

修复：从 option_close.keywords 移除"跟量"。option_close 真正需要的"跟量"上下文
一定有"序号"/"平"/"留"等更确定的关键词同时出现，仍由前面规则覆盖。

回归保护：
1. swap 单含"跟量"但无"序号/平"等关键词 → 路由 swap
2. option_close 单含"序号"+"跟量" → 路由 option_close（"序号"先命中）
3. option_close 单含"留X万"+"跟量" → 路由 option_close（"留X万" regex 先命中）
"""
from __future__ import annotations

from app.nodes.intent_route import _match_keywords


class TestIntentRouteKeywords:
    """keyword 路由器准确性。"""

    def test_swap_with_genliang_routes_swap(self) -> None:
        """swap 单含"跟量比例" → 不应误路由到 option_close。"""
        text = "标的：深港通1357.HK，买入 数量2000，限价5，跟量比例20%，交易对手：A"
        result = _match_keywords(text)
        # 期待：swap 或 None（让 LLM 兜底分类）。绝对不应是 option_close。
        assert result != "option_close", (
            f"swap 单含跟量不应路由到 option_close，实际: {result}"
        )

    def test_option_close_with_xuhao_still_routes(self) -> None:
        """option_close 单含"序号"+跟量 → 仍正确路由（序号关键词先命中）。"""
        text = "序号1 平300万 拉满跟量"
        result = _match_keywords(text)
        assert result == "option_close"

    def test_option_close_with_liu_still_routes(self) -> None:
        """option_close 单含"留X万"+跟量 → regex 命中 option_close。"""
        text = "留300万 拉满跟量"
        result = _match_keywords(text)
        assert result == "option_close"
