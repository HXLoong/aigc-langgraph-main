"""ticker 子图的工具函数库（Dify DSL v2 迁移：标的智能化推断和分词工具，12 节点）。

新管线（对照 dify/yaml/标的智能化推断和分词工具.yml）：

    候选标的（raw_text 分词） -> 列表格式化(空->短路) -> 并行(推断/拆分/判类型) LLM
        -> 合并数据并校验完整标的（确定性）-> GOATS 查询 + 大模型排序并过滤(rank)

设计原则（ADR 0008 + grill-with-docs）：
- 确定性优先：候选拆分 / 列表格式化 / 合并校验 都是纯函数，不调 LLM
- LLM 集中在 3 个批量调用：infer_code_batch / split_ticker_keywords / judge_ticker_type
  （新 DSL 把这 3 个 LLM 节点做成"并行 fan-out"，本模块用 asyncio.gather 对齐）
- rank_candidates 是第 4 个 LLM 调用，属于独立的"标的相关性排序工具"子工作流，
  在本地管线里由 resolver.py 编排调用（GOATS 查询之后）

关键变化 vs 旧版 ReAct 架构：
- **completeness 工具已删除**：被 `merge_and_validate` 里的确定性交易所后缀正则替代
  （对齐 ticker_合并数据并校验完整标的.py 的 FULL_CODE_REGEX 校验）
- **infer_code 从"单 keyword 同步 + 线程包裹调用"改为"批量 async 调用"**：
  新 DSL 一次性把全部候选词交给 LLM（省 token、省往返延迟），不再逐词调用
- **动态 prompt HTTP 拉取（ADR 0013）已删除**：新 DSL 把 `inferencePrompt` 收编为
  外部入参，本地实现改为纯 `load_prompt()` 静态加载，不再有 5 分钟 LRU 缓存 /
  `get_inference_prompt()` 运行时拉取链路
- **无 ReAct**：不再有 Agent 自主决策调用顺序，管线在 resolver.py 里显式编排

后端依赖：
- securities-instrument/select — GOATS 候选查询（ADR 0001 D4）
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Annotated, Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from app.config import get_settings
from app.llm.clients import get_qwen_standard
from app.tools.ticker_client import TickerClientHttpx

logger = logging.getLogger(__name__)


# ============================================================
# tokenize · 候选标的提取（规则常量，保持现状不变）
# ============================================================
#
# 说明（P1 ticker 域范围裁决）：新 DSL 的"标的智能化推断和分词工具"以
# `list 候选词JSON串` 作为外部入参，候选提取本身属于主干路由的"候选标的提取[code]"
# 节点（P5 router 域，本次不在范围内）。在 P5 落地前，本模块继续复用这个已验证
# 的确定性分词器作为"候选标的提取"的本地替代实现，产出交给下游新管线
# （format_candidate_list -> 并行 LLM -> merge_and_validate）处理。

#: 多分隔符（空格 / 中英文逗号 / 分号 / 顿号 / 斜杠 / 竖线 / @ / # / 制表 / 换行）
_DELIM_RE = re.compile(r"[\s,，;；、/|@#\t\n]+")

#: 完整代码后缀（"代码 + 后缀" 命中时同时输出完整代码 + 无后缀片段，便于反查）
_CODE_SUFFIXES = (
    ".SH", ".SZ", ".HK", ".HKEX", ".SHF", ".DCE", ".CZC", ".CFE", ".INE",
    ".O", ".N", ".NYM", ".CME", ".COMEX", ".LME", ".CBOT", ".SGX",
)

#: 名称中嵌入的 4-6 位数字（如 "贵州茅台600519" → 600519）
_EMBEDDED_DIGIT_RE = re.compile(r"(\d{4,6})")

#: 业务/时间词黑名单（D2.4 真后端联调发现：tokenize 把"1个月"误识别为 ticker keyword
#: → GOATS 命中 ETF（嘉实1个月理财 等），render 输出错误 HITL 卡片）
#: Round D 续修：百分比形式（如"200%" "80%/50%10%"）被 GOATS 模糊匹配成 002001.SZ 等
#: 无关股票，opt-016 反案例链式失败 → 加百分比模式过滤
_NON_TICKER_PATTERNS = (
    re.compile(r"^\d+(?:\.\d+)?[DWMY]$", re.IGNORECASE),  # 1M / 2w / 0.5Y
    re.compile(r"^\d+\s*(个)?\s*(月|年|周|日|天)$"),  # 1个月 / 3年 / 6周 / 2天
    re.compile(r"^(行权价|执行价|敲入|敲出|期限|名义本金|本金|期权费|参与率|价格)$"),
    # 数字+百分号开头的 token 都不是标的（80% / 25.5% / 50%10% / 70/103 等）
    re.compile(r"^\d+(\.\d+)?[%/].*"),
)


def _is_non_ticker_token(token: str) -> bool:
    """业务术语 / 时间词 → 不进 GOATS 查询。仅 tokenize 阶段过滤，不影响 LLM 推断。"""
    return any(p.match(token) for p in _NON_TICKER_PATTERNS)


def _split_token_with_suffix(token: str) -> list[str]:
    """`代码.后缀` 格式 → 同时输出完整代码 + 无后缀片段。例：`0700.HK` → `[0700.HK, 0700]`"""
    upper = token.upper()
    for suf in _CODE_SUFFIXES:
        if upper.endswith(suf) and len(token) > len(suf):
            return [token, token[: -len(suf)]]
    return [token]


def _extract_embedded_codes(token: str) -> list[str]:
    """从 token 中提取嵌入的 4-6 位数字 + 剥离数字后的剩余文本。

    例：`02513智谱` → `[02513, 智谱]`
        `贵州茅台600519` → `[600519, 贵州茅台]`
        `2月WTI原油` → `[WTI原油]`（2 位数字不算代码）
        `腾讯` → `[腾讯]`
        `中证1000` → `[中证1000, 1000, 中证]`（4 位数字 + 中文余 → 大概率命名指数，保留复合）
    """
    digits = _EMBEDDED_DIGIT_RE.findall(token)
    if not digits:
        return [token]
    remainder = _EMBEDDED_DIGIT_RE.sub("", token).strip()
    # 4 位数字 + 中文余 → 命名指数复合 keyword（中证1000/中证2000），保留原 token 在最前。
    # 5-6 位数字（如 600519/02513）是股票代码，仍按"代码+名称"分离。
    has_chinese_remainder = bool(re.search(r"[一-鿿]", remainder))
    is_chinese_index_pattern = has_chinese_remainder and any(
        len(d) == 4 for d in digits
    )
    out: list[str] = []
    if is_chinese_index_pattern:
        out.append(token)
    out.extend(digits)
    if remainder and remainder not in out:
        out.append(remainder)
    return out


@tool
def tokenize(raw_text: Annotated[str, "用户原话"]) -> list[str]:
    """把用户原话拆分为标的关键词候选 list（去重保持顺序）。

    规则（ADR 0008 b：保守提取，不做证券识别）：
    1. 多分隔符切割（空格 / 逗号 / 分号 / 顿号 / 斜杠 / 竖线 / @ / #）
    2. 带后缀的代码同时输出完整代码 + 无后缀片段
    3. 4-6 位独立数字识别为代码 keyword
    4. 名称中嵌入 4-6 位数字 → 拆出数字 + 剩余文本
    5. 不调 LLM、不映射名称↔代码、不脑补完整信息

    例：
    >>> tokenize("买 02513智谱 1000 股")
    ['02513', '智谱', '1000']
    >>> tokenize("0700.HK")
    ['0700.HK', '0700']
    >>> tokenize("600519/000858")
    ['600519', '000858']
    """
    if not raw_text or not raw_text.strip():
        return []

    raw_tokens = [t for t in _DELIM_RE.split(raw_text) if t]

    out: list[str] = []
    seen: set[str] = set()
    for tok in raw_tokens:
        # D2.4 真后端联调发现：业务术语 / 时间词不进 GOATS 查询
        if _is_non_ticker_token(tok):
            continue
        with_suffix = _split_token_with_suffix(tok)
        if len(with_suffix) > 1:
            # 完整代码（含后缀）→ 不再做嵌入数字拆分
            for piece in with_suffix:
                if piece and piece not in seen and not _is_non_ticker_token(piece):
                    out.append(piece)
                    seen.add(piece)
            continue
        for piece in _extract_embedded_codes(tok):
            if piece and piece not in seen and not _is_non_ticker_token(piece):
                out.append(piece)
                seen.add(piece)
    return out


#: 订单号前缀（业务单号不是标的代码，候选列表阶段就过滤，避免浪费 LLM / GOATS 调用）
_ORDER_ID_PREFIXES = ("OPT-", "CO-", "H-", "OPTG-", "Q-")


def _filter_noise_candidates(items: list[str]) -> list[str]:
    """过滤候选列表里的噪音项：单字符 / 非 4-6 位纯数字 / 订单号前缀。"""
    out: list[str] = []
    for kw in items:
        if len(kw) <= 1:
            continue
        if kw.isdigit() and not (4 <= len(kw) <= 6):
            continue
        if any(kw.upper().startswith(p) for p in _ORDER_ID_PREFIXES):
            continue
        out.append(kw)
    return out


# ============================================================
# 列表格式化（ticker_列表格式化.py 移植）
# ============================================================


def format_candidate_list(items: list[Any] | str) -> list[str]:
    """候选词列表格式化：JSON 串 parse（若已是 list 直接用）+ 去空值 + 去重（保持顺序）。

    对齐 `ticker_列表格式化.py`：
    - `items` 是 JSON 字符串 → 尝试 parse，失败或非数组 → 返回 []
    - `items` 已是 list → 直接使用
    - 过滤 None / 空字符串
    - 去重，保留首次出现顺序（JS `new Set` 语义）
    """
    if isinstance(items, str):
        try:
            parsed: Any = json.loads(items)
        except (json.JSONDecodeError, ValueError):
            return []
    else:
        parsed = items

    if not isinstance(parsed, list):
        return []

    seen: list[str] = []
    for item in parsed:
        if item is None or item == "":
            continue
        if item not in seen:
            seen.append(item)
    return seen


# ============================================================
# 合并数据并校验完整标的（ticker_合并数据并校验完整标的.py 移植，确定性）
# ============================================================

#: 交易所枚举：(中文名, MIC 代码, Wind 后缀)
EXCHANGE_ENUM: tuple[tuple[str, str, str], ...] = (
    # 中国大陆及港澳台
    ("上海证券交易所", "SSE", "SH"),
    ("深圳证券交易所", "SZSE", "SZ"),
    ("北京证券交易所", "BSE", "BJ"),
    ("香港交易及结算所有限公司", "HKEX", "HK"),
    ("台湾证券交易所", "TWSE", "TW"),
    ("台湾证券柜台买卖中心", "TPEx", "TWO"),
    # 亚太地区
    ("东京证券交易所", "TSE", "T"),
    ("大阪交易所", "OSE", "J"),
    ("韩国交易所", "KRX", "KS"),
    ("韩国科斯达克市场", "KOSDAQ", "KQ"),
    ("新加坡交易所", "SGX", "SG"),
    ("马来西亚证券交易所", "BURSA", "KL"),
    ("泰国证券交易所", "SET", "BK"),
    ("印度尼西亚证券交易所", "IDX", "JK"),
    ("菲律宾证券交易所", "PSE", "PS"),
    ("胡志明市证券交易所", "HOSE", "VN"),
    ("澳大利亚证券交易所", "ASX", "AX"),
    ("新西兰证券交易所", "NZX", "NZ"),
    ("印度国家证券交易所", "NSE", "NS"),
    ("孟买证券交易所", "BOM", "BO"),
    ("巴基斯坦证券交易所", "PSX", "KA"),
    ("科伦坡证券交易所", "CSE", "CM"),
    # 北美洲
    ("纽约证券交易所", "NYSE", "N"),
    ("纳斯达克证券交易所", "NASDAQ", "O"),
    ("多伦多证券交易所", "TSX", "TO"),
    ("多伦多创业交易所", "TSXV", "V"),
    ("加拿大证券交易所", "XCNQ", "CN"),
    ("墨西哥证券交易所", "BMV", "MX"),
    # 欧洲
    ("伦敦证券交易所", "LSE", "L"),
    ("法兰克福证券交易所", "FSE", "F"),
    ("法兰克福XETRA电子交易系统", "XETR", "DE"),
    ("巴黎泛欧交易所", "XPAR", "PA"),
    ("阿姆斯特丹泛欧交易所", "XAMS", "AS"),
    ("布鲁塞尔泛欧交易所", "XBRU", "BR"),
    ("里斯本泛欧交易所", "XLIS", "LS"),
    ("瑞士证券交易所", "SIX", "SW"),
    ("米兰证券交易所", "XMIL", "MI"),
    ("马德里证券交易所", "BME", "MA"),
    ("斯德哥尔摩证券交易所", "XSTO", "ST"),
    ("奥斯陆证券交易所", "XOSL", "OL"),
    ("哥本哈根证券交易所", "XCSE", "CO"),
    ("赫尔辛基证券交易所", "XHEL", "HE"),
    ("冰岛证券交易所", "XICE", "IC"),
    ("华沙证券交易所", "GPW", "WA"),
    ("布拉格证券交易所", "XPRA", "PR"),
    ("布达佩斯证券交易所", "XBUD", "BD"),
    ("维也纳证券交易所", "XWBO", "VI"),
    ("雅典证券交易所", "ATHEX", "AT"),
    ("伊斯坦布尔证券交易所", "BIST", "IS"),
    ("爱尔兰证券交易所", "XDUB", "IR"),
    ("莫斯科交易所", "MOEX", "MC"),
    ("塔林证券交易所", "XTAL", "TL"),
    ("里加证券交易所", "XRIS", "RG"),
    ("维尔纽斯证券交易所", "XLIT", "VS"),
    ("柏林证券交易所", "XBER", "BE"),
    ("杜塞尔多夫证券交易所", "XDUS", "DU"),
    ("慕尼黑证券交易所", "XMUN", "MU"),
    ("汉堡证券交易所", "XHAM", "HM"),
    ("汉诺威证券交易所", "XHAN", "HA"),
    # 中东地区
    ("沙特证券交易所", "TADAWUL", "SR"),
    ("阿联酋证券交易所", "DFM", "AE"),
    ("卡塔尔证券交易所", "QSE", "QA"),
    ("科威特证券交易所", "XKUW", "KW"),
    ("特拉维夫证券交易所", "TASE", "TA"),
    ("巴林证券交易所", "XBAH", "BH"),
    ("安曼证券交易所", "XAMM", "AM"),
    # 非洲
    ("约翰内斯堡证券交易所", "JSE", "JO"),
    ("埃及证券交易所", "EGX", "CA"),
    ("内罗毕证券交易所", "XNAI", "NR"),
    ("卡萨布兰卡证券交易所", "XCAS", "CS"),
    ("尼日利亚证券交易所", "NGX", "LG"),
    # 南美洲
    ("巴西证券交易所", "B3", "SA"),
    ("布宜诺斯艾利斯证券交易所", "BYMA", "BA"),
    ("圣地亚哥证券交易所", "XSGO", "SN"),
    ("利马证券交易所", "BVL", "LM"),
)

#: 纯市场/板块导航词：作为搜索关键词对标的 DB 查询无帮助、只引噪声，丢弃
#: （市场意图由业务层的 placeOrderTransactionType 承载）
MARKET_WORDS: frozenset[str] = frozenset(
    {
        "A股", "沪市", "深市", "沪股", "深股", "北交所", "新三板",
        "科创板", "创业板", "主板", "港股", "美股", "日股", "英股",
    }
)

#: 按后缀长度降序排列，避免正则短串优先匹配（如 TW 先于 TWO）
_SUFFIXES_DESC = sorted({e[2] for e in EXCHANGE_ENUM}, key=len, reverse=True)
#: 完整标的代码校验正则：结尾是 `.<交易所后缀>`
FULL_CODE_REGEX = re.compile(
    r"\.(" + "|".join(re.escape(s) for s in _SUFFIXES_DESC) + r")$"
)

#: 期货合约日期前置规整：`YYMM`(4位)/`YYMMDD`(6位) + 名称 -> 名称 + 日期
_FUTURE_DATE_NAME_RE = re.compile(
    r"^(\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])?)([^\d].*)$"
)

_MD_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


def _strip_markdown_fence(text: str) -> str:
    """去掉 LLM 输出可能带的 ```json ... ``` 包裹（防御，prompt 已要求禁止）。"""
    if not isinstance(text, str):
        return text
    return _MD_FENCE_RE.sub("", text.strip()).strip()


def _safe_parse_llm_dict(raw: dict[str, Any] | str | None) -> dict[str, Any]:
    """LLM 批量调用结果转 dict：已是 dict 直接用；str 尝试 JSON parse；失败 → {}。"""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            data = json.loads(_strip_markdown_fence(raw))
        except (json.JSONDecodeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def merge_and_validate(
    infer_codes: dict[str, Any] | str | None,
    split_codes: dict[str, Any] | str | None,
    ins_family_data: dict[str, Any] | str | None,
) -> list[dict[str, Any]]:
    """合并 3 路 LLM 输出 + 校验完整标的（对齐 `ticker_合并数据并校验完整标的.py`，确定性）。

    Args:
        infer_codes: 「大模型推断对应标的代码」输出，`{orgStr: [code, name, ...]}`
            （单个 orgStr 的 value 里的元素也可能是嵌套 list，会被展平）
        split_codes: 「标的代码和code的拆分」输出，`{orgStr: [kw1, kw2, ...]}`
        ins_family_data: 「大模型判断标的类型」输出，`{orgStr: "EQUITY"|"FUND"|...}`

    Returns:
        `[{"orgStr": str, "keywords": [{"id": str, "keyword": str, "isFull": bool}, ...]}, ...]`
    """
    infer_codes_d = _safe_parse_llm_dict(infer_codes)
    split_codes_d = _safe_parse_llm_dict(split_codes)
    ins_family_d = _safe_parse_llm_dict(ins_family_data)

    all_keys: list[str] = list(
        dict.fromkeys([*infer_codes_d.keys(), *split_codes_d.keys()])
    )

    result: list[dict[str, Any]] = []
    for org_str in all_keys:
        raw_infer = infer_codes_d.get(org_str)
        raw_infer = raw_infer if isinstance(raw_infer, list) else []
        from_infer: list[Any] = []
        for item in raw_infer:
            if isinstance(item, list):
                from_infer.extend(item)
            else:
                from_infer.append(item)

        from_split = split_codes_d.get(org_str)
        from_split = from_split if isinstance(from_split, list) else []

        seen: set[Any] = set()
        raw_keywords: list[Any] = []
        for val in (*from_infer, *from_split):
            if val is not None and val != "" and val not in seen:
                seen.add(val)
                raw_keywords.append(val)
        if org_str is not None and org_str != "" and org_str not in seen:
            raw_keywords.append(org_str)
            seen.add(org_str)

        # 期货合约日期前置规整：仅当 insFamily==FUTURE 且 orgStr 命中"日期+名称"模式
        ins_family = str(ins_family_d.get(org_str) or "").upper().strip()
        m = _FUTURE_DATE_NAME_RE.match(org_str) if isinstance(org_str, str) else None
        if m and ins_family == "FUTURE":
            normalized = m.group(2) + m.group(1)
            if normalized not in seen:
                seen.add(normalized)
                raw_keywords.append(normalized)

        keywords: list[dict[str, Any]] = []
        for kw in raw_keywords:
            if kw in MARKET_WORDS:
                continue
            is_full = bool(isinstance(kw, str) and FULL_CODE_REGEX.search(kw))
            kw_id = uuid.uuid4().hex[:12]
            keywords.append({"id": kw_id, "keyword": kw, "isFull": is_full})
            if is_full and isinstance(kw, str):
                stripped = re.sub(r"^0+", "", kw)
                if stripped != kw:
                    keywords.append({"id": kw_id, "keyword": stripped, "isFull": is_full})

        result.append({"orgStr": org_str, "keywords": keywords})

    return result


# ============================================================
# GOATS 客户端
# ============================================================


def _make_client() -> TickerClientHttpx:
    """构造 TickerClient，base_url + token 取自 settings（对齐真实后端 @PlatformApiAuth）。"""
    settings = get_settings()
    return TickerClientHttpx(
        base_url=settings.otc_api_base_url,
        token=settings.otc_api_secret or None,
    )


# ============================================================
# 3 路并行 LLM（infer_code / tokenize 拆分 / judge_type）+ rank
# ============================================================
#
# 均为非 thinking 模型批量调用（1 次调用处理全部候选词，对齐新 DSL 的 fan-out
# 并行设计），静态 prompt 通过 load_prompt() 加载，不做任何运行时动态拼接。

_RESULT_TAG_RE = re.compile(r"<result>\s*(.*?)\s*</result>", re.DOTALL)


def _extract_json_dict(content: str) -> dict[str, Any]:
    """从 LLM 原始输出提取 JSON object：优先 `<result>` 标签，否则整段内容。"""
    if not content:
        return {}
    m = _RESULT_TAG_RE.search(content)
    payload = m.group(1) if m else content
    payload = _strip_markdown_fence(payload)
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _extract_json_list(content: str) -> list[Any]:
    """从 LLM 原始输出提取 JSON array：优先 `<result>` 标签，否则整段内容。"""
    if not content:
        return []
    m = _RESULT_TAG_RE.search(content)
    payload = m.group(1) if m else content
    payload = _strip_markdown_fence(payload)
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        return []
    return data if isinstance(data, list) else []


async def _call_ticker_llm(prompt_name: str, user_message: str) -> str:
    """加载 `ticker/<prompt_name>.md` 静态 prompt，异步调用非 thinking 模型，返回原始文本。

    失败（网络异常 / 超时）时返回空串，交由调用方按空结果降级处理，不抛出阻塞管线。
    """
    from app.prompts import load_prompt

    prompt = load_prompt("ticker", prompt_name)
    llm = get_qwen_standard()
    messages = [
        SystemMessage(content=prompt.system),
        HumanMessage(content=user_message),
    ]
    try:
        resp = await llm.ainvoke(messages)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ticker LLM 调用失败 prompt=%s: %s", prompt_name, exc)
        return ""
    content = getattr(resp, "content", "") or ""
    return str(content)


async def infer_code_batch(candidates: list[str]) -> dict[str, Any]:
    """「大模型推断对应标的代码」：批量把候选词推断为 windCode + 名称候选。

    返回 `{orgStr: [code, name, ...]}`；单个 orgStr 可能没有该 LLM 涉及到的解析结果。
    """
    if not candidates:
        return {}
    user_message = json.dumps(candidates, ensure_ascii=False)
    content = await _call_ticker_llm("infer_code", user_message)
    return _extract_json_dict(content)


async def split_ticker_keywords(candidates: list[str]) -> dict[str, Any]:
    """「标的代码和code的拆分」：批量对候选词做保守字面拆分。

    返回 `{orgStr: [kw1, kw2, ...]}`。
    """
    if not candidates:
        return {}
    user_message = f"标的列表：{json.dumps(candidates, ensure_ascii=False)}"
    content = await _call_ticker_llm("tokenize", user_message)
    return _extract_json_dict(content)


async def judge_ticker_type(candidates: list[str]) -> dict[str, Any]:
    """「大模型判断标的类型」：批量判断每个候选词最可能的标的类型枚举。

    返回 `{orgStr: "EQUITY"|"FUND"|"FUTURE"|"INDEX"|""}`。
    """
    if not candidates:
        return {}
    user_message = json.dumps(candidates, ensure_ascii=False)
    content = await _call_ticker_llm("judge_type", user_message)
    return _extract_json_dict(content)


async def rank_candidates(
    keyword: str,
    results: list[Any],
    predicted_ins_family: str = "",
    expected_transaction_type: str = "",
) -> list[str]:
    """「大模型排序并过滤」：对 GOATS 候选按相关性过滤 + 排序，返回 windCode 列表。

    Args:
        keyword: 用户搜索关键字（用于判断相关性意图）
        results: GOATS `search_securities_instrument` 返回的候选（含 windCode 等字段）
        predicted_ins_family: judge_ticker_type 对该 orgStr 的类型预测（仅排序信号）
        expected_transaction_type: 业务层显式给出的期望交易品种（P1 暂无来源，默认空）

    Returns:
        过滤 + 排序后的 windCode 列表，相关性最高排最前；无相关结果返回 []
    """
    if not results:
        return []
    payload = [
        {
            "windCode": r.windCode,
            "insShtDesc": r.insShtDesc,
            "insLngDesc": r.insLngDesc,
            "insFamily": getattr(r, "insFamily", None),
            "currency": getattr(r, "currency", None),
            "exchange": getattr(r, "exchange", None),
            "tradableNow": getattr(r, "tradableNow", None),
            "hasPermission": getattr(r, "hasPermission", None),
            "transactionTypes": getattr(r, "transactionTypeLists", None),
        }
        for r in results
    ]
    user_message = (
        f"关键字：{keyword}\n"
        f"用户期望类型：{predicted_ins_family}\n"
        f"用户期望品种：{expected_transaction_type}\n"
        f"标的列表：{json.dumps(payload, ensure_ascii=False)}"
    )
    content = await _call_ticker_llm("rank", user_message)
    ranked = _extract_json_list(content)
    return [c for c in ranked if isinstance(c, str)]


__all__ = [
    "EXCHANGE_ENUM",
    "MARKET_WORDS",
    "FULL_CODE_REGEX",
    "tokenize",
    "format_candidate_list",
    "merge_and_validate",
    "infer_code_batch",
    "split_ticker_keywords",
    "judge_ticker_type",
    "rank_candidates",
]
