#!/usr/bin/env python3
"""V1 闭环验证 demo —— 完全 in-process，无需 Docker / LLM API / Dify。

用法：
    python scripts/demo_closed_loop.py
    python scripts/demo_closed_loop.py --sample tests/fixtures/golden.jsonl
    python scripts/demo_closed_loop.py --max-cases 5 --verbose

设计：
- LangGraph 主图 + InMemorySaver（不依赖 MySQL）
- LLM 用 SmartLLMMock 替换：根据 raw_content 的关键词模式 + 结构化输出 Pydantic
  类型，返回符合该 case expected 的输出。这只是验证**管道连通性**，
  不验证 LLM 准确率（那是 eval_golden.py 的职责）。
- OtcBackendClient 用 mock 替换：所有调用返回 code=0

输出：
- 每条 case 的 PASS/FAIL（基于 product_type + intent 是否符合 expected）
- 汇总：通过率、按子图分组的统计、平均延迟
- 失败时退出码 1（CI 友好）

这是"V1 闭环可用"的唯一证据：在零外部依赖下，所有路径都能跑通。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch


# ============================================================
# 1. 设置 mock 环境变量（避免真实 .env 校验）
# ============================================================
def _setup_env() -> None:
    defaults = {
        "CHECKPOINT_MYSQL_URI": "mysql://mock:mock@localhost:3306/mock",
        "BUSINESS_MYSQL_URI": "mysql+aiomysql://mock:mock@localhost:3306/mock",
        "QWEN_API_BASE": "http://mock/v1",
        "QWEN_API_KEY": "mock-qwen-key",
        "OTC_API_BASE_URL": "http://localhost/admin-api",
        "OTC_API_SECRET": "mock-secret",
    }
    for k, v in defaults.items():
        os.environ.setdefault(k, v)


# ============================================================
# 2. SmartLLMMock：根据输入和目标 Pydantic 类型合成结构化输出
# ============================================================
# 宽松匹配（与 app/nodes/route.py 的 SWAP_ORDER_ID_PATTERN 一致），用于 demo 路由判断
SWAP_ID_RE = re.compile(r"H-\d{8}-[A-Z0-9]{4,16}")
CLOSE_ID_RE = re.compile(r"CO-\d{8}-[A-Z0-9]{4,16}")
CONTRACT_RE = re.compile(r"OPT[A-Z]?-[A-Z0-9]+")


def _swap_intent_from_text(text: str) -> str:
    """根据关键词推断 swap 意图（覆盖 golden 中所有 swap case）。"""
    if "确认改单" in text or "确认修改" in text:
        return "confirm_modify_order"
    if "确认撤" in text:
        return "confirm_cancel_order"
    if "确认" in text and SWAP_ID_RE.search(text):
        return "confirm_order"
    if "查" in text and SWAP_ID_RE.search(text):
        return "query_order_status"
    if "撤" in text:
        return "cancel_order_request"
    return "place_order_request"


def _close_intent_from_text(text: str) -> str:
    """根据关键词推断 close 意图。"""
    if "确认撤" in text:
        return "close_order_confirm_cancel"
    if "撤" in text:
        return "close_order_cancel"
    if "确认平" in text or "确认 平" in text:
        return "close_order_confirm"
    if "查" in text or "持仓" in text or "我有" in text:
        return "close_order_query"
    return "close_order_request"


def _option_intent_from_text(text: str) -> str:
    """根据关键词推断 option 意图。"""
    if "撤" in text:
        return "cancel_order"
    if "确认" in text:
        return "confirm"
    if "下单" in text and "询价" not in text:
        return "place_order"
    if "改" in text:
        return "modify_order"
    return "new_inquiry"


class _StructuredLLM:
    """对应 llm.with_structured_output(Pydantic) 返回的对象。"""

    def __init__(self, output_cls: type, raw_text_getter):
        self.output_cls = output_cls
        self._get_text = raw_text_getter

    async def ainvoke(self, messages, *args, **kwargs):
        return _synthesize_output(self.output_cls, self._get_text(messages))


class SmartLLMMock:
    """伪装 get_qwen_standard() / get_qwen_thinking() 的返回值。"""

    def __init__(self):
        # 普通调用（无 structured_output）— ticker rank 用
        self._raw_text = ""

    def with_structured_output(self, output_cls):
        return _StructuredLLM(output_cls, self._extract_text)

    @staticmethod
    def _extract_text(messages) -> str:
        """从 messages 列表里抽取 user 消息内容。

        关键：只取 ("user", ...) 消息，避免捕获 system prompt 中的关键词
        （system prompt 里通常会列举所有意图类型描述，会污染关键词匹配）。
        进一步抽取 raw_content: 字段，因为 user message 通常拼接了多段 context。
        """
        user_text_parts: list[str] = []
        for m in messages or []:
            role, content = None, None
            if isinstance(m, tuple) and len(m) == 2:
                role, content = m[0], m[1]
            elif isinstance(m, dict):
                role, content = m.get("role"), m.get("content", "")
            elif hasattr(m, "type") and hasattr(m, "content"):
                role, content = getattr(m, "type", None), m.content
            if role in ("user", "human", "Human"):
                user_text_parts.append(str(content))
        joined = "\n".join(user_text_parts)
        # 优先提取 raw_content: 行的值
        m = re.search(r"raw_content:\s*([^\n]+)", joined)
        if m:
            quote = re.search(r"quote_content:\s*([^\n]+)", joined)
            return m.group(1) + ("\n" + quote.group(1) if quote and quote.group(1) != "(无)" else "")
        return joined

    # 用于 ticker rank（自由文本，无 structured_output）
    async def ainvoke(self, messages, *args, **kwargs):
        text = self._extract_text(messages)
        # Ticker rank 节点期望返回 <result>[...]</result>
        # 我们直接返回所有候选（demo 里 ranking 不关键）
        resp = MagicMock()
        resp.content = '<analysis>demo</analysis>\n<result>[]</result>'
        return resp


def _synthesize_output(output_cls, text: str) -> Any:
    """根据目标类型 + 输入文本，合成一个合法的 Pydantic 实例。"""
    name = output_cls.__name__

    # ===== Ticker tokenize =====
    if name == "TokenizeOutput":
        # 按空格/标点切，过滤明显非标的的词
        keywords = [
            w.strip() for w in re.split(r"[/、,，;；\s]+", text) if w.strip()
        ]
        # 只保留可能是标的的（去掉常见动词）
        STOP = {
            "买", "卖", "做", "下单", "询价", "互换", "TRS", "swap", "@机器人",
            "帮我", "帮", "一笔", "一手", "一只", "市价", "限价", "全部",
            "确认", "撤", "确认平", "确认撤", "查", "查询", "我有", "持仓",
            "今天", "在吗", "你好", "天气", "怎么样", "期权", "下月合约",
            "100", "1000", "2000", "500", "3", "1", "5", "100万", "500万", "1000w",
            "个月", "1M", "3M", "1Y", "M", "Y", "雪球", "参与型看涨", "参与型看跌",
            "欧式看涨", "欧式看跌", "美式看涨", "美式看跌", "亚式看涨", "亚式看跌",
            "行权价", "行权价400", "行权价150", "行权价500", "行权价1800", "期限",
            "名义", "个", "笔", "股",
        }
        clean = [k for k in keywords if k not in STOP and 1 < len(k) < 30 and not k.isdigit()]
        return output_cls(keywords=clean[:10], needs_refinement=False)

    # ===== Swap =====
    if name == "SwapIntentOutput":
        return output_cls(type=_swap_intent_from_text(text), confidence=0.9, reason="demo")

    if name == "SwapPlaceOrderOutput":
        from app.subgraphs.swap_models import SwapOrderLeg
        return output_cls(
            type="place_order_request",
            order_list=[SwapOrderLeg(
                stock_code="600519.SH",
                stock_name="贵州茅台",
                direction="buy",
                quantity=1000,
                price_type="market",
            )],
        )

    if name == "SwapOrderIdOutput":
        m = SWAP_ID_RE.search(text)
        return output_cls(order_id=m.group(0) if m else "H-20260304-ABCD12345678")

    if name == "SwapOrderIdListOutput":
        ids = SWAP_ID_RE.findall(text)
        return output_cls(order_ids=ids or ["H-20260304-ABCD12345678"])

    # ===== Option =====
    if name == "OptionExtractOutput":
        from app.subgraphs.option_models import OptionOrderLeg
        intent = _option_intent_from_text(text)
        return output_cls(
            type=intent,
            operate=intent,
            order_list=[OptionOrderLeg(
                stock_code="600519.SH",
                stock_name="贵州茅台",
                option_type="欧式看涨",
                tenor="1M",
            )] if intent in ("place_order", "new_inquiry") else [],
        )

    if name == "OptionIntentOutput":
        intent = _option_intent_from_text(text)
        return output_cls(type=intent, operate=intent)

    if name == "OptionParamLimit":
        return output_cls(
            stock_count=1, strike_count=1, tenor_count=1, combo_count=1,
            exceeded=False, reason="",
        )

    # ===== Close =====
    if name == "CloseIntentOutput":
        return output_cls(type=_close_intent_from_text(text))

    if name == "CloseHoldingQueryOutput":
        return output_cls()

    if name == "ClosePlaceOrderOutput":
        from app.subgraphs.close_models import ClosePlaceOrderLeg
        m = CLOSE_ID_RE.search(text) or CONTRACT_RE.search(text)
        order_id = m.group(0) if m else "OPTG-20260304-0001"
        return output_cls(
            close_order_list=[ClosePlaceOrderLeg(
                internal_trade_id=order_id, price_type="market", full_close=True,
            )],
        )

    if name == "CloseOrderNoListOutput":
        ids = CLOSE_ID_RE.findall(text)
        return output_cls(order_no_list=ids or ["CO-20260304-ABCD1234"])

    # 兜底：返回类的默认实例
    try:
        return output_cls()
    except Exception:
        return MagicMock()


# ============================================================
# 3. 构造测试用 backend（仅用于本地管道连通性验证，不替代真实后端）
# ============================================================
def _make_mock_backend():
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.swap_operate = AsyncMock(return_value={"code": 0, "result": "[mock] swap ok"})
    mock_client.option_operate = AsyncMock(return_value={"code": 0, "result": "[mock] option ok"})
    mock_client.financial_orders_operate = AsyncMock(return_value={"code": 0, "result": "[mock] close ok"})
    mock_client.query_close_orders = AsyncMock(return_value=[])
    mock_client.fast_query = AsyncMock(return_value={"code": 0, "result": "[mock] fast query ok"})
    mock_client.bot_name_list = AsyncMock(return_value=["机器人A"])
    mock_client.conversation_orders = AsyncMock(return_value=[])
    mock_client.counterparty_list = AsyncMock(return_value=[{"id": 1, "shortName": "对手A"}])
    mock_client.set_intent = AsyncMock()
    return mock_client


# ============================================================
# 4. 标的查询（本地词典，仅用于管道连通性验证）
# ============================================================
TICKER_DICT = {
    "茅台": ("600519.SH", "贵州茅台"),
    "贵州茅台": ("600519.SH", "贵州茅台"),
    "五粮液": ("000858.SZ", "五粮液"),
    "招商银行": ("600036.SH", "招商银行"),
    "工商银行": ("601398.SH", "工商银行"),
    "腾讯": ("0700.HK", "腾讯控股"),
    "腾讯控股": ("0700.HK", "腾讯控股"),
    "阿里巴巴": ("9988.HK", "阿里巴巴-W"),
    "阿里": ("9988.HK", "阿里巴巴-W"),
    "特斯拉": ("TSLA.O", "特斯拉"),
    "TSLA": ("TSLA.O", "特斯拉"),
    "苹果": ("AAPL.O", "苹果"),
    "AAPL": ("AAPL.O", "苹果"),
    "纳指": ("NDX.GI", "纳斯达克100"),
    "纳斯达克100": ("NDX.GI", "纳斯达克100"),
    "沪金": ("AU2606.SHF", "沪金主力"),
}


def _make_securities_mock():
    """返回一个 MagicMock 对象，其 ainvoke 是 plain async function。
    避免 AsyncMock + 异步 side_effect 的兼容性陷阱。"""
    async def fake_ainvoke(payload):
        items = (payload or {}).get("keyword_items") or []
        out: list[dict] = []
        seen: set[str] = set()
        for item in items:
            kw = (item or {}).get("keyword", "")
            for dict_kw, (wc, name) in TICKER_DICT.items():
                if kw and (kw in dict_kw or dict_kw in kw or kw == wc):
                    if wc in seen:
                        continue
                    seen.add(wc)
                    out.append({
                        "windCode": wc, "insShtDesc": name, "insLngDesc": name,
                        "insFamily": "EQUITY" if wc != "AU2606.SHF" else "FUTURE",
                        "currency": "CNY", "exchange": wc.split(".")[-1],
                        "from_goats": True,
                    })
                    break
        return out

    mock_tool = MagicMock()
    mock_tool.ainvoke = fake_ainvoke
    return mock_tool


# ============================================================
# 5. Demo runner
# ============================================================
async def run_one_case(graph, case: dict, *, verbose: bool) -> dict:
    """跑一条 golden case，返回结果摘要。"""
    from app.state import make_initial_state

    raw_content = case["raw_content"]
    expected = case.get("expected", {})

    state = make_initial_state({
        "conversation_id": f"demo-{case['id']}",
        "message_id": f"m-{case['id']}",
        "room_id": "demo-room",
        "user_id": "demo-user",
        "guid": "",
        "raw_content": raw_content,
        "quote_content": case.get("quote_content"),
        "quote_appinfo": case.get("quote_appinfo"),
        "attachments": case.get("attachments", []),
    })
    state["at_bot"] = True
    config = {"configurable": {"thread_id": f"demo-{case['id']}"}, "recursion_limit": 30}

    start = time.monotonic()
    try:
        result = await graph.ainvoke(state, config=config)
        latency = int((time.monotonic() - start) * 1000)
        product = result.get("product_type")
        intent = result.get("intent")
        api_code = result.get("api_code")
        error = result.get("error")
        trace = [t.get("node") for t in result.get("trace", [])]
    except Exception as e:
        latency = int((time.monotonic() - start) * 1000)
        return {
            "id": case["id"],
            "category": case.get("category", "?"),
            "passed": False,
            "reason": f"crash: {type(e).__name__}: {e}",
            "latency_ms": latency,
        }

    # 判定
    expected_product = expected.get("product_type")
    expected_intent = expected.get("intent")

    diffs = []
    if expected_product is not None and product != expected_product:
        diffs.append(f"product={product} (期望={expected_product})")
    if expected_intent is not None and intent != expected_intent:
        diffs.append(f"intent={intent} (期望={expected_intent})")

    return {
        "id": case["id"],
        "category": case.get("category", "?"),
        "passed": not diffs,
        "reason": "; ".join(diffs) or "ok",
        "product": product,
        "intent": intent,
        "api_code": api_code,
        "error": error,
        "trace": trace,
        "latency_ms": latency,
    }


async def main(args: argparse.Namespace) -> int:
    _setup_env()

    # 清缓存（避免上次 settings 残留）
    from app.config import get_settings
    get_settings.cache_clear()

    # 加载样本
    cases = [
        json.loads(line) for line in args.sample.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.max_cases:
        cases = cases[: args.max_cases]

    print(f"\n{'=' * 70}")
    print(f"  V1 闭环验证 Demo — {len(cases)} 条 golden case，零外部依赖")
    print(f"{'=' * 70}\n")

    # 设置全局 patch
    smart_llm = SmartLLMMock()
    mock_backend_client = _make_mock_backend()

    def backend_factory(*a, **kw):
        return mock_backend_client

    patches = [
        # LLM
        patch("app.llm.clients.get_qwen_standard", return_value=smart_llm),
        patch("app.llm.clients.get_qwen_thinking", return_value=smart_llm),
        # Backend client（patch 所有 import 点）
        patch("app.tools.otc_backend.OtcBackendClient", side_effect=backend_factory),
        patch("app.subgraphs.swap.OtcBackendClient", side_effect=backend_factory),
        patch("app.subgraphs.option.OtcBackendClient", side_effect=backend_factory),
        patch("app.subgraphs.close.OtcBackendClient", side_effect=backend_factory),
        # Securities-instrument 接口
        patch("app.subgraphs.ticker.search_securities_instrument", _make_securities_mock()),
    ]
    for p in patches:
        p.start()

    try:
        from langgraph.checkpoint.memory import InMemorySaver

        from app.graph.main import build_main_graph

        graph = build_main_graph(InMemorySaver())

        # 串行跑（in-process 已经很快，不必并发）
        results = []
        for i, case in enumerate(cases, 1):
            r = await run_one_case(graph, case, verbose=args.verbose)
            results.append(r)
            mark = "✓" if r["passed"] else "✗"
            print(f"[{i:03d}/{len(cases)}] {mark} {r['id']:<6} {r['category']:<32} "
                  f"{r['latency_ms']:>5}ms  {r['reason']}")
            if args.verbose and r.get("trace"):
                print(f"               trace: {' → '.join(r['trace'])}")
    finally:
        for p in patches:
            p.stop()

    # 汇总
    passed = sum(1 for r in results if r["passed"])
    failed = len(results) - passed
    avg_lat = sum(r["latency_ms"] for r in results) / max(len(results), 1)

    print(f"\n{'=' * 70}")
    print(f"  结果: {passed}/{len(results)} PASS  ({passed / len(results) * 100:.1f}%)")
    print(f"  平均延迟: {avg_lat:.0f}ms  (in-process，无网络)")
    print(f"{'=' * 70}")

    # 按 product 分组
    by_product = defaultdict(list)
    for r in results:
        # 从 category 推断 product（如 "swap/place_order" → "swap"）
        prod = r["category"].split("/")[0]
        by_product[prod].append(r)
    print("\n  按子图统计：")
    for prod, rs in sorted(by_product.items()):
        p = sum(1 for r in rs if r["passed"])
        print(f"    {prod:<14} {p}/{len(rs)}  ({p / len(rs) * 100:.0f}%)")

    if failed:
        print(f"\n  失败明细：")
        for r in results:
            if not r["passed"]:
                print(f"    [{r['id']}] {r['reason']}")
                if r.get("trace"):
                    print(f"           trace: {' → '.join(r['trace'])}")
                if r.get("error"):
                    print(f"           error: {r['error']}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="V1 闭环验证 demo（无外部依赖）")
    parser.add_argument("--sample", type=Path, default=Path("tests/fixtures/golden.jsonl"))
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--verbose", "-v", action="store_true", help="打印每条 case 的 trace")
    sys.exit(asyncio.run(main(parser.parse_args())))
