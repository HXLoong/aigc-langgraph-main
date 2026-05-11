"""ticker 白名单 · 50 个常用标的的关键词 → wind 代码映射。

骨架阶段（M2 Day 5）resolver 用白名单实现"双轨 ticker"中的 mock 轨。
后续 PR 接真 ReAct Agent + GOATS 库后，白名单作为：
- harness `--mock-ticker` 开关时的 mock 应答（grill-with-docs 第 3 决策）
- 高频俗称的本地缓存（ADR 0008 后续优化项）

数据格式：
    keyword (用户原话片段) → (windCode, insShtDesc)

所有白名单条目视为"经 GOATS 校验过"——`from_goats=True` 写死。
"""
from __future__ import annotations

from typing import Final

#: 关键词 → (windCode, 简称)。覆盖 golden 中提到的标的 + 常见标的。
TICKER_WHITELIST: Final[dict[str, tuple[str, str]]] = {
    # ---- 港股 ----
    "腾讯": ("00700.HK", "腾讯控股"),
    "腾讯控股": ("00700.HK", "腾讯控股"),
    "阿里": ("09988.HK", "阿里巴巴-W"),
    "阿里巴巴": ("09988.HK", "阿里巴巴-W"),
    "美团": ("03690.HK", "美团-W"),
    "京东": ("09618.HK", "京东集团-SW"),
    "小米": ("01810.HK", "小米集团-W"),
    "汇丰": ("00005.HK", "汇丰控股"),
    "中国移动": ("00941.HK", "中国移动"),
    # ---- A 股 ----
    "贵州茅台": ("600519.SH", "贵州茅台"),
    "茅台": ("600519.SH", "贵州茅台"),
    "招商银行": ("600036.SH", "招商银行"),
    "招行": ("600036.SH", "招商银行"),
    "五粮液": ("000858.SZ", "五粮液"),
    "比亚迪": ("002594.SZ", "比亚迪"),
    "宁德时代": ("300750.SZ", "宁德时代"),
    "中国平安": ("601318.SH", "中国平安"),
    "工商银行": ("601398.SH", "工商银行"),
    "建设银行": ("601939.SH", "建设银行"),
    "海康威视": ("002415.SZ", "海康威视"),
    "美的集团": ("000333.SZ", "美的集团"),
    # ---- ETF ----
    "50ETF": ("510050.SH", "上证50ETF"),
    "300ETF": ("510300.SH", "沪深300ETF"),
    "500ETF": ("510500.SH", "中证500ETF"),
    "创业板ETF": ("159915.SZ", "创业板ETF"),
    "科创板ETF": ("588000.SH", "科创板50ETF"),
    # ---- 指数 ----
    "上证50": ("000016.SH", "上证50"),
    "沪深300": ("000300.SH", "沪深300"),
    "中证500": ("000905.SH", "中证500"),
    "中证1000": ("000852.SH", "中证1000"),
    "创业板指": ("399006.SZ", "创业板指"),
    "科创50": ("000688.SH", "科创50"),
    "上证指数": ("000001.SH", "上证指数"),
    # ---- 美股 / 海外指数 ----
    "纳指": ("NDX.GI", "纳斯达克100指数"),
    "纳斯达克": ("NDX.GI", "纳斯达克100指数"),
    "标普500": ("SPX.GI", "标准普尔500指数"),
    "道琼斯": ("DJI.GI", "道琼斯工业指数"),
    "苹果": ("AAPL.O", "苹果"),
    "特斯拉": ("TSLA.O", "特斯拉"),
    "英伟达": ("NVDA.O", "英伟达"),
    "微软": ("MSFT.O", "微软"),
    # ---- 商品 / 期货俗称 ----
    "伦铜": ("CA.LME", "LME 铜"),
    "伦铝": ("AH.LME", "LME 铝"),
    "布油": ("BRENT.IPE", "布伦特原油"),
    "美油": ("WTI.NYM", "WTI 原油"),
    "黄金": ("GC.CMX", "COMEX 黄金"),
    "沪金": ("AU.SHF", "上海黄金"),
    "沪银": ("AG.SHF", "上海白银"),
    "沪铜": ("CU.SHF", "上海铜"),
    # ---- 港股指数 / 其他 ----
    "恒指": ("HSI.HI", "恒生指数"),
    "恒生指数": ("HSI.HI", "恒生指数"),
    "国债期货": ("T.CFE", "10年国债期货"),
    "000001.SH": ("000001.SH", "上证指数"),  # auto: code→code
    "000016.SH": ("000016.SH", "上证50"),  # auto: code→code
    "00005.HK": ("00005.HK", "汇丰控股"),  # auto: code→code
    "000300.SH": ("000300.SH", "沪深300"),  # auto: code→code
    "000333.SZ": ("000333.SZ", "美的集团"),  # auto: code→code
    "0005.HK": ("00005.HK", "汇丰控股"),  # auto: 4-digit HK normalize
    "000688.SH": ("000688.SH", "科创50"),  # auto: code→code
    "000852.SH": ("000852.SH", "中证1000"),  # auto: code→code
    "000858.SZ": ("000858.SZ", "五粮液"),  # auto: code→code
    "000905.SH": ("000905.SH", "中证500"),  # auto: code→code
    "002415.SZ": ("002415.SZ", "海康威视"),  # auto: code→code
    "002594.SZ": ("002594.SZ", "比亚迪"),  # auto: code→code
    "00700.HK": ("00700.HK", "腾讯控股"),  # auto: code→code
    "00941.HK": ("00941.HK", "中国移动"),  # auto: code→code
    "01810.HK": ("01810.HK", "小米集团-W"),  # auto: code→code
    "03690.HK": ("03690.HK", "美团-W"),  # auto: code→code
    "0700.HK": ("00700.HK", "腾讯控股"),  # auto: 4-digit HK normalize
    "0941.HK": ("00941.HK", "中国移动"),  # auto: 4-digit HK normalize
    "09618.HK": ("09618.HK", "京东集团-SW"),  # auto: code→code
    "09988.HK": ("09988.HK", "阿里巴巴-W"),  # auto: code→code
    "159915.SZ": ("159915.SZ", "创业板ETF"),  # auto: code→code
    "1810.HK": ("01810.HK", "小米集团-W"),  # auto: 4-digit HK normalize
    "300750.SZ": ("300750.SZ", "宁德时代"),  # auto: code→code
    "3690.HK": ("03690.HK", "美团-W"),  # auto: 4-digit HK normalize
    "399006.SZ": ("399006.SZ", "创业板指"),  # auto: code→code
    "510050.SH": ("510050.SH", "上证50ETF"),  # auto: code→code
    "510300.SH": ("510300.SH", "沪深300ETF"),  # auto: code→code
    "510500.SH": ("510500.SH", "中证500ETF"),  # auto: code→code
    "588000.SH": ("588000.SH", "科创板50ETF"),  # auto: code→code
    "600036.SH": ("600036.SH", "招商银行"),  # auto: code→code
    "600519.SH": ("600519.SH", "贵州茅台"),  # auto: code→code
    "601318.SH": ("601318.SH", "中国平安"),  # auto: code→code
    "601398.SH": ("601398.SH", "工商银行"),  # auto: code→code
    "601939.SH": ("601939.SH", "建设银行"),  # auto: code→code
    "9618.HK": ("09618.HK", "京东集团-SW"),  # auto: 4-digit HK normalize
    "9988.HK": ("09988.HK", "阿里巴巴-W"),  # auto: 4-digit HK normalize
    "AAPL.O": ("AAPL.O", "苹果"),  # auto: code→code
    "AG.SHF": ("AG.SHF", "上海白银"),  # auto: code→code
    "AH.LME": ("AH.LME", "LME 铝"),  # auto: code→code
    "AU.SHF": ("AU.SHF", "上海黄金"),  # auto: code→code
    "BRENT.IPE": ("BRENT.IPE", "布伦特原油"),  # auto: code→code
    "CA.LME": ("CA.LME", "LME 铜"),  # auto: code→code
    "CU.SHF": ("CU.SHF", "上海铜"),  # auto: code→code
    "DJI.GI": ("DJI.GI", "道琼斯工业指数"),  # auto: code→code
    "GC.CMX": ("GC.CMX", "COMEX 黄金"),  # auto: code→code
    "HSI.HI": ("HSI.HI", "恒生指数"),  # auto: code→code
    "MSFT.O": ("MSFT.O", "微软"),  # auto: code→code
    "NDX.GI": ("NDX.GI", "纳斯达克100指数"),  # auto: code→code
    "NVDA.O": ("NVDA.O", "英伟达"),  # auto: code→code
    "SPX.GI": ("SPX.GI", "标准普尔500指数"),  # auto: code→code
    "T.CFE": ("T.CFE", "10年国债期货"),  # auto: code→code
    "TSLA.O": ("TSLA.O", "特斯拉"),  # auto: code→code
    "WTI.NYM": ("WTI.NYM", "WTI 原油"),  # auto: code→code
}


__all__ = ["TICKER_WHITELIST"]
