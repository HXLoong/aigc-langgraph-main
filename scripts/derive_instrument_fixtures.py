"""从 swap 业务集派生"标的识别"意图集（tests/fixtures/intent/swap_instrument.jsonl 的来源）。

用法：
    python scripts/derive_instrument_fixtures.py --dry-run            # 逐条打印抽取结果供人工复核
    python scripts/derive_instrument_fixtures.py --out tmp/intent_drafts/swap_instrument.jsonl
    python scripts/derive_instrument_fixtures.py --only-reviewed --out tests/fixtures/intent/swap_instrument.jsonl

口径（docs/backend-instrument-boundary.md）：LangGraph 只把用户原文里的标的表达逐字送给后端，
权威识别由 Java 完成。因此期望值不是证券代码，而是"用户原文里的表达"任一候选：
- 订单数与顺序以业务卡片的 `标的代码：` 行为准（后端权威回执）
- 原文含该代码的主体（300748 / NVDA / 9618 …）→ 候选 = [名称+代码, 代码, 名称]
- 原文不含代码（京东 / 阿里巴巴 …）→ 去掉交易词汇后的残留名称
- 市场限定词（港股 / A股 / 美股 / 深港通 / 沪港通 …）→ placeOrderTransactionType 候选；无限定词不断言
- 卡片为【待补充】或残留无法与订单一一对应 → review.pending，需人工补标
原业务卡片的代码保留在 reference.backend_codes 供人工核对，不参与评分。
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = sorted((REPO_ROOT / "tests" / "fixtures" / "categories").glob("swap*.jsonl"))
DEFAULT_OUT = REPO_ROOT / "tmp" / "intent_drafts" / "swap_instrument.jsonl"

#: 市场限定词 → placeOrderTransactionType 候选（港股口语可能落港股通，三者任一即可）
_MARKET_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("深港通", ("SZ_HK_CONNECT",)),
    ("沪港通", ("SH_HK_CONNECT",)),
    ("港股", ("HK_STOCK", "SH_HK_CONNECT", "SZ_HK_CONNECT")),
    ("A股", ("A_SHARE",)),
    ("美股", ("US_STOCK",)),
    ("境内期货", ("CHN_FUTURE",)),
    ("跨境期货", ("CROSS_FUTURE",)),
)
_UNRESOLVED_CODE = "【待补充】"
_GENERIC_SUFFIX = ("合约",)

#: 交易词汇（闭合集合，只用于从原文剥离非标的片段；不是业务数据字典）
_CN_VOCAB = (
    "根据市场成交量成交", "算法开始时间", "算法结束时间", "全部持仓", "集合竞价", "开盘尽快",
    "全天均价", "不限价", "买入开仓", "买入平仓", "卖出开仓", "卖出平仓", "新增指令", "股份数量",
    "建仓方式", "价值精选", "部分卖出", "没成的话", "到时候", "这部分", "人民币", "到收盘",
    "市价", "限价", "均价", "收盘", "跟量", "买入", "卖出", "卖空", "平空", "沽出", "清仓",
    "全部", "全天", "剩下", "备注", "标的", "方向", "数量", "金额", "帮我", "谢谢", "稳健",
    "互换", "平仓", "挂单", "继续", "占", "再", "转", "沽", "买", "卖", "的话",
)
_LATIN_VOCAB = ("pov", "twap", "vwap", "mkt", "asap", "cny", "usd", "hkd", "b", "s")
_VOCAB_RE = re.compile(
    "|".join(re.escape(word) for word in sorted(_CN_VOCAB, key=len, reverse=True))
    + "|(?<![A-Za-z])(?:" + "|".join(_LATIN_VOCAB) + r")(?![A-Za-z])",
    re.IGNORECASE,
)
_MARKET_RE = re.compile("|".join(re.escape(hint) for hint, _ in _MARKET_HINTS))
#: 带单位 / 价格 / 时间 / 1–3 位独立数字视为数量或价格；4–6 位独立数字和粘在名称上的数字
#: 可能是证券代码或合约月份，保留给分块阶段
_NUMERIC_RE = re.compile(
    r"@\s*[\d.,]+|[\d.,]*\d\s*(?:%|万股|万元|万|亿|股|手|元|张|个亿|个|[wWkK](?![A-Za-z]))"
    r"|\d{1,2}:\d{2}(?::\d{2})?|\d+\.\d+|(?<![A-Za-z0-9一-龥])\d{1,3}(?![0-9])"
)
_CN_NUMBER_RE = re.compile(r"[一二两三四五六七八九十]+[一二两三四五六七八九十百千]*(?:万|亿|个亿)*(?:股|元|手|张|个)?")
_PUNCT_RE = re.compile(r"[，。、；;：:,.（）()【】\[\]!！?？\-—~《》\"'“”]+")
_CN_CHUNK_RE = re.compile(r"(?P<name>[一-龥]{2,12})(?P<letter>[A-Z](?![A-Za-z]))?(?P<num>\d{4})?(?P<suffix>合约)?")
_LATIN_CODE_CHUNK_RE = re.compile(r"(?<![A-Za-z])(?P<code>[A-Za-z]{1,6}\d{3,6})(?P<suffix>合约)?")
_DIGIT_CODE_CHUNK_RE = re.compile(r"(?<![A-Za-z0-9一-龥])\d{4,6}(?![0-9])")
_LATIN_WORDS_RE = re.compile(r"[A-Za-z][A-Za-z]+(?:\s+[A-Za-z][A-Za-z]+)*")


def market_candidates(text: str) -> list[str]:
    """按市场限定词给出 transaction_type 候选；无限定词返回空列表（不断言）。"""
    candidates: list[str] = []
    for hint, values in _MARKET_HINTS:
        if hint in text:
            for value in values:
                if value not in candidates:
                    candidates.append(value)
    return candidates


def _card_codes(obj: dict[str, Any]) -> list[str]:
    card = obj.get("response_contains") or ""
    lines = card.splitlines() if isinstance(card, str) else [str(x) for x in card]
    return [line.split("：", 1)[1].strip() for line in lines if line.startswith("标的代码：")]


def _strip_vocab_tail(name: str) -> str:
    """相邻中文名末尾若粘着交易词（"苹果市价"），逐词剥掉。"""
    changed = True
    while changed and name:
        changed = False
        for word in sorted(_CN_VOCAB, key=len, reverse=True):
            if name.endswith(word) and len(name) > len(word):
                name = name[: -len(word)]
                changed = True
    return name


def _code_in_text(text: str, code: str) -> dict[str, str] | None:
    """原文里找到代码主体（含可选交易所后缀）→ {token, before, after}。"""
    key = code.split(".", 1)[0]
    if not key or code == _UNRESOLVED_CODE:
        return None
    pattern = re.compile(
        rf"(?P<before>[一-龥]{{2,8}})?(?P<token>{re.escape(key)}(?:\.[A-Za-z]{{1,3}})?)"
        rf"(?![A-Za-z0-9])\s?(?P<after>[一-龥]{{2,8}})?",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if match is None:
        return None
    return {
        "token": match.group("token"),
        "before": match.group("before") or "",
        "after": _strip_vocab_tail(match.group("after") or ""),
    }


def _code_alternatives(found: dict[str, str], text: str) -> list[str]:
    token, before, after = found["token"], found["before"], found["after"]
    alternatives: list[str] = []
    if before:
        alternatives.append(f"{before}{token}")
    if after:
        joiner = " " if f"{token} {after}" in text else ""
        alternatives.append(f"{token}{joiner}{after}")
    alternatives.append(token)
    for name in (before, after):
        if name and name not in _GENERIC_SUFFIX and name not in alternatives:
            alternatives.append(name)
    return alternatives


def _residual_chunks(text: str) -> list[list[str]]:
    """去掉交易词汇 / 数量 / 价格后，剩下的名称片段（每个片段给出候选表达）。"""
    cleaned = _MARKET_RE.sub(" ", text)
    cleaned = _VOCAB_RE.sub(" ", cleaned)
    cleaned = _NUMERIC_RE.sub(" ", cleaned)
    cleaned = _CN_NUMBER_RE.sub(" ", cleaned)
    cleaned = _PUNCT_RE.sub(" ", cleaned)
    found: list[tuple[int, list[str]]] = []
    consumed: list[tuple[int, int]] = []

    def _taken(start: int) -> bool:
        return any(begin <= start < end for begin, end in consumed)

    for match in _LATIN_CODE_CHUNK_RE.finditer(cleaned):
        combined = match.group("code") + (match.group("suffix") or "")
        found.append((match.start(), [combined, match.group("code")] if match.group("suffix") else [match.group("code")]))
        consumed.append(match.span())
    for match in _CN_CHUNK_RE.finditer(cleaned):
        if _taken(match.start()):
            continue
        name = match.group("name")
        if name in _GENERIC_SUFFIX:
            continue
        with_letter = name + (match.group("letter") or "")
        combined = with_letter + (match.group("num") or "") + (match.group("suffix") or "")
        alternatives = [combined]
        for alternative in (with_letter, name):
            if alternative not in alternatives:
                alternatives.append(alternative)
        found.append((match.start(), alternatives))
        consumed.append(match.span())
    for match in _DIGIT_CODE_CHUNK_RE.finditer(cleaned):
        if not _taken(match.start()):
            found.append((match.start(), [match.group(0)]))
            consumed.append(match.span())
    for match in _LATIN_WORDS_RE.finditer(cleaned):
        if _taken(match.start()):
            continue
        words = match.group(0).strip()
        if len(words) >= 2:
            found.append((match.start(), [words]))
    return [alternatives for _, alternatives in sorted(found, key=lambda item: item[0])]


def derive_case(
    obj: dict[str, Any], *, source_stem: str, ignore_tokens: tuple[str, ...] = ()
) -> dict[str, Any]:
    """一条 swap 业务集 case → 标的识别意图集 case（草稿）。"""
    case_no = str(obj.get("caseNo") or obj.get("id") or "").strip()
    if not case_no:
        raise ValueError(f"{source_stem}: caseNo/id is required")
    send_text = str(obj.get("send_text") or "")
    text = send_text
    for token in ignore_tokens:
        text = text.replace(token, " ")
    text = text.strip()

    codes = _card_codes(obj)
    markets = market_candidates(text)
    pending_reasons: list[str] = []
    instruments: list[dict[str, Any]] = []
    unresolved: list[int] = []
    for index, code in enumerate(codes):
        found = _code_in_text(text, code)
        if found is None:
            instruments.append({"expression": []})
            unresolved.append(index)
        else:
            instruments.append({"expression": _code_alternatives(found, text)})

    if unresolved:
        residual = _residual_chunks(text)
        unresolved_codes = {codes[i] for i in unresolved}
        if any(codes[i] == _UNRESOLVED_CODE for i in unresolved):
            pending_reasons.append("backend card has 【待补充】; expected expression unknown")
        elif len(residual) == len(unresolved):
            for index, chunk in zip(unresolved, residual, strict=True):
                instruments[index]["expression"] = chunk
        elif len(residual) == 1 and len(unresolved_codes) == 1:
            for index in unresolved:
                instruments[index]["expression"] = list(residual[0])
        else:
            pending_reasons.append(
                f"{len(unresolved)} order(s) unresolved but {len(residual)} residual chunk(s): {residual}"
            )
    if not codes:
        pending_reasons.append("backend card has no 标的代码 line")
    if markets:
        for item in instruments:
            item["transaction_type"] = list(markets)

    card = obj.get("response_contains") or ""
    intent = "place_order_request" if "场外收益互换详情" in str(card) else ""
    if not intent:
        pending_reasons.append("card is not a swap order card; intent unknown")

    case: dict[str, Any] = {
        "caseNo": f"intent-swap-instrument-{case_no}",
        "name": str(obj.get("name") or case_no),
        "category": "intent/swap",
        "type": obj.get("type") if obj.get("type") in ("positive", "negative") else "positive",
        "source": f"derived:{source_stem}#{case_no}",
        "send_text": send_text,
        "at_bot": obj.get("at_bot", True),
        "quote_previous": obj.get("quote_previous", False),
        "expected": {"product_type": "swap", "intent": intent, "instruments": instruments},
        "sub_scenes": [],
        "reference": {"backend_codes": codes},
    }
    if pending_reasons:
        case["review"] = {"status": "pending", "reasons": pending_reasons}
    return case


def _iter_source(paths: list[Path]) -> list[tuple[str, dict[str, Any]]]:
    records: list[tuple[str, dict[str, Any]]] = []
    for path in paths:
        for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{line_number}: case must be an object")
            records.append((path.stem, obj))
    return records


def write_cases(
    sources: list[Path], out: Path, *, ignore_tokens: tuple[str, ...], only_reviewed: bool
) -> dict[str, int]:
    """写出标的识别用例；返回 {written, pending}。only_reviewed 时 pending 不写入。"""
    written: list[dict[str, Any]] = []
    pending = 0
    for stem, obj in _iter_source(sources):
        case = derive_case(obj, source_stem=stem, ignore_tokens=ignore_tokens)
        if "review" in case:
            pending += 1
            if only_reviewed:
                continue
        written.append(case)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "".join(json.dumps(case, ensure_ascii=False) + "\n" for case in written),
        encoding="utf-8",
    )
    logger.info("wrote cases=%d pending=%d path=%s", len(written), pending, out)
    return {"written": len(written), "pending": pending}


def _print_review_table(sources: list[Path], ignore_tokens: tuple[str, ...]) -> None:
    for stem, obj in _iter_source(sources):
        case = derive_case(obj, source_stem=stem, ignore_tokens=ignore_tokens)
        text = case["send_text"]
        for token in ignore_tokens:
            text = text.replace(token, "")
        flag = "PENDING" if "review" in case else "ok"
        instruments = [
            (item["expression"], item.get("transaction_type", []))
            for item in case["expected"]["instruments"]
        ]
        logger.info(
            "%-7s %s | %s | %s | ref=%s",
            flag,
            case["caseNo"].removeprefix("intent-swap-instrument-"),
            text.strip().replace("\n", " ")[:60],
            instruments,
            case["reference"]["backend_codes"],
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, action="append", help="swap 业务集 JSONL，可重复；默认 categories/swap*.jsonl")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--ignore-token", action="append", default=[],
        help="从原文剥离的固定片段（如测试环境的交易对手名），可重复；只影响抽取，不改 send_text",
    )
    parser.add_argument("--only-reviewed", action="store_true", help="只写出无 review.pending 的 case")
    parser.add_argument("--dry-run", action="store_true", help="逐条打印抽取结果，不写文件")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sources = args.source or DEFAULT_SOURCES
    ignore = tuple(args.ignore_token)
    if args.dry_run:
        _print_review_table(sources, ignore)
        return 0
    summary = write_cases(sources, args.out, ignore_tokens=ignore, only_reviewed=args.only_reviewed)
    logger.info("done: %s", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
