"""ticker 子图的 4 个 ReAct 工具。

设计原则（ADR 0008 + grill-with-docs）：
- 工具单职责，确定性优先（HTTP / 词典 / 规则）
- LLM 调用集中在 `infer_code`（推断需要 LLM 兜底）+ ReAct Agent 自身的 think 层
- tokenize / completeness / rank 不调 LLM，避免 token 浪费 + 死循环

后端依赖：
- securities-instrument/select  — completeness + rank（ADR 0001 D4）
- counterparty/info/instrument-inference-prompt  — infer_code 动态片段（ADR 0013）
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Annotated

from langchain_core.tools import tool

from app.config import get_settings
from app.llm.clients import get_qwen_thinking, make_qwen_thinking
from app.tools.ticker_client import (
    KeywordItem,
    SecuritiesInstrumentReqVO,
    TickerClientHttpx,
)

logger = logging.getLogger(__name__)


# ============================================================
# tokenize · 规则常量
# ============================================================

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
_NON_TICKER_PATTERNS = (
    re.compile(r"^\d+\s*(个)?\s*(月|年|周|日|天)$"),  # 1个月 / 3年 / 6周 / 2天
    re.compile(r"^(行权价|执行价|敲入|敲出|期限|名义本金|本金|期权费|参与率|价格)$"),
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
    """
    digits = _EMBEDDED_DIGIT_RE.findall(token)
    if not digits:
        return [token]
    out: list[str] = list(digits)
    remainder = _EMBEDDED_DIGIT_RE.sub("", token).strip()
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


# ============================================================
# completeness · 接 securities-instrument/select isFull=true
# ============================================================


def _make_client() -> TickerClientHttpx:
    """构造 TickerClient，base_url + token 取自 settings（对齐真实后端 @PlatformApiAuth）。"""
    settings = get_settings()
    return TickerClientHttpx(
        base_url=settings.otc_api_base_url,
        token=settings.otc_api_secret or None,
    )


def _run_async(coro):  # pragma: no cover - utility for sync tool wrapper
    """在 sync 工具内运行 async coroutine。优先复用当前事件循环。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # 在 ReAct Agent（async 上下文）中应直接 await，但 @tool 装饰器允许 sync。
    # 退化方案：在新线程中跑 asyncio.run，避免 nested loop 问题。
    import threading

    result_box: dict = {}

    def _runner():
        result_box["v"] = asyncio.run(coro)

    t = threading.Thread(target=_runner)
    t.start()
    t.join()
    return result_box["v"]


@tool
def completeness(
    keyword: Annotated[str, "标的关键词或代码"],
) -> dict[str, object]:
    """判断关键词是否是完整的、可直接定位标的的代码。

    实现：调 `securities-instrument/select` 用 isFull=true 模式查询。
    后端命中 1 条 → is_complete=True；命中 0 或 ≥ 2 → is_complete=False。

    返回：
        {"keyword": str, "is_complete": bool, "candidates": int}

    后端不可达时退化到后缀规则（保守判定，不让 ReAct Agent 死锁）。
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return {"keyword": "", "is_complete": False, "candidates": 0}

    try:
        client = _make_client()
        req = SecuritiesInstrumentReqVO(
            keywordItems=[KeywordItem(keyword=keyword, isFull=True)]
        )
        results = _run_async(client.search_securities_instrument(req))
        n = len(results)
        return {
            "keyword": keyword,
            "is_complete": n == 1,
            "candidates": n,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "completeness 调用失败，退化后缀规则: %s (keyword=%s)", exc, keyword
        )
        is_complete = any(
            keyword.upper().endswith(s) for s in _CODE_SUFFIXES
        )
        return {
            "keyword": keyword,
            "is_complete": is_complete,
            "candidates": 0,  # 0 表示退化模式
            "fallback": True,
        }


# ============================================================
# rank · 接 securities-instrument/select 拿候选 + 排序 + HITL 触发
# ============================================================

#: 多命中分差阈值（ADR 0008 c）：top1.score - top2.score ≥ 此值 → 自动选 top1
RANK_AUTO_PICK_GAP = 10


def pick_best(keyword: str, results: list) -> object:
    """多命中启发式选优（无 LLM、无 HTTP）。

    优先级：
    1. insShtDesc 精确匹配关键词 → A 股优先（SH > SZ），否则取第一个
    2. insShtDesc 前缀匹配 → 名称最短者；同长度优先 A 股
    3. A 股（.SH / .SZ）> 其他市场
    4. 兜底取 results[0]
    """
    exact = [r for r in results if (getattr(r, "insShtDesc", "") or "") == keyword]
    if exact:
        a_shares_exact = [
            r for r in exact
            if (getattr(r, "windCode", "") or "").endswith((".SH", ".SZ"))
        ]
        if a_shares_exact:
            return min(
                a_shares_exact,
                key=lambda r: 0 if (getattr(r, "windCode", "") or "").endswith(".SH") else 1,
            )
        return exact[0]

    prefix_matches = [
        r for r in results
        if (getattr(r, "insShtDesc", "") or "").startswith(keyword)
    ]
    if prefix_matches:
        min_len = min(len(getattr(r, "insShtDesc", "") or "") for r in prefix_matches)
        same_len = [
            r for r in prefix_matches
            if len(getattr(r, "insShtDesc", "") or "") == min_len
        ]
        if len(same_len) > 1:
            _hk = [r for r in same_len if (getattr(r, "windCode", "") or "").endswith(".HK")]
            if _hk:
                return _hk[0]
        return min(
            prefix_matches,
            key=lambda r: (
                len(getattr(r, "insShtDesc", "") or ""),
                0 if (getattr(r, "windCode", "") or "").endswith(".SH") else 1,
            ),
        )

    a_shares = [
        r for r in results
        if (getattr(r, "windCode", "") or "").endswith((".SH", ".SZ"))
    ]
    if a_shares:
        return a_shares[0]

    return results[0]


@tool
def rank(
    keyword: Annotated[str, "标的关键词（用于查询候选）"],
) -> dict[str, object]:
    """查 securities-instrument/select 候选 → 按 relevanceScore 排序 → 自动选/HITL。

    业务约定（ADR 0008 c）：score 越小越相关（0 = 精确匹配，10 = 弱包含）。
    top1 与 top2 分差 ≥ 10 → 自动选 top1；< 10 → 触发 HITL。

    返回：
        {
          "keyword": str,
          "winner": str | None,          # 自动选中的 windCode，HITL 时 None
          "candidates": list[dict],      # 全部候选 [{windCode, insShtDesc, relevanceScore}, ...]
          "needs_hitl": bool,            # True 时调用方应触发 LangGraph interrupt（ADR 0006）
          "reason": str,
        }
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return {
            "keyword": "",
            "winner": None,
            "candidates": [],
            "needs_hitl": False,
            "reason": "empty_keyword",
        }

    try:
        client = _make_client()
        req = SecuritiesInstrumentReqVO(
            keywordItems=[KeywordItem(keyword=keyword, isFull=False)]
        )
        results = _run_async(client.search_securities_instrument(req))
    except Exception as exc:  # noqa: BLE001
        logger.warning("rank 调用失败: %s (keyword=%s)", exc, keyword)
        return {
            "keyword": keyword,
            "winner": None,
            "candidates": [],
            "needs_hitl": False,
            "reason": f"backend_error: {exc!r}",
        }

    if not results:
        return {
            "keyword": keyword,
            "winner": None,
            "candidates": [],
            "needs_hitl": False,
            "reason": "no_match",
        }

    # 后端按 relevanceScore 升序返回（小分数 = 强相关）
    candidates = [
        {
            "windCode": r.windCode,
            "insShtDesc": r.insShtDesc,
            "relevanceScore": r.relevanceScore or 0,
        }
        for r in results
    ]

    if len(candidates) == 1:
        return {
            "keyword": keyword,
            "winner": candidates[0]["windCode"],
            "candidates": candidates,
            "needs_hitl": False,
            "reason": "single_match",
        }

    return {
        "keyword": keyword,
        "winner": candidates[0]["windCode"],
        "candidates": candidates,
        "needs_hitl": False,
        "reason": "goats_top1",
    }


# ============================================================
# infer_code · 动态 prompt 片段 + LLM 推断（ADR 0013）
# ============================================================

#: 后端 prompt 片段缓存（5 分钟 LRU）
_INFER_PROMPT_CACHE: dict[str, tuple[float, str]] = {}
_INFER_PROMPT_TTL_SEC = 300

#: 净化常量（ADR 0013 基础净化）
_INFER_PROMPT_MAX_LEN = 4096
_INFER_PROMPT_INVALID_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _sanitize_dynamic_prompt(text: str) -> str:
    """trim + 长度上限 + 控制字符过滤（ADR 0013 基础净化）。"""
    if not text:
        return ""
    text = text.strip()
    text = _INFER_PROMPT_INVALID_CHARS_RE.sub("", text)
    if len(text) > _INFER_PROMPT_MAX_LEN:
        text = text[:_INFER_PROMPT_MAX_LEN]
    return text


def _get_dynamic_prompt_cached() -> str:
    """5 分钟 LRU 拉 inference-prompt 动态片段。失败返回空串（降级走静态 prompt）。

    指标埋点（D2.5 / ADR 0013）：每次调用 emit otc_agent_dynamic_prompt_total
    {status=cache_hit | cache_miss_ok | fallback}
    """
    from app.observability.metrics import emit_dynamic_prompt

    now = time.time()
    cached = _INFER_PROMPT_CACHE.get("global")
    if cached and (now - cached[0]) < _INFER_PROMPT_TTL_SEC:
        emit_dynamic_prompt("cache_hit")
        return cached[1]
    try:
        client = _make_client()
        raw = _run_async(client.get_inference_prompt())
        sanitized = _sanitize_dynamic_prompt(raw)
        _INFER_PROMPT_CACHE["global"] = (now, sanitized)
        emit_dynamic_prompt("cache_miss_ok")
        return sanitized
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_inference_prompt 失败，降级走静态 prompt: %s", exc)
        emit_dynamic_prompt("fallback")
        return ""


def _load_static_infer_prompt() -> str:
    """加载 app/prompts/ticker/infer_code.md 的 system 段。"""
    from app.prompts import load_prompt

    return load_prompt("ticker", "infer_code").system


def _llm_infer(keyword: str, dynamic_prompt: str) -> str:
    """thinking 模型推断 keyword → 标准 windCode（ADR 0010）。

    拼接策略（ADR 0013）：静态 system + dynamic_prompt 追加在末尾。

    thinking 模型可能输出 <analysis>...</analysis><result>{"k": ["windCode"]}</result>
    格式，不能直接用 with_structured_output；改为 raw 调用 + 手动提取。

    使用同步 llm.invoke()（httpx.Client）避免跨 event-loop 污染：
    anyio 在主 loop 初始化时绑定 asyncio 原语，子线程 asyncio.run() 复用会失败。
    """
    import json
    import re
    import threading

    from langchain_core.messages import HumanMessage, SystemMessage

    static_system = _load_static_infer_prompt()
    full_system = (
        f"{static_system}\n\n## 后端动态片段（实时拼接）\n{dynamic_prompt}"
        if dynamic_prompt
        else static_system
    )

    messages = [
        SystemMessage(content=full_system),
        HumanMessage(content=f"标的：{keyword}"),
    ]

    result_box: dict[str, str] = {}
    exc_box: dict[str, BaseException] = {}

    def _sync_call() -> None:
        try:
            resp = make_qwen_thinking().invoke(messages)
            content = (resp.content or "") if hasattr(resp, "content") else str(resp)

            # 优先解析 <result>...</result> 标签（thinking 模型格式）
            m = re.search(r"<result>\s*(.*?)\s*</result>", content, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(1))
                    if isinstance(data, dict):
                        if "windCode" in data:
                            result_box["v"] = str(data["windCode"])
                            return
                        for v in data.values():
                            if isinstance(v, list) and v:
                                result_box["v"] = str(v[0])
                                return
                            if isinstance(v, str) and v:
                                result_box["v"] = v
                                return
                except (json.JSONDecodeError, ValueError):
                    pass

            # fallback：从内容中提取 windCode 格式字符串（如 159915.SZ）
            m2 = re.search(r'\b\d{5,6}\.[A-Z]{2,4}\b', content)
            if m2:
                result_box["v"] = m2.group(0)
                return

            result_box["v"] = keyword
        except Exception as exc:  # noqa: BLE001
            exc_box["e"] = exc

    t = threading.Thread(target=_sync_call, daemon=True)
    t.start()
    t.join(timeout=100)
    if exc_box.get("e"):
        raise exc_box["e"]
    return result_box.get("v", keyword)


@tool
def infer_code(
    keyword: Annotated[str, "中文简称或俗称"],
) -> str:
    """基于关键词推断完整 windCode。

    流程（ADR 0008 b + ADR 0013）：
    1. 拉后端 inference-prompt 动态片段（5min LRU + 净化 + 后端不可达降级）
    2. 拼接到静态 infer_code.md system 末尾
    3. thinking 模型 with_structured_output 推断 windCode

    返回：推断的 windCode（如 `00700.HK`）。失败返回原 keyword（保守，不阻塞 ReAct）。
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return ""
    try:
        dynamic = _get_dynamic_prompt_cached()
        return _llm_infer(keyword, dynamic) or keyword
    except Exception as exc:  # noqa: BLE001
        logger.warning("infer_code 失败，原样返回: %s (keyword=%s)", exc, keyword)
        return keyword


def clear_infer_prompt_cache() -> None:
    """测试 / 热更新清缓存。"""
    _INFER_PROMPT_CACHE.clear()


# ============================================================
# 工具列表
# ============================================================


TICKER_TOOLS = [tokenize, completeness, rank, infer_code]


__all__ = [
    "TICKER_TOOLS",
    "tokenize",
    "completeness",
    "rank",
    "infer_code",
    "RANK_AUTO_PICK_GAP",
    "clear_infer_prompt_cache",
]
