"""tokenize 命名指数复合名称保留测试。

Round 4 eval 暴露：tokenize 对"中证1000 100% 2M"切分为 ['1000', '中证', '100%', '2M']，
丢失了"中证1000"这个完整指数名的语义。"1000" 单独搜 GOATS 返回 1000.HK，导致后续
被当作港股标的提交后端，被拒绝。

设计：当 token 含"中文 + 4位数字"组合（命名指数典型结构，如中证1000/中证2000）时，
保留原 token 作为复合 keyword 放在数字/中文分离 keyword 之前。下游 resolver 优先用
完整 token 调 GOATS + LLM 推断 ETF 代码。

注：3 位及以下数字（沪深300/上证50/中证500）GOATS 通常返回完整名称的指数/ETF，
不需特殊处理；5-6 位数字（贵州茅台600519/02513智谱）是股票代码，应保持分离。
"""
from __future__ import annotations

from app.subgraphs.ticker.tools import tokenize


class TestCompoundIndexPreserved:
    """中文 + 4 位数字组合的 token 保留为复合 keyword。"""

    def test_zhongzheng_1000_preserved_as_compound(self) -> None:
        """中证1000 → tokenize 保留"中证1000"为一项，列在分离 keyword 之前。"""
        result = tokenize.invoke({"raw_text": "中证1000 100% 2M"})
        assert "中证1000" in result, f"应保留'中证1000'整体，实际: {result}"
        # 复合 token 优先级最高，便于 resolver 优先解析整体语义
        compound_idx = result.index("中证1000")
        if "1000" in result:
            assert compound_idx < result.index("1000"), (
                f"'中证1000'应在'1000'之前，实际: {result}"
            )

    def test_zhongzheng_2000_preserved(self) -> None:
        """中证2000 → 同上。"""
        result = tokenize.invoke({"raw_text": "中证2000 100%"})
        assert "中证2000" in result

    def test_stock_code_still_separated(self) -> None:
        """5-6 位数字股票代码 + 中文名 → 仍应分离（保持现有行为）。"""
        # 6 位 stock code
        result1 = tokenize.invoke({"raw_text": "贵州茅台600519"})
        assert "600519" in result1
        assert "贵州茅台" in result1
        assert "贵州茅台600519" not in result1, (
            f"6 位股票代码不应被复合，实际: {result1}"
        )
        # 5 位
        result2 = tokenize.invoke({"raw_text": "02513智谱"})
        assert "02513" in result2
        assert "智谱" in result2
        assert "02513智谱" not in result2

    def test_three_digit_compound_not_extracted(self) -> None:
        """3 位数字（如沪深300）整体保留（已是现有行为，回归保护）。"""
        result = tokenize.invoke({"raw_text": "沪深300 3M"})
        assert "沪深300" in result
        # 不应错误拆出 "300"
        assert "300" not in result
