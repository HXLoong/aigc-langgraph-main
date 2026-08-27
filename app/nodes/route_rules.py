"""一级路由规则层(DSL v2「脚本判断期权、互换、其他查询指令」1:1 移植)。

对照源:dify/yaml/主干工作流.yml node 1755072896717(2026-08 版)。
返回标签与 DSL 一致:互换-文本 / 期权-文本 / 期权平仓-文本 / 互换-图片 / 互换-Excel /
无法识别文件类型 / unknown。product_type 映射由 intent_route 节点完成。

移植纪律:判定顺序、正则、关键词表与源节点保持一致;仅做工程化改造
(print → logging、类型提示、常量命名)。改业务逻辑必须先改 Dify 源再同步。
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------
# 订单号正则(优先级:互换 H- > 期权开仓 Q- > 期权平仓 CO-/OPT)
# ---------------------------------------------------------------
OPTION_CLOSE_ORDER_PATTERN = r"CO-\d{8}-[0-9A-F]{8}|OPTG?-[A-Z]{4,8}\d{6,10}"
SWAP_ORDER_PATTERN = r"H-\d{8}-\d{10}"
OPTION_OPEN_ORDER_PATTERN = r"Q-\d{8}-\d{10}"

# 口语化平仓表达(无平仓单号时 → 互换头寸口语化减仓)
COLLOQUIAL_SWAP_CLOSE_PATTERNS: list[str] = [
    r"平\s*\d+(?:\.\d+)?\s*%",
    r"平掉\s*\d+(?:\.\d+)?\s*%",
    r"以\s*\d+(?:\.\d+)?\s*%\s*平",
    r"平[一二三四五六七八九十1-9]\s*成",
    r"平一半",
    r"半仓",
    r"平[一二三四五六七八九十1-9]+\s*分之\s*[一二三四五六七八九十1-9]+",
    r"平\s*\d+\s*/\s*\d+",
    r"全平",
    r"全部平仓",
    r"全部平了",
    r"平\s*\d+",
    r"平仓\s*\d+",
]

OPTION_CLOSE_QUERY_KEYWORDS: list[str] = [
    "我想平仓", "我要平仓", "帮我平仓", "想平仓", "要平仓",
    "我有哪些持仓", "查询持仓", "查看持仓", "持仓情况", "我的持仓",
    "期权持仓", "查持仓", "期权平仓", "持仓",
]

OPTION_KEYWORDS: list[str] = [
    "期权", "期权订单",
    "报价", "询价",
    "看涨", "看跌",
    "行权价", "平直", "平值",
    "call", "CALL", "Call",
    "put", "PUT", "Put",
    "欧式看涨", "雪球", "参与型看涨", "敲入", "敲出",
    "Q-",
    "涨跌幅过大", "结构", "期限", "保证金", "最大亏损", "名本", "名义本金", "个月", "月", "M", "m",
]

SWAP_KEYWORDS: list[str] = [
    "互换", "收益互换", "互换订单", "互换请求下单",
    "交易品种", "A股", "港股", "美股", "深港通", "沪港通", "境内期货", "跨境期货", "期货",
    "交易方向", "开仓", "平仓", "空", "买入", "卖出", "卖空", "平空", "买", "卖", "手",
    "H-",
    "POV", "TWAP", "VWAP", "ICEBERG", "SNIPER",
]

_SWAP_SYSTEM_MSG_KEYWORDS = ("互换请求", "互换详情", "收益互换", "场外收益互换")

EXCEL_EXTENSIONS = {".xls", ".xlsx"}
EXCEL_MIME_TYPES = {
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

_UUID_PATTERN = (
    r"\([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\)"
)


def _clean_text(text: str) -> str:
    """删除文本中括号包裹的 UUID(用户提及信息),折叠空白。"""
    if not text:
        return text
    cleaned = re.sub(_UUID_PATTERN, "", text, flags=re.MULTILINE | re.DOTALL)
    return re.sub(r"\s+", " ", cleaned).strip()


def _has_colloquial_swap_close(text: str) -> bool:
    if not text:
        return False
    return any(re.search(p, text) for p in COLLOQUIAL_SWAP_CLOSE_PATTERNS)


def _is_quote_content_valid(quote_content: str | None) -> bool:
    """排除 None / 空白 / Java String.valueOf(null) 产生的 "null"。"""
    if not quote_content or not isinstance(quote_content, str):
        return False
    stripped = quote_content.strip()
    return bool(stripped) and stripped.lower() != "null"


def is_swap_transaction(
    instruction: str,
    files: list[dict] | None = None,
    quote_content: str | None = None,
) -> str:
    """文件优先分类:全图片 → 互换-图片;全 Excel → 互换-Excel;混合 → 无法识别文件类型。

    无文件时走文本分类。
    """
    if files and isinstance(files, list) and len(files) > 0:
        if all(str(f.get("type", "")).lower() == "image" for f in files):
            return "互换-图片"
        all_excels = all(
            (str(f.get("extension", "")).lower() in EXCEL_EXTENSIONS)
            or (str(f.get("mime_type", "")).lower() in EXCEL_MIME_TYPES)
            for f in files
        )
        if all_excels:
            return "互换-Excel"
        return "无法识别文件类型"
    return classify_trade_type(instruction, quote_content)


def classify_trade_type(text: str, quote_content: str | None = None) -> str:
    """无文件时的文本分类。判定顺序与 DSL 源节点一致。"""
    # 1) 订单号正则(query + 有效 quote_content 合并扫描)
    order_search_text = text or ""
    if _is_quote_content_valid(quote_content):
        order_search_text = order_search_text + " " + (quote_content or "")

    if re.search(SWAP_ORDER_PATTERN, order_search_text):
        return "互换-文本"
    if re.search(OPTION_OPEN_ORDER_PATTERN, order_search_text):
        return "期权-文本"
    if re.search(OPTION_CLOSE_ORDER_PATTERN, order_search_text):
        return "期权平仓-文本"

    # 2) 口语化平仓 → 互换-文本(早于平仓查询关键词,防"全平"被干扰)
    if text and _has_colloquial_swap_close(text):
        return "互换-文本"

    # 3) 互换系统回复引用 → 互换-文本(防候选标的列表污染关键词计数)
    if _is_quote_content_valid(quote_content) and any(
        k in (quote_content or "") for k in _SWAP_SYSTEM_MSG_KEYWORDS
    ):
        return "互换-文本"

    # 4) 明确互换下单特征:方向 + 数量/算法/价格类型,且无明确期权特征
    has_explicit_option = False
    if text:
        upper_text = text.upper()
        has_swap_direction = any(
            k in text for k in ("买入", "卖出", "卖空", "平空", "沽出", "沽入")
        )
        has_swap_params = (
            (any(ch.isdigit() for ch in text) and any(k in text for k in ("股", "手")))
            or any(k in upper_text for k in ("POV", "TWAP", "VWAP", "ICEBERG", "SNIPER", "MKT"))
            or any(k in text for k in ("市价", "限价"))
        )
        has_explicit_option = any(
            k in text for k in ("期权", "看涨", "看跌", "雪球")
        ) or bool(re.search(r"(?<![A-Za-z])(?:CALL|PUT)(?![A-Za-z])", upper_text))
        if has_swap_direction and has_swap_params and not has_explicit_option:
            return "互换-文本"

    # 5) 期权平仓查询关键词("持仓"遇明确互换下单信号让位)
    if text:
        for keyword in OPTION_CLOSE_QUERY_KEYWORDS:
            if keyword in text:
                has_explicit_swap_order_signal = any(
                    signal in text.upper()
                    for signal in ("买入", "卖出", "卖空", "平空", "MKT", "POV", "TWAP", "VWAP", "ICEBERG", "SNIPER")
                ) or bool(
                    re.search(r"[0-9]+(?:[.][0-9]+)?[ ]*(?:万|千|亿|k|w)?[ ]*(?:股|手)", text, re.I)
                )
                if keyword == "持仓" and has_explicit_swap_order_signal and not has_explicit_option:
                    continue
                return "期权平仓-文本"

    # 6) 关键词计数
    combined_text = text if text else ""
    if quote_content and isinstance(quote_content, str) and quote_content.strip():
        combined_text = combined_text + " " + quote_content
    if not combined_text.strip():
        return "unknown"

    cleaned_text = _clean_text(combined_text)

    option_matched: list[str] = []
    option_count = 0
    for keyword in OPTION_KEYWORDS:
        if keyword in ("M", "m"):
            matches = re.findall(r"\d+" + keyword, cleaned_text)
            if matches:
                option_matched.append(keyword)
                option_count += len(matches)
        elif keyword in cleaned_text:
            option_matched.append(keyword)
            option_count += cleaned_text.count(keyword)

    swap_matched: list[str] = []
    swap_count = 0
    for keyword in SWAP_KEYWORDS:
        if keyword == "手":
            matches = re.findall(r"\d+手", cleaned_text)
            if matches:
                swap_matched.append(keyword)
                swap_count += len(matches)
        elif keyword in cleaned_text:
            swap_matched.append(keyword)
            swap_count += cleaned_text.count(keyword)

    logger.debug(
        "route_rules keyword hit option=%s(%d) swap=%s(%d)",
        option_matched, option_count, swap_matched, swap_count,
    )

    option_hit = bool(option_matched)
    swap_hit = bool(swap_matched)
    if swap_hit and not option_hit:
        return "互换-文本"
    if option_hit and not swap_hit:
        return "期权-文本"
    if swap_hit and option_hit:
        if swap_count > option_count:
            return "互换-文本"
        if option_count > swap_count:
            return "期权-文本"
        # 打平:含 数字+M/m(期权月度期限信号)优先期权,否则维持互换
        if re.search(r"\d+\s*[Mm]", cleaned_text):
            return "期权-文本"
        return "互换-文本"

    return "unknown"


__all__ = ["classify_trade_type", "is_swap_transaction"]
