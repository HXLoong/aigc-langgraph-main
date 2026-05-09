"""Langfuse 期权链路评估脚本。

用法:
    python scripts/langfuse_eval.py --dry-run --limit 3   # 预览
    python scripts/langfuse_eval.py                        # 全量 98 条
    python scripts/langfuse_eval.py --filter 期权询价       # 只跑询价类

执行流程:
    1. 从 Langfuse Dataset 拉 case
    2. 每条 case 多轮跑 LangGraph（InMemorySaver + mock 后端 + 真实 Qwen）
    3. DeepSeek V4 Pro Judge（thinking 开启）自动打分
    4. 结果写回 Langfuse → UI 查看
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

# 加载 .env
_DOTENV = Path(__file__).resolve().parent.parent / ".env"
if _DOTENV.exists():
    for line in _DOTENV.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if k and not os.environ.get(k):
            os.environ[k] = v

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from langgraph.checkpoint.memory import InMemorySaver

from app.graphs.main_graph import build_main_graph
from app.state import ProductType, WechatInput, make_initial_state

DATASET_NAME = "otc-option-golden"


# ============================================================
# Mock 后端
# ============================================================

# 防重复提交追踪：{(item_id, type): ...}
_DUP_TRACKER: set[tuple] = set()


# OPT-NOTEXIST 各 case 的剩余名义本金（万元单位）

def _dynamic_financial_orders(**kwargs) -> dict:
    """根据输入参数动态返回后端响应，模拟真实业务校验。"""
    type_ = kwargs.get("type", "")

    # 平仓意图 → 返回持仓/操作结果
    if type_ == "close_order_query":
        return {
            "code": 0,
            "result": (
                "-----场外期权持仓详情-----\n"
                "序号：1\n"
                "单号：CO-20260506-DEAF117C\n"
                "合约编号：OPT-LYAFT20260001\n"
                "期权类型：欧式看涨\n"
                "标的信息：600519.SH\n"
                "标的名称：贵州茅台\n"
                "名义本金：1000万元\n"
                "可平仓名义本金：1000万元\n\n"
                "序号：2\n"
                "单号：CO-20260506-AB345678\n"
                "合约编号：OPTG-20260002\n"
                "期权类型：欧式看跌\n"
                "标的信息：601318.SH\n"
                "标的名称：中国平安\n"
                "名义本金：500万元\n"
                "可平仓名义本金：300万元"
            ),
        }
    if type_ and type_.startswith("close_order_"):
        return {"code": 0, "result": f"平仓操作 {type_} 已受理，单号 CO-20260509-TEST001"}

    return {
        "code": 0,
        "result": (
            "-----场外期权询价详情-----\n"
            "单号：Q-20260509-TEST001\n"
            "期权类型：欧式看涨\n"
            "标的代码：600519.SH\n"
            "标的名称：贵州茅台\n"
            "方向：看涨\n"
            "期限：1M\n"
            "行权价格：80%\n"
            "期权费率：6.9%\n"
            "名义本金：待补充\n"
            "建仓指令：待补充\n"
            "当前额度：0万元\n"
            "交易对手：待补充\n\n"
            "如需下单，请引用本消息补充【交易对手】【名义本金】【建仓指令】。\n"
            "本群可选交易对手列表：\n"
            "A.交易对手A\n"
            "B.交易对手B\n"
            "例如：A，200w 市价下单"
        ),
    }

def _dynamic_query_close_orders(**kwargs) -> list[dict[str, Any]]:
    """根据 order_ids / contract_codes 动态返回持仓明细。"""
    order_ids = set(kwargs.get("order_ids", []) or [])
    contract_codes = set(kwargs.get("contract_codes", []) or [])

    all_positions: list[dict[str, Any]] = [
        {
            "id": 1, "contractCode": "OPT-LYAFT20260001",
            "orderId": "CO-20260506-DEAF117C",
            "availableNotional": 10_000_000, "notional": 10_000_000,
            "underlyingCode": "000155.SZ", "underlyingName": "川能动力",
            "optionType": "欧式看涨", "createTime": "2026-05-06 15:21",
        },
        {
            "id": 2, "contractCode": "OPT-SZZSCF20260004",
            "orderId": "CO-20260506-7C8DEF06",
            "availableNotional": 10_000_000, "notional": 10_000_000,
            "underlyingCode": "002382.SZ", "underlyingName": "蓝帆医疗",
            "optionType": "雪球", "createTime": "2026-05-06 15:05",
        },
    ]

    # 无过滤条件时返回全部持仓（用户说"序号1"不带 CO-/OPT- 格式）
    if not order_ids and not contract_codes:
        return all_positions

    result = []
    for pos in all_positions:
        if pos["orderId"] in order_ids or pos["contractCode"] in contract_codes:
            result.append(pos)
    return result



def _build_close_place_reply(order_list: list[dict], raw_content: str) -> dict:
    """根据 LLM 提取的 order_list 动态生成平仓确认回复。"""
    all_positions = [
        {
            "id": 1, "contractCode": "OPT-LYAFT20260001",
            "orderId": "CO-20260506-DEAF117C",
            "availableNotional": 10_000_000, "notional": 10_000_000,
            "underlyingCode": "000155.SZ", "underlyingName": "川能动力",
            "optionType": "欧式看涨", "createTime": "2026-05-06 15:21",
        },
        {
            "id": 2, "contractCode": "OPT-SZZSCF20260004",
            "orderId": "CO-20260506-7C8DEF06",
            "availableNotional": 10_000_000, "notional": 10_000_000,
            "underlyingCode": "002382.SZ", "underlyingName": "蓝帆医疗",
            "optionType": "雪球", "createTime": "2026-05-06 15:05",
        },
    ]
    pos_map = {p["orderId"]: p for p in all_positions}
    pos_map.update({str(p["id"]): p for p in all_positions})

    def _fmt_notional(v):
        w = int(v) / 10000
        return f"{int(w):,}" if w == int(w) else f"{w:,.1f}"

    lines = ["以下平仓申请，请核对详情后确认："]
    needs_pov_ratio = False

    for order in order_list:
        oid = str(order.get("orderId", ""))
        pos = pos_map.get(oid)
        if pos is None:
            continue
        price_type = (order.get("closeOrderType") or "").strip()
        pov_ratio = order.get("closeOrderPovRatio")
        notional_delta = order.get("closeOrderNotionalDelta", "")

        lines.append("-----场外期权平仓详情-----")
        lines.append(f"序号：{pos['id']}")
        lines.append(f"合约编号：{pos['contractCode']}")
        lines.append(f"单号：{pos['orderId']}")
        lines.append(f"申请时间：{pos.get('createTime', '')}")
        lines.append(f"期权类型：{pos['optionType']}")
        lines.append(f"标的代码：{pos['underlyingCode']}")
        lines.append(f"标的名称：{pos['underlyingName']}")
        lines.append("交易方向：卖出")
        if notional_delta:
            lines.append(f"平仓名义本金：{_fmt_notional(notional_delta)}")
        lines.append(f"平仓价格方式：{price_type}")
        if price_type == "POV":
            if pov_ratio is not None:
                lines.append(f"POV比例：{pov_ratio}%")
            else:
                lines.append("POV比例：【待补充】")
                needs_pov_ratio = True
        lines.append("")

    if needs_pov_ratio:
        lines.append("【待补全必填项：POV比例】示例：25%")
        lines.append(" 请引用本消息补充【POV比例】")
    else:
        lines.append("若要对以上订单执行平仓操作，请引用本消息回复【确认平仓】")

    return {"code": 0, "result": "\n".join(lines)}

def _make_mock_backend():
    """构造 mock OtcBackendClient。"""
    mock = AsyncMock()
    mock.__aenter__.return_value = mock
    mock.__aexit__.return_value = None

    mock.bot_name_list = AsyncMock(return_value=["机器人A", "机器人B"])
    mock.conversation_orders = AsyncMock(return_value=[
        {
            "orderId": "Q-20260509-TEST001",
            "windCode": "600519.SH",
            "insShtDesc": "贵州茅台",
            "orderType": "欧式看涨",
            "notional": 2000000,
            "status": "已提交",
        },
        {
            "orderId": "CO-20260506-DEAF117C",
            "contractCode": "OPT-LYAFT20260001",
            "windCode": "000155.SZ",
            "insShtDesc": "川能动力",
            "orderType": "欧式看涨",
            "notional": 10000000,
            "status": "已成交",
        },
    ])
    mock.counterparty_list = AsyncMock(return_value=[
        {"id": 1, "shortName": "交易对手A"},
        {"id": 2, "shortName": "交易对手B"},
    ])
    mock.financial_orders_operate = AsyncMock(side_effect=_dynamic_financial_orders)
    mock.swap_operate = AsyncMock(return_value={"code": 0, "result": "互换操作成功"})
    mock.option_operate = AsyncMock(return_value={"code": 0, "result": "期权操作成功"})
    mock.query_close_orders = AsyncMock(return_value=[])
    mock.set_intent = AsyncMock()

    return mock


# ============================================================
# Task 函数（Langfuse run_experiment 的 task）
# ============================================================
async def _run_graph_once(
    graph, config: dict, raw_content: str, has_mention: bool,
    turn: int, quote_content: str | None = None,
    user_id: str = "eval-user",
) -> dict:
    """跑单轮 LangGraph，返回 bot 输出。"""
    wx = WechatInput(
        conversation_id=config["configurable"]["thread_id"],
        message_id=f"m-{config['configurable']['thread_id']}-t{turn}",
        room_id="eval-room",
        user_id=user_id,
        guid="",
        raw_content=raw_content,
        quote_content=quote_content,
        quote_appinfo=None,
    )
    state = make_initial_state(wx)
    state["at_bot"] = has_mention

    result = await graph.ainvoke(state, config=config)
    return {
        "product_type": result.get("product_type", "unknown"),
        "intent": result.get("intent"),
        "reply_text": result.get("reply_text", ""),
        "error": result.get("error"),
        "api_code": result.get("api_code"),
        "api_result": str(result.get("api_result", ""))[:500],
    }


async def run_langgraph_pipeline(*, item, **kwargs):
    """Langfuse task 函数：解析 item → 跑 LangGraph → 返回结果。"""
    graph = kwargs.get("_graph")
    mock_factory = kwargs.get("_mock_factory")
    user_id = kwargs.get("_user_id", "eval-user")

    inp = item.input if isinstance(item.input, dict) else json.loads(item.input)
    turns_data = inp.get("turns", [])
    config = {"configurable": {"thread_id": f"eval-{item.id}"}}

    mock = mock_factory() if mock_factory else _make_mock_backend()
    patches = [
        patch("app.tools.otc_backend.OtcBackendClient", return_value=mock),
        patch("app.subgraphs.close.OtcBackendClient", return_value=mock),
        patch("app.subgraphs.option.OtcBackendClient", return_value=mock),
        patch("app.subgraphs.swap.OtcBackendClient", return_value=mock),
    ]
    for p in patches:
        p.start()

    try:
        reply_text = ""
        last_intent = ""
        last_product = ""
        for turn_data in turns_data:
            raw_content = turn_data.get("raw_content", "")
            has_mention = turn_data.get("has_mention", False)
            quote_content = turn_data.get("quote_desc", "")
            r = await _run_graph_once(
                graph, config, raw_content, has_mention,
                turn_data.get("turn", 1), quote_content, user_id,
            )
            reply_text = r["reply_text"]
            last_intent = r["intent"] or ""
            last_product = r["product_type"]
        return {
            "product_type": last_product,
            "intent": last_intent,
            "reply_text": reply_text,
        }
    finally:
        for p in patches:
            p.stop()


def _extract_json(text: str) -> dict | None:
    """从 Judge LLM 输出中提取 JSON 对象。"""
    import re as _re3

    # 策略 1：直接解析
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # 策略 2：提取 ```json ... ``` 代码块
    m = _re3.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, _re3.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    # 策略 3：提取第一个 { 到最后一个 } 之间的 JSON
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except (json.JSONDecodeError, ValueError):
            pass

    return None




def judge_by_deepseek(*, output: dict, expected_output: str, metadata: dict | None = None,
                       **kwargs) -> dict:
    """DeepSeek V4 Pro Judge（Anthropic 兼容端点，effort=max）。"""
    from anthropic import Anthropic

    actual = output.get("reply_text", "")
    exp = expected_output or ""

    user_prompt = f"""## 测试用例
{(metadata or {}).get('overview', '') or '(空)'}

## 机器人实际回复
{actual}

## 期望回复
{exp}

请评分："""

    client = Anthropic()

    resp = client.messages.create(
        model=os.environ.get("ANTHROPIC_MODEL", "deepseek-v4-pro[1m]"),
        max_tokens=1024,
        system=JUDGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        thinking={"type": "enabled", "budget_tokens": 4096},
    )

    # Thinking 模式下 content 混有 thinking block(s) 和 text block(s)。
    # 取最后一个 text block（thinking 完成后的最终输出），而非第一个（可能为空）。
    text = ""
    for block in resp.content:
        if hasattr(block, "text"):
            text = block.text
    text = (text or "").strip()

    # DEBUG: print raw judge output
    import sys as _sys
    print(f"  [judge-debug] raw_text({len(text)} chars): {text[:200]}", file=_sys.stderr)

    result = _extract_json(text)
    if result is None:
        # Fallback: regex extract from malformed JSON
        import re as _re2
        score = 0.0
        m = _re2.search(r'"score"\s*:\s*([\d.]+)', text)
        if m:
            score = float(m.group(1))
        m = _re2.search(r'"pass"\s*:\s*(true|false)', text, _re2.IGNORECASE)
        passed = m.group(1).lower() == "true" if m else (score >= 0.5)
        m = _re2.search(r'"reason"\s*:\s*"([^"]*)"', text)
        reason = m.group(1) if m else text[:200]
        result = {"pass": passed, "score": score, "reason": reason}

    from langfuse.experiment import Evaluation

    return Evaluation(
        name="otc-option-judge",
        value=float(result.get("score", 0)),
        comment=result.get("reason", ""),
        metadata={"pass": result.get("pass", False)},
    )


# ============================================================
# 主流程
# ============================================================
async def run_eval(
    dataset_name: str,
    filter_func: str | None,
    ids: list[str] | None,
    max_concurrency: int,
    limit: int | None,
    dry_run: bool,
):
    from langfuse import Langfuse

    lf = Langfuse()

    # 1. 拉 dataset
    print(f"加载 Langfuse Dataset: {dataset_name}")
    items = list(lf.get_dataset(dataset_name).items)
    print(f"共 {len(items)} 条")

    # 2. 按 ID 指定
    if ids:
        items = [i for i in items if i.id in ids]
        print(f"按 id={ids} 过滤: {len(items)} 条")

