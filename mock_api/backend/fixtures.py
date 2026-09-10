"""共享静态测试数据：标的词典、持仓、交易对手、订单序列。

设计原则：
- 数据**接近生产**而非一两条占位（让 LangGraph 跑时拿到真实样貌）
- 与 `tests/fixtures/golden.jsonl` 中常用的 case 对齐（如 700.HK / 600519.SH / OPT-LYAFT…）
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

HKT = timezone(timedelta(hours=8))


def now() -> str:
    return datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S")


def today() -> str:
    return datetime.now(HKT).strftime("%Y-%m-%d")


def today_compact() -> str:
    return today().replace("-", "")


# ============================================================
# 标的词典（Securities Instrument）
# 真实 RespVO 字段：windCode / insShtDesc / insLngDesc / insFamily / currency
#                   / exchange / transactionTypeLists / relevanceScore
# ============================================================

SECURITIES_DICT: list[dict[str, Any]] = [
    # === A 股 ===
    {"id": 1001, "windCode": "600519.SH", "insShtDesc": "贵州茅台", "insLngDesc": "贵州茅台股份有限公司",
     "insFamily": "EQUITY", "currency": "CNY", "exchange": "SSE", "transactionTypeLists": ["A_SHARE"]},
    {"id": 1002, "windCode": "000858.SZ", "insShtDesc": "五粮液", "insLngDesc": "宜宾五粮液股份有限公司",
     "insFamily": "EQUITY", "currency": "CNY", "exchange": "SZSE", "transactionTypeLists": ["A_SHARE"]},
    {"id": 1003, "windCode": "600036.SH", "insShtDesc": "招商银行", "insLngDesc": "招商银行股份有限公司",
     "insFamily": "EQUITY", "currency": "CNY", "exchange": "SSE", "transactionTypeLists": ["A_SHARE"]},
    {"id": 1004, "windCode": "601398.SH", "insShtDesc": "工商银行", "insLngDesc": "中国工商银行股份有限公司",
     "insFamily": "EQUITY", "currency": "CNY", "exchange": "SSE", "transactionTypeLists": ["A_SHARE"]},
    {"id": 1005, "windCode": "300750.SZ", "insShtDesc": "宁德时代", "insLngDesc": "宁德时代新能源科技股份有限公司",
     "insFamily": "EQUITY", "currency": "CNY", "exchange": "SZSE", "transactionTypeLists": ["A_SHARE"]},
    {"id": 1006, "windCode": "688472.SH", "insShtDesc": "阿特斯", "insLngDesc": "阿特斯阳光电力科技股份有限公司",
     "insFamily": "EQUITY", "currency": "CNY", "exchange": "SSE", "transactionTypeLists": ["A_SHARE"]},
    {"id": 1007, "windCode": "002597.SZ", "insShtDesc": "金禾实业", "insLngDesc": "安徽金禾实业股份有限公司",
     "insFamily": "EQUITY", "currency": "CNY", "exchange": "SZSE", "transactionTypeLists": ["A_SHARE"]},
    {"id": 1008, "windCode": "002074.SZ", "insShtDesc": "国轩高科", "insLngDesc": "国轩高科股份有限公司",
     "insFamily": "EQUITY", "currency": "CNY", "exchange": "SZSE", "transactionTypeLists": ["A_SHARE"]},
    {"id": 1009, "windCode": "002690.SZ", "insShtDesc": "美亚光电", "insLngDesc": "合肥美亚光电技术股份有限公司",
     "insFamily": "EQUITY", "currency": "CNY", "exchange": "SZSE", "transactionTypeLists": ["A_SHARE"]},
    {"id": 1010, "windCode": "603308.SH", "insShtDesc": "应流股份", "insLngDesc": "安徽应流机电股份有限公司",
     "insFamily": "EQUITY", "currency": "CNY", "exchange": "SSE", "transactionTypeLists": ["A_SHARE"]},
    {"id": 1011, "windCode": "603198.SH", "insShtDesc": "迎驾贡酒", "insLngDesc": "安徽迎驾贡酒股份有限公司",
     "insFamily": "EQUITY", "currency": "CNY", "exchange": "SSE", "transactionTypeLists": ["A_SHARE"]},
    {"id": 1012, "windCode": "300098.SZ", "insShtDesc": "高新兴", "insLngDesc": "高新兴科技集团股份有限公司",
     "insFamily": "EQUITY", "currency": "CNY", "exchange": "SZSE", "transactionTypeLists": ["A_SHARE"]},
    {"id": 1013, "windCode": "000155.SZ", "insShtDesc": "川能动力", "insLngDesc": "四川省新能源动力股份有限公司",
     "insFamily": "EQUITY", "currency": "CNY", "exchange": "SZSE", "transactionTypeLists": ["A_SHARE"]},
    {"id": 1014, "windCode": "002382.SZ", "insShtDesc": "蓝帆医疗", "insLngDesc": "蓝帆医疗股份有限公司",
     "insFamily": "EQUITY", "currency": "CNY", "exchange": "SZSE", "transactionTypeLists": ["A_SHARE"]},
    # === 港股 ===
    {"id": 2001, "windCode": "0700.HK", "insShtDesc": "腾讯控股", "insLngDesc": "腾讯控股有限公司",
     "insFamily": "EQUITY", "currency": "HKD", "exchange": "HKEX",
     "transactionTypeLists": ["HK_STOCK", "SH_HK_CONNECT", "SZ_HK_CONNECT"]},
    {"id": 2002, "windCode": "0941.HK", "insShtDesc": "中国移动", "insLngDesc": "中国移动有限公司",
     "insFamily": "EQUITY", "currency": "HKD", "exchange": "HKEX",
     "transactionTypeLists": ["HK_STOCK", "SH_HK_CONNECT"]},
    {"id": 2003, "windCode": "0200.HK", "insShtDesc": "新濠国际发展", "insLngDesc": "新濠国际发展有限公司",
     "insFamily": "EQUITY", "currency": "HKD", "exchange": "HKEX",
     "transactionTypeLists": ["HK_STOCK"]},
    {"id": 2004, "windCode": "9988.HK", "insShtDesc": "阿里巴巴-W", "insLngDesc": "阿里巴巴集团控股有限公司",
     "insFamily": "EQUITY", "currency": "HKD", "exchange": "HKEX",
     "transactionTypeLists": ["HK_STOCK", "SH_HK_CONNECT", "SZ_HK_CONNECT"]},
    {"id": 2005, "windCode": "1357.HK", "insShtDesc": "美图公司", "insLngDesc": "美图公司",
     "insFamily": "EQUITY", "currency": "HKD", "exchange": "HKEX",
     "transactionTypeLists": ["HK_STOCK", "SZ_HK_CONNECT"]},
    {"id": 2006, "windCode": "0590.HK", "insShtDesc": "六福集团", "insLngDesc": "六福集团（国际）有限公司",
     "insFamily": "EQUITY", "currency": "HKD", "exchange": "HKEX",
     "transactionTypeLists": ["HK_STOCK", "SH_HK_CONNECT"]},
    {"id": 2007, "windCode": "02513.HK", "insShtDesc": "智谱", "insLngDesc": "智谱华章科技股份有限公司",
     "insFamily": "EQUITY", "currency": "HKD", "exchange": "HKEX",
     "transactionTypeLists": ["HK_STOCK"]},
    # === 美股 ===
    {"id": 3001, "windCode": "AAPL.O", "insShtDesc": "苹果", "insLngDesc": "Apple Inc.",
     "insFamily": "EQUITY", "currency": "USD", "exchange": "NAS",
     "transactionTypeLists": ["US_STOCK"]},
    {"id": 3002, "windCode": "TSLA.O", "insShtDesc": "特斯拉", "insLngDesc": "Tesla, Inc.",
     "insFamily": "EQUITY", "currency": "USD", "exchange": "NAS",
     "transactionTypeLists": ["US_STOCK"]},
    {"id": 3003, "windCode": "NVDA.O", "insShtDesc": "英伟达", "insLngDesc": "NVIDIA Corporation",
     "insFamily": "EQUITY", "currency": "USD", "exchange": "NAS",
     "transactionTypeLists": ["US_STOCK"]},
    {"id": 3004, "windCode": "TME.N", "insShtDesc": "腾讯音乐", "insLngDesc": "Tencent Music Entertainment Group",
     "insFamily": "EQUITY", "currency": "USD", "exchange": "NYS",
     "transactionTypeLists": ["US_STOCK"]},
    # === 期货 ===
    {"id": 4001, "windCode": "CLN26.NYM", "insShtDesc": "WTI原油2607",
     "insLngDesc": "Light Sweet Crude Oil July 2026",
     "insFamily": "FUTURE", "currency": "USD", "exchange": "NYM",
     "transactionTypeLists": ["CROSS_FUTURE"]},
    {"id": 4002, "windCode": "IF2607.CFE", "insShtDesc": "沪深300股指期货2607",
     "insLngDesc": "CSI 300 Index Futures July 2026",
     "insFamily": "FUTURE", "currency": "CNY", "exchange": "CFE",
     "transactionTypeLists": ["CHN_FUTURE"]},
]


# ============================================================
# 持仓数据（CloseOrderInfoRespVO 字段：orderId / availableNotional / notional / contractCode）
# 同时含 underlyingCode / underlyingName / optionType 等扩展字段供文本渲染
# ============================================================

POSITIONS: list[dict[str, Any]] = [
    {"orderId": "CO-20260506-85AB8526", "contractCode": "OPT-LYAFT20260001",
     "notional": 10_000_000, "availableNotional": 10_000_000,
     "underlyingCode": "000155.SZ", "underlyingName": "川能动力",
     "optionType": "欧式看涨", "createTime": "2026-05-06 15:18"},
    {"orderId": "CO-20260506-E74E24BF", "contractCode": "OPT-SZZSCF20260001",
     "notional": 10_000_000, "availableNotional": 10_000_000,
     "underlyingCode": "000155.SZ", "underlyingName": "川能动力",
     "optionType": "欧式看涨", "createTime": "2026-05-06 15:49"},
    {"orderId": "CO-20260506-7C8DEF06", "contractCode": "OPT-SZZSCF20260004",
     "notional": 10_000_000, "availableNotional": 10_000_000,
     "underlyingCode": "002382.SZ", "underlyingName": "蓝帆医疗",
     "optionType": "雪球", "createTime": "2026-05-06 15:05"},
    {"orderId": "CO-20260506-DEAF117C", "contractCode": "OPT-LYAFT20260002",
     "notional": 5_000_000, "availableNotional": 3_000_000,
     "underlyingCode": "000155.SZ", "underlyingName": "川能动力",
     "optionType": "欧式看涨", "createTime": "2026-05-06 15:21"},
]


# ============================================================
# 交易对手（CounterpartyVO 字段：ctptyId / shortName / longName / groupFlag / transactionTypeList）
# ============================================================

COUNTERPARTIES: list[dict[str, Any]] = [
    {"ctptyId": 10049, "shortName": "临沂阿凡提", "longName": "上海猎鲸志投资管理有限公司",
     "groupFlag": "N",
     "transactionTypeList": ["A_SHARE", "HK_STOCK", "US_STOCK", "SZ_HK_CONNECT",
                             "SH_HK_CONNECT", "CROSS_FUTURE"]},
    {"ctptyId": 10833, "shortName": "10833测试短名", "longName": "10833测试产品",
     "groupFlag": "N",
     "transactionTypeList": ["A_SHARE", "HK_STOCK", "US_STOCK"]},
    {"ctptyId": 11125, "shortName": "11125测试短名（张天琪专用）", "longName": "吕测试企业-Ukey",
     "groupFlag": "N",
     "transactionTypeList": ["A_SHARE", "HK_STOCK", "US_STOCK", "SZ_HK_CONNECT",
                             "SH_HK_CONNECT", "CROSS_FUTURE"]},
]


# ============================================================
# 推断 prompt（CounterpartyInfoController.getInstrumentInferencePrompt）
# 真实后端走 `configApi.getConfigValueByKey("swap_instrument_inference_prompt")`
# ============================================================

INSTRUMENT_INFERENCE_PROMPT = (
    "你是一个标的代码推断助手。\n"
    "根据用户输入的标的简称或别名，结合候选列表，推断最匹配的 windCode。\n"
    "若不能确定，返回 unknown。\n"
    "注意港股代码补零（如 700 → 0700.HK）。\n"
)


# ============================================================
# 全局自增订单序列（按 type 区分前缀）
# ============================================================


class _OrderSeq:
    def __init__(self) -> None:
        self._counters: dict[str, int] = {}

    def next(self, prefix: str) -> str:
        n = self._counters.get(prefix, 0) + 1
        self._counters[prefix] = n
        return f"{prefix}-{today_compact()}-{n:08d}"


order_seq = _OrderSeq()
