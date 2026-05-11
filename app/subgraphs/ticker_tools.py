"""标的识别工具集。

对应 Dify 的 `标的智能化推断和分词工具` + `标的相关性排序工具`（共 31 节点），
在 LangGraph 中用 7 个工具函数 + ReAct Agent 重构。

核心规则（来自已有业务经验）：
1. 任何返回结果必须经 goats 库验证
2. 中文/国内标的优先 Bocha，英文/海外标的优先 Tavily
3. 候选数量 ≥ 2 时必须 LLM 排序
4. 期货合约优先"月份字母+YY"格式（如 CLN26.NYM）
"""
from __future__ import annotations

import logging
import re

import httpx
from langchain_core.tools import tool

from app.config import get_settings

logger = logging.getLogger(__name__)


# ==================================================================
# 常量：交易所枚举（来自 Dify `正则校验是否为完整标的` 节点）
# ==================================================================
EXCHANGE_SUFFIXES: set[str] = {
    "SH", "SZ", "BJ", "HK", "TW", "TWO",     # 大中华
    "T", "TSE",                                # 东京
    "KS", "KQ",                                # 韩国
    "L", "PA", "DE", "MI", "SW", "AS", "ST",  # 欧洲
    "N", "O", "NYM", "CMX", "CBT",             # 美国
    "SHF", "DCE", "CZC", "INE", "CFE",         # 国内期货
}

COMPLETE_TICKER_RE = re.compile(
    r"^[A-Z0-9]{1,8}(\.[A-Z]{1,5})?$"
)


# ==================================================================
# 工具 1：分词（字面提取，不做推断）
# ==================================================================
@tool
def tokenize_tickers(raw_text: str) -> list[str]:
    """从用户输入中提取可能的标的关键词（字面提取，零推断）。

    可识别：
    - 纯代码：600519、02513、AAPL
    - 代码+名称：600519.SH贵州茅台
    - 仅名称：贵州茅台、纳斯达克100
    - 多项分隔：600519/000858

    Args:
        raw_text: 用户输入原文

    Returns:
        关键词列表（去重去空，保持出现顺序）
    """
    # 斜杠/顿号/逗号分隔
    parts = re.split(r"[/、,，;；\s]+", raw_text)
    seen: set[str] = set()
    result: list[str] = []
    for p in parts:
        p = p.strip()
        if not p or p in seen:
            continue
        # 过滤明显不是标的的词
        if len(p) > 30 or p in {"买", "卖", "做", "下单", "询价"}:
            continue
        seen.add(p)
        result.append(p)
    return result


# ==================================================================
# 工具 2：正则判断是否为完整标的代码
# ==================================================================
@tool
def regex_validate(keyword: str) -> dict:
    """用正则判断 keyword 是否已经是完整的标的代码。

    判断依据：
    - 包含交易所后缀（.SH / .HK / .NYM 等）
    - 符合主流代码格式

    Returns:
        {"is_complete": bool, "reason": str}
    """
    keyword = keyword.strip().upper()
    if "." in keyword:
        _, suffix = keyword.rsplit(".", 1)
        if suffix in EXCHANGE_SUFFIXES:
            return {"is_complete": True, "reason": f"交易所后缀 .{suffix} 已识别"}

    # 没后缀但可能是期货合约（如 CLN26 本身就是完整的）
    if re.match(r"^[A-Z]{1,3}[FGHJKMNQUVXZ]\d{2}$", keyword):
        return {"is_complete": False,
                "reason": "期货合约缺少交易所后缀，需补全"}

    return {"is_complete": False, "reason": "缺少交易所或代码格式不完整"}


# ==================================================================
# 工具 3：标的池 MySQL 直查（标的验证唯一终点）
#
# 备选方案（HTTP API，已注释保留）：
#     原来走 http://172.16.8.28:8807/admin-api/integration/securities-instrument/select
#     POST body: {"keywordItems": [{"isFull": false, "keyword": "贵州茅台"}]}
#     返回: {"code": 0, "data": [{windCode, insShtDesc, ...}]}
#     需要 Authorization: Bearer {securities_instrument_key}
# ==================================================================
_EXCHANGE_CURRENCY: dict[str, str] = {
    "SH": "CNY", "SZ": "CNY", "BJ": "CNY",
    "HK": "HKD",
    "N": "USD", "O": "USD", "NYM": "USD", "CMX": "USD", "CBT": "USD",
    "T": "JPY", "TSE": "JPY",
}
_EXCHANGE_FAMILY: dict[str, str] = {
    "SH": "EQUITY", "SZ": "EQUITY", "BJ": "EQUITY",
    "HK": "EQUITY", "N": "EQUITY", "O": "EQUITY",
    "NYM": "FUTURE", "CMX": "FUTURE", "CBT": "FUTURE",
    "SHF": "FUTURE", "DCE": "FUTURE", "CZC": "FUTURE",
    "INE": "FUTURE", "CFE": "FUTURE",
}


def _mysql_row_to_ticker(d: dict) -> dict:
    exchange = (d.get("exchange_abbreviation") or "").strip().upper()
    return {
        "windCode": (d.get("bond_code") or "").strip(),
        "insShtDesc": d.get("stock_name") or "",
        "insLngDesc": d.get("corporate_name") or "",
        "insFamily": _EXCHANGE_FAMILY.get(exchange, "EQUITY"),
        "currency": _EXCHANGE_CURRENCY.get(exchange, "CNY"),
        "exchange": exchange,
        "from_goats": True,
    }


@tool
async def search_securities_instrument(
    keyword_items: list[dict],
) -> list[dict]:
    """标的查询——通过 HTTP API 校验标的。返回的标的均标记 from_goats=True。"""
    import httpx

    keyword_items = [i for i in keyword_items if i.get("keyword")]
    if not keyword_items:
        return []

    settings = get_settings()
    try:
        async with httpx.AsyncClient(
            base_url=settings.otc_api_base_url, timeout=httpx.Timeout(10.0)
        ) as client:
            r = await client.post(
                "/admin-api/integration/securities-instrument/select",
                json={"keywordItems": keyword_items},
            )
            r.raise_for_status()
            data = r.json().get("data", [])
            for d in data:
                d["from_goats"] = True
            return data
    except Exception as e:
        logger.error("标的查询失败: %s", e)
        return []

# 工具 4：Bocha 搜索（中文/国内标的）
# ==================================================================
@tool
async def web_search_bocha(keyword: str) -> str:
    """用 Bocha 搜索引擎查找中文/国内标的信息。

    场景：用户输入的中文名不在 goats 库中，需要先搜到标准代码再回查。

    Returns:
        搜索结果摘要文本
    """
    settings = get_settings()
    if not settings.bocha_api_key:
        return "Bocha 未配置"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                "https://api.bochaai.com/v1/web-search",
                json={
                    "query": f"{keyword} 股票代码 交易所",
                    "count": 5,
                },
                headers={"Authorization": f"Bearer {settings.bocha_api_key}"},
            )
            r.raise_for_status()
            data = r.json()
            pages = data.get("data", {}).get("webPages", {}).get("value", [])
            snippets = [p.get("snippet", "") for p in pages[:3]]
            return "\n".join(snippets)
    except Exception as e:
        return f"搜索失败: {e}"


# ==================================================================
# 工具 5：Tavily 搜索（英文/海外标的）
# ==================================================================
@tool
async def web_search_tavily(keyword: str) -> str:
    """用 Tavily 搜索引擎查找英文/海外标的信息。"""
    settings = get_settings()
    if not settings.tavily_api_key:
        return "Tavily 未配置"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.tavily_api_key,
                    "query": f"{keyword} ticker symbol exchange",
                    "max_results": 5,
                    "search_depth": "basic",
                },
            )
            r.raise_for_status()
            data = r.json()
            results = data.get("results", [])
            snippets = [r.get("content", "") for r in results[:3]]
            return "\n".join(snippets)
    except Exception as e:
        return f"搜索失败: {e}"


# ==================================================================
# 工具 6：LLM 相关性排序（候选 ≥ 2 时必用）
# ==================================================================
@tool
async def llm_rank_candidates(keyword: str, candidates: list[dict]) -> list[dict]:
    """用 LLM 对 goats 的多个候选按相关性排序并过滤。

    对应 Dify 的 `标的相关性排序工具`。

    规则：
    - 候选数 ≤ 1 直接返回
    - 期货合约优先"月份字母+YY"格式（如 CLN26.NYM）过滤 "YYMM" 格式
    """
    if len(candidates) <= 1:
        return candidates

    from app.llm.clients import get_qwen_standard

    llm = get_qwen_standard()

    system_prompt = """你是金融标的相关性排序助手。根据用户关键字对候选列表排序并过滤。
规则：
1. 严格语义匹配优先于字面子串匹配
2. 期货合约优先"月份字母+YY"格式（如 CLN26.NYM），过滤对应的"YYMM"格式
3. 仅保留 top 5 结果
仅输出 JSON：{"ranked": [完整对象数组]}"""

    user_prompt = f"关键字：{keyword}\n\n候选列表：{candidates}"

    try:
        resp = await llm.ainvoke([
            ("system", system_prompt),
            ("user", user_prompt),
        ])
        import json
        content = resp.content
        if isinstance(content, str):
            # 剥离可能的 markdown 包裹
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
            data = json.loads(content)
            return data.get("ranked") or candidates
    except Exception as e:
        logger.warning("llm_rank 失败，返回原始候选: %s", e)
    return candidates


# ==================================================================
# 工具 7：验证最终输出全部来自 goats
# ==================================================================
@tool
def assert_from_goats(tickers: list[dict]) -> dict:
    """终端断言：确保所有返回的 ticker 都带有 from_goats=True 标记。

    这是最后一道防线，Agent 在结束前必须调用。
    """
    # 检查是否有 API 调用失败的 marker
    api_errors = [t.get("_error") for t in tickers if t.get("_error")]
    if api_errors:
        return {
            "valid": False,
            "error": f"search_securities_instrument 调用失败: {api_errors}",
            "message": "API 不可用，不要编造标的。请告知用户当前无法查询标的。",
        }

    violations = [t for t in tickers if not t.get("from_goats")]
    if violations:
        return {
            "valid": False,
            "error": f"发现 {len(violations)} 个未经验证的标的",
            "message": "请重新调用 search_securities_instrument 验证所有候选",
        }
    return {"valid": True, "count": len(tickers)}
