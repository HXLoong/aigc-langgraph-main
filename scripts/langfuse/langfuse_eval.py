"""期权链路评估。跑 LangGraph，DeepSeek v4 flash Judge 打分。

OTC_API_BASE_URL 从 .env 读取，指向真实后端地址。
前提: 对应的后端服务必须已启动
用法: uv run python scripts/langfuse/langfuse_eval.py --ids opt-001 --concurrency 1
"""
# Imports below intentionally follow dotenv/bootstrap setup.
# ruff: noqa: E402, I001

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import secrets
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DOTENV = PROJECT_ROOT / ".env"
if _DOTENV.exists():
    for line in _DOTENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        # 去掉行内注释（如 "true  # 注释" → "true"）
        v = v.split("#")[0].strip()
        if k:
            os.environ[k] = v

# 清除 shell 中可能干扰 .env 配置的变量（如 Claude Code 设置的 ANTHROPIC_AUTH_TOKEN）
for _k in ("ANTHROPIC_AUTH_TOKEN",):
    os.environ.pop(_k, None)

# OTC_API_BASE_URL 由上方 .env 加载提供（mock 或真实 GOATS），不再强制覆盖
# Langfuse API 不走代理
os.environ["NO_PROXY"] = os.environ.get("NO_PROXY", "") + ",cloud.langfuse.com"

sys.path.insert(0, str(PROJECT_ROOT))

from langgraph.checkpoint.memory import InMemorySaver
from app.graph.main import build_main_graph
from app.prompts import load_prompt
from app.api.turn_state import inputs_to_state
from harness import intent_runner
from harness.evaluators import instrument_match, intent_match, rejection_match
from harness.golden import (
    GoldenCase,
    build_overview,
    dataset_expected,
    filter_by_category,
    filter_by_ids,
    load_golden,
    select_runnable,
)
from harness.multi_turn import early_stop_kind, quote_for_turn
from harness.scenario_inputs import resolve_order_reference
from app.tools.ticker_client import TickerClientHttpx

DATASET_NAME = "otc-option-golden"

#: 套件：intent（意图集，只跑意图子链、只调 LLM，确定性 intent_match 评分，不跑 Judge）
#: / business（业务集，真后端 + 卡片文本断言 + Judge）
SUITES = ("intent", "business")
DEFAULT_SUITE = "business"
INTENT_DIR_NAME = "intent"


def resolve_suite(
    suite: str | None, local_paths: list[Path] | None, dataset_name: str | None
) -> str:
    """显式 --suite 优先；--local 路径或 intent_ / intent- Dataset 名判断套件。"""
    if suite:
        return suite
    if local_paths and any(INTENT_DIR_NAME in path.parts for path in local_paths):
        return "intent"
    if dataset_name and dataset_name.startswith(("intent_", "intent-")):
        return "intent"
    return DEFAULT_SUITE


def judge_enabled(suite: str, *, no_judge: bool) -> bool:
    """意图集永远不跑 LLM Judge：它只有 product_type / intent 两个确定性断言。"""
    return suite != "intent" and not no_judge


def build_expected_text(case: GoldenCase) -> str:
    """A 方言没有 expected.output：把逐轮路由期望 + 文本断言拼成 Judge 可读的期望。"""
    lines: list[str] = []
    for index, turn in enumerate(case.turns, 1):
        lines.append(f"第{index}轮 send_text={turn.send_text}")
        route = ", ".join(
            f"{key}={turn.expected[key]}"
            for key in ("product_type", "intent")
            if turn.expected.get(key)
        )
        if route:
            lines.append(f"  期望路由: {route}")
        for label, values in (
            ("必含文本", turn.response_contains),
            ("任一文本", turn.response_contains_any),
            ("禁止文本", turn.response_not_contains),
        ):
            if values:
                lines.append(f"  {label}: {'; '.join(values)}")
    return "\n".join(lines)


def _fmt_trace(trace_entries) -> str:
    """把 TraceEntry list 格式化成 node[decision] → ... 字符串。"""
    parts = []
    for e in trace_entries or []:
        if hasattr(e, "node"):
            s = e.node
            if getattr(e, "decision", None):
                s += f"[{e.decision}]"
        elif isinstance(e, dict):
            s = e.get("node", "?")
            if e.get("decision"):
                s += f"[{e['decision']}]"
        else:
            s = str(e)
        parts.append(s)
    return " → ".join(parts) if parts else "(无 trace)"


# ── Task ──
async def _run_graph_once(
    graph, config, raw_content, has_mention=True, turn=1, quote_content=None,
    suite: str = DEFAULT_SUITE,
):
    # 与生产 routes 同一条入口（ADR 0024 D2）：Dify 形态 inputs → inputs_to_state
    inputs = {
        "rawContent": raw_content,
        "quoteContent": quote_content,
        "messageId": secrets.randbelow(900_000_000_000_000) + 100_000_000_000_000,
        "roomId": os.environ.get("EVAL_ROOM_ID", "eval-room"),
        "userId": os.environ.get("EVAL_USER_ID", "eval-user"),
        "guid": "",
        "at_bot": has_mention,
    }
    if suite == "intent":
        # CI 的 mock backend 提供与生产 Java 输入同形的授权参考上下文。
        client = TickerClientHttpx()
        for product, field in (("OPTION", "option_counterparties"), ("TRS", "swap_counterparties")):
            rows = await client.list_counterparty(
                inputs["roomId"], user_id=inputs["userId"], business_type=product,
                message_id=inputs["messageId"],
            )
            inputs[field] = json.dumps(rows, ensure_ascii=False)
    state = inputs_to_state(inputs)
    state["conversation_id"] = config["configurable"]["thread_id"]
    result = await graph.ainvoke(state, config=config)
    return result


#: 多轮 case 同 conversationId 紧密调用后端会触发 dedup（返回"正在处理,请勿重复提交"）。
#: 生产场景真人输入间隔大，eval 这里加 sleep 模拟真实节奏避开 dedup（仅 eval 行为，不动业务代码）。
_TURN_INTERVAL_SECONDS = float(os.environ.get("EVAL_TURN_INTERVAL", "1.0"))

#: PASS 判定阈值（默认 0.7，覆盖"近 PASS"——意图路由+主参数正确,仅个别非关键字段漏）
#: 改为环境变量可调:EVAL_PASS_THRESHOLD=0.99 严格 / 0.7 宽松（默认）/ 0.5 极宽松
_PASS_THRESHOLD = float(os.environ.get("EVAL_PASS_THRESHOLD", "0.7"))

#: 图片 / Excel case 标识——这些 case 在 golden.jsonl 里声明"用户发送图片"等但
#: 实际没图片/Excel 数据,无法真测。默认跳过以避免污染分数。
#: EVAL_SKIP_IMAGE_CASES=0 可跑(返回固定 fail)
_SKIP_IMAGE_CASES = os.environ.get("EVAL_SKIP_IMAGE_CASES", "1") == "1"
_IMAGE_MARKERS = ("用户发送图片", "发送图片", "图片识别", ".xlsx", ".xls", "截图")


def _is_image_case(case: GoldenCase) -> bool:
    """case 是否依赖图片/Excel 数据（实际 golden 里没数据）。"""
    full_text = " ".join(turn.send_text for turn in case.turns)
    return any(m in full_text for m in _IMAGE_MARKERS)


def _langfuse_enabled() -> bool:
    """langfuse v4 CallbackHandler 只读 os.environ；双 key 齐才算启用。"""
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))


def _graph_callbacks() -> list:
    """图级全局注入已删除（ADR 0024 D5）：eval 自己把 LangFuse handler 放进 config。"""
    if not _langfuse_enabled():
        return []
    try:
        from app.observability.tracing import create_callback_handler

        return [create_callback_handler()]
    except Exception as exc:  # noqa: BLE001
        print(f"LangFuse CallbackHandler 不可用，per-node span 缺失：{exc}")
        return []


#: 一轮输入里 runner 认识的键（Langfuse Dataset 的 send_text + sub_scenes 结构）
_TURN_INPUT_KEYS = frozenset(
    {"send_text", "at_bot", "quote_previous", "quote_desc", "quote_content", "history", "prev_product_type"}
)


def _item_turns(item) -> list[dict[str, Any]]:
    """本地 _LocalItem（turns[]）与 Langfuse Dataset item（首轮 + sub_scenes[]）统一成逐轮列表。"""
    inp = item.input if isinstance(item.input, dict) else json.loads(item.input)
    turns_data = inp.get("turns")
    if isinstance(turns_data, list):
        return turns_data
    first_turn = {key: value for key, value in inp.items() if key in _TURN_INPUT_KEYS}
    sub_scenes = inp.get("sub_scenes", [])
    turns = [first_turn]
    if isinstance(sub_scenes, list):
        turns.extend(scene for scene in sub_scenes if isinstance(scene, dict))
    return turns


def _simplify_place_params(rs: dict[str, Any]) -> dict[str, Any] | None:
    """place_params 简化（顶层 expected_action + orderList 字段，去掉 None 减少噪音）。"""
    pp = rs.get("place_params") or {}
    if not pp:
        return None
    orders_simple = [
        {
            k: v
            for k, v in (
                o if isinstance(o, dict) else (o.model_dump() if hasattr(o, "model_dump") else {})
            ).items()
            if v is not None
        }
        for o in pp.get("orderList", [])
    ]
    return {"action": rs.get("expected_action"), "orderList": orders_simple}


def _simplify_error(err: Any) -> dict[str, Any] | None:
    if err is None:
        return None
    err_dict = err.model_dump() if hasattr(err, "model_dump") else err
    if isinstance(err_dict, dict):
        return {
            "node": err_dict.get("node"),
            "type": err_dict.get("type"),
            "message": (err_dict.get("message") or "")[:200],
        }
    return {"message": str(err)[:200]}


def _expects_rejection(item) -> bool:
    """拒绝验收要检查面向用户的拒绝回复与“未提交后端”，只有主图（render / fallback）能给出。"""
    flag = getattr(item, "has_rejections", None)
    if flag is not None:
        return bool(flag)
    expected = getattr(item, "expected_output", None)
    text = expected if isinstance(expected, str) else json.dumps(expected or {}, ensure_ascii=False)
    return '"rejection"' in text


def _needs_instrument_extraction(item) -> bool:
    """期望里有 instruments 才追加 swap 参数抽取（标的原文评估读 place_params）。"""
    flag = getattr(item, "has_instruments", None)
    if flag is not None:
        return bool(flag)
    expected = getattr(item, "expected_output", None)
    text = expected if isinstance(expected, str) else json.dumps(expected or {}, ensure_ascii=False)
    return '"instruments"' in text


async def run_intent_pipeline(*, item, **kwargs):
    """意图集：只跑意图子链（harness/intent_runner.py），逐轮独立 + 冻结上下文，不碰后端。

    与业务集 pipeline 同一输出结构（turns[i].product_type / intent / place_params / error），
    评估器无需区分；不早停——每轮都有自己的期望，前一轮错不影响后一轮的输入。
    """
    graph = intent_runner.build_intent_graph(swap_extraction=_needs_instrument_extraction(item))
    conversation_id = str(uuid.uuid4())
    # 与生产 routes._build_run_config 同一契约；意图子链不挂 checkpointer，thread_id 只作关联
    config = {
        "configurable": {"thread_id": conversation_id},
        "metadata": {
            "trace_id": uuid.uuid4().hex,
            "langfuse_session_id": conversation_id,
            "langfuse_tags": ["eval", "intent"],
        },
        "callbacks": _graph_callbacks(),
    }
    results = []
    for index, turn in enumerate(_item_turns(item), 1):
        quote = turn.get("quote_content") or ""
        try:
            rs = await intent_runner.run_turn(graph, turn, conversation_id=conversation_id, config=config)
            tr = {
                "product_type": rs.get("product_type", "unknown"),
                "intent": rs.get("intent"),
                "reply_text": "",
                "place_params": _simplify_place_params(rs),
                "error": _simplify_error(rs.get("error")),
                "trace": _fmt_trace(rs.get("trace")),
            }
        except Exception as e:
            tr = {
                "product_type": "error",
                "intent": None,
                "reply_text": "",
                "place_params": None,
                "error": {"message": str(e)[:200]},
                "trace": "",
            }
        tr.update(
            api_result=None, api_code=None, tickers=[], quote_passed=quote[:120],
            turn=index, raw_content=turn.get("send_text", ""),
        )
        results.append(tr)
    trace_log = "\n".join(
        f"[第{r['turn']}轮] input={r['raw_content'][:40]!r}"
        f" | route={r['product_type']}/{r['intent'] or '?'}"
        f" | quote={len(r['quote_passed'])}c | trace: {r['trace']}"
        + (f" | ERROR: {r['error']}" if r.get("error") else "")
        for r in results
    )
    return {"reply_text": "", "turns": results, "trace_log": trace_log, "mode": "intent_chain"}


async def run_langgraph_pipeline(*, item, suite: str = DEFAULT_SUITE, **kwargs):
    turns_data = _item_turns(item)
    # 意图集两种模式并存（harness/intent_context.py）：冻结用例只跑意图子链；仍需上一轮
    # 真实回复的回放用例、以及要验收用户可见拒绝回复的用例，走下面的主图 + mock_api
    if (
        suite == "intent"
        and not intent_runner.requires_replay(turns_data)
        and not _expects_rejection(item)
    ):
        return await run_intent_pipeline(item=item)
    cp = InMemorySaver()
    graph = build_main_graph(cp)
    conversation_id = str(uuid.uuid4())
    # 与生产 routes._build_run_config 同一契约：thread + session + 审计 trace_id
    config = {
        "configurable": {"thread_id": conversation_id},
        "metadata": {
            "trace_id": uuid.uuid4().hex,
            "langfuse_session_id": conversation_id,
            "langfuse_tags": ["eval", suite],
        },
        "callbacks": _graph_callbacks(),
    }
    results = []
    failure: dict | None = None
    for t in turns_data:
        # 多轮之间加 sleep 避开后端 dedup（仅对第 2 轮起生效）
        if results and _TURN_INTERVAL_SECONDS > 0:
            await asyncio.sleep(_TURN_INTERVAL_SECONDS)
        quote = (
            quote_for_turn(
                len(results),
                t.get("quote_previous"),
                [r.get("reply_text") or "" for r in results],
            )
            or None
        )
        raw_content = t.get("send_text", "")
        try:
            raw_content = resolve_order_reference(
                raw_content, results[-1].get("reply_text", "") if results else "",
            )
            rs = await _run_graph_once(
                graph,
                config,
                raw_content=raw_content,
                has_mention=bool(t.get("at_bot", not results)),
                turn=len(results) + 1,
                quote_content=quote,
                suite=suite,
            )
            # tickers 简化（保留 windCode + 中文名 + from_goats）
            tickers_raw = rs.get("tickers") or []
            tickers_simple = []
            for tk in tickers_raw:
                if hasattr(tk, "wind_code"):
                    tickers_simple.append(
                        {
                            "wind": tk.wind_code,
                            "desc": getattr(tk, "ins_sht_desc", None),
                            "goats": getattr(tk, "from_goats", None),
                        }
                    )
                elif isinstance(tk, dict):
                    tickers_simple.append(
                        {
                            "wind": tk.get("windCode"),
                            "desc": tk.get("insShtDesc"),
                            "goats": tk.get("from_goats"),
                        }
                    )

            place_simple = _simplify_place_params(rs)
            err_simple = _simplify_error(rs.get("error"))

            tr = {
                "product_type": rs.get("product_type", "unknown"),
                "intent": rs.get("intent"),
                "reply_text": rs.get("reply_text", ""),
                "api_result": rs.get("api_result"),
                "api_code": rs.get("api_code"),
                "tickers": tickers_simple,
                "place_params": place_simple,
                "error": err_simple,
                "trace": _fmt_trace(rs.get("trace")),
                "quote_passed": (quote or "")[:120],  # 实际传入的引用内容预览
            }
        except Exception as e:
            tr = {
                "product_type": "error",
                "intent": None,
                "reply_text": "",
                "api_result": None,
                "api_code": None,
                "tickers": [],
                "place_params": None,
                "error": {"message": str(e)[:200]},
                "trace": "",
                "quote_passed": (quote or "")[:120],
            }
        tr["turn"] = len(results) + 1
        tr["raw_content"] = raw_content
        results.append(tr)

        api_code = tr.get("api_code")
        kind = early_stop_kind(tr.get("error") is not None, api_code)
        if kind is not None:
            failure = {
                "turn": tr["turn"],
                "kind": kind,
                "api_code": api_code,
                "error": tr.get("error"),
                "reply_text": tr.get("reply_text", ""),
            }
            break
    lines = []
    for r in results:
        line = f"[第{r['turn']}轮] 机器人回复: {r['reply_text'] or '(无回复)'}"
        if r.get("error"):
            line += f" [错误: {r['error']}]"
        lines.append(line)
    # trace_log 单独存储，方便 LangFuse 查看（不影响 Judge 评分的 reply_text）
    trace_log_lines = []
    for r in results:
        qlen = len(r.get("quote_passed") or "")
        qprev = (r.get("quote_passed") or "")[:60]
        tl = (
            f"[第{r['turn']}轮] input={r.get('raw_content', '')[:40]!r}"
            f" | route={r['product_type']}/{r['intent'] or '?'}"
            f" | quote={qlen}c({qprev!r})"
            f" | trace: {r.get('trace', '')}"
        )
        if r.get("error"):
            tl += f" | ERROR: {r['error']}"
        trace_log_lines.append(tl)
    output = {
        "reply_text": "\n".join(lines),
        "turns": results,
        "trace_log": "\n".join(trace_log_lines),
    }
    if suite == "intent":
        output["mode"] = "main_graph"
    if failure is not None:
        output["failure"] = failure
        output["remaining_turns"] = len(turns_data) - len(results)
    return output


# ── Judge ──
# #159 裁决：judge 提示词纳入 ADR 0003 版本化（app/prompts/judge/option_judge.md），
# 改动走 git PR 留痕；不要在本脚本内改写 judge 正文
JUDGE = load_prompt("judge", "option_judge").system

_JSON_OBJ_RE = re.compile(r'\{[^{}]*"pass"[^{}]*"score"[^{}]*\}', re.DOTALL)


_PASS_KV_RE = re.compile(r'"pass"\s*:\s*(true|false)', re.IGNORECASE)
_SCORE_KV_RE = re.compile(r'"score"\s*:\s*([0-9.]+)')


def _parse_judge_json(text: str) -> dict | None:
    """从 Judge 输出里抠 JSON：优先整体 loads，失败用 regex 抓含 pass+score 的对象。

    最后兜底：如果 JSON 完全坏（含内嵌未转义引号等），直接 regex 取 pass / score 字面值。
    这样即使 reason 字段坏掉也能拿到正确评分（避免 Judge 自己挂导致冤判 0）。
    """
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    m = _JSON_OBJ_RE.search(text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    s, e = text.find("{"), text.rfind("}")
    if 0 <= s < e:
        try:
            return json.loads(text[s : e + 1])
        except Exception:
            pass
    # 兜底：regex 抠 pass / score 字面值（即使 JSON 完全坏掉）
    pass_m = _PASS_KV_RE.search(text)
    score_m = _SCORE_KV_RE.search(text)
    if pass_m and score_m:
        try:
            return {
                "pass": pass_m.group(1).lower() == "true",
                "score": float(score_m.group(1)),
                "reason": f"JSON 坏但 regex 抠到 pass+score: {text[:80]}",
            }
        except Exception:
            pass
    return None


class JudgeScore(BaseModel):
    passed: bool = Field(alias="pass", description="实际回复是否满足该测试的业务预期")
    score: float = Field(ge=0, le=1, description="业务预期满足程度，0 表示失败，1 表示完全满足")
    reason: str = Field(description="评分依据与实际回复的具体差异")


def judge_by_deepseek(*, output, expected_output, metadata=None, **kwargs):
    from anthropic import Anthropic

    provider = os.environ.get("EVAL_JUDGE_PROVIDER", "anthropic")
    if provider not in {"anthropic", "standard"}:
        raise ValueError("EVAL_JUDGE_PROVIDER 必须是 anthropic 或 standard")
    if output.get("failure"):
        from langfuse.experiment import Evaluation

        failure = output["failure"]
        kind = failure.get("kind", "unknown") if isinstance(failure, dict) else "unknown"
        return Evaluation(
            name="otc-option-judge", value=0.0,
            comment=f"业务流程未完成（{kind}），不能由宽松 Judge 计为业务成功",
            metadata={"pass": False, "failure": failure, "provider": "deterministic_precheck"},
        )

    actual = output.get("reply_text", "")
    overview = (metadata or {}).get("overview", "")
    user = f"## 测试用例\n{overview}\n\n## 实际回复\n{actual}\n\n## 期望回复\n{expected_output}\n\n请评分："
    if provider == "standard":
        from langfuse.experiment import Evaluation

        from app.llm.clients import get_qwen_standard

        result = JudgeScore.model_validate(
            get_qwen_standard().with_structured_output(JudgeScore).invoke(
                [("system", JUDGE), ("user", user)],
            ),
        )
        return Evaluation(name="otc-option-judge", value=result.score, comment=result.reason,
                          metadata={"pass": result.passed, "provider": provider})
    client = Anthropic()
    request = {
        "model": os.environ.get("ANTHROPIC_MODEL", "deepseek-v4-flash"),
        "max_tokens": 2048,
        "system": JUDGE,
        "messages": [{"role": "user", "content": user}],
    }
    resp = client.messages.create(**request, thinking={"type": "disabled"})
    texts = []
    for block in resp.content:
        if getattr(block, "type", "") == "text":
            texts.append(block.text)
    text = "".join(texts).strip()
    result = _parse_judge_json(text)
    if not result and getattr(resp, "stop_reason", "") == "max_tokens":
        resp = client.messages.create(**request, thinking={"type": "disabled"})
        text = "".join(
            block.text for block in resp.content if getattr(block, "type", "") == "text"
        ).strip()
        result = _parse_judge_json(text)
    if not result:
        result = {"pass": False, "score": 0.0, "reason": f"JSON解析失败:{text[:100]}"}
    from langfuse.experiment import Evaluation

    return Evaluation(
        name="otc-option-judge",
        value=float(result.get("score", 0)),
        comment=result.get("reason", ""),
        metadata={"pass": result.get("pass", False)},
    )


def reply_check(output: dict[str, Any]):
    """--no-judge 的兜底评分：只检查有没有回复。"""
    from langfuse.experiment import Evaluation

    reply = (output.get("reply_text") or "").strip()
    return Evaluation(
        name="reply-check",
        value=1.0 if reply else 0.0,
        comment="有回复" if reply else "reply_text 为空",
    )


def code_evaluations(item, output: dict[str, Any]) -> list:
    """意图集本地评分：直接跑 harness/evaluators 里的确定性评估器（与 Langfuse Online Rule
    同一份源码），不依赖 Langfuse、Java、GOATS。expected 用 Dataset 同款 categories 结构。"""
    from langfuse.experiment import Evaluation

    ctx = SimpleNamespace(
        experiment=SimpleNamespace(item_expected_output=item.expected_structured),
        observation=SimpleNamespace(output=output),
    )
    evaluators = [intent_match.evaluate]
    if getattr(item, "has_instruments", False):
        evaluators.append(instrument_match.evaluate)
    if getattr(item, "has_rejections", False):
        evaluators.append(rejection_match.evaluate)
    evaluations = []
    for evaluate in evaluators:
        for score in evaluate(ctx).scores:
            evaluations.append(
                Evaluation(
                    name=score.name,
                    value=1.0 if score.value else 0.0,
                    comment=score.comment,
                    metadata=score.metadata,
                )
            )
    return evaluations


def case_passed(suite: str, evaluations: list) -> bool:
    """意图集：全部确定性评估器为真；业务集：首个评分（Judge / reply-check）≥ 阈值。"""
    if not evaluations:
        return False
    if suite == "intent":
        return all(float(ev.value) >= 1.0 for ev in evaluations)
    return float(evaluations[0].value) >= _PASS_THRESHOLD


def passes_quality_gate(summary: dict[str, Any], threshold: float) -> bool:
    """正向质量不因加入拒绝样本抬高；已标注的安全拒绝必须全部通过。"""
    if summary["pass_rate"] < threshold:
        return False
    buckets = summary.get("acceptance_buckets", {})
    executable = buckets.get("executable", {})
    rejection = buckets.get("expected_rejection", {})
    return not (
        executable.get("total", 0) and executable["pass_rate"] < threshold
        or rejection.get("total", 0) and rejection["passed"] != rejection["total"]
    )


# ── 报告 ──
def _report_text(value) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _report_input(input_data) -> str:
    if not isinstance(input_data, dict):
        return _report_text(input_data) if input_data else ""

    turns = input_data.get("turns")
    if not isinstance(turns, list):
        turns = [input_data]
        sub_scenes = input_data.get("sub_scenes", [])
        if isinstance(sub_scenes, list):
            turns.extend(sub_scenes)

    texts = []
    for turn in turns[:3]:
        if not isinstance(turn, dict):
            continue
        text = turn.get("send_text") or turn.get("raw_content") or ""
        if text:
            texts.append(str(text))
    return "; ".join(texts)


def _print_report(name, result):
    items = result.item_results
    if not items:
        print("无评估结果")
        return
    scores = []
    for r in items:
        score = float(r.evaluations[0].value) if r.evaluations else None
        comment = r.evaluations[0].comment if r.evaluations else "未评分"
        reply = (
            (r.output or {}).get("reply_text", "") if isinstance(r.output, dict) else str(r.output)
        )
        inp, exp = "", ""
        if isinstance(r.item, dict):
            inp_data = r.item.get("input", {})
            exp = (
                r.item.get("expected_output")
                or r.item.get("expectedOutput")
                or ""
            )
        elif hasattr(r.item, "input"):
            inp_data = getattr(r.item, "input", {})
            exp = getattr(r.item, "expected_output", "") or ""
        else:
            inp_data = {}
        inp = _report_input(inp_data)
        out_turns = (r.output or {}).get("turns", []) if isinstance(r.output, dict) else []
        trace_log = (r.output or {}).get("trace_log", "") if isinstance(r.output, dict) else ""
        scores.append(
            {
                "score": score,
                "comment": comment,
                "reply": reply,
                "input": inp,
                "expected": _report_text(exp),
                "turns": out_turns,
                "trace_log": trace_log,
            }
        )
    t = len(scores)
    scored = [s for s in scores if s["score"] is not None]
    unscored = [s for s in scores if s["score"] is None]
    print(f"\n{'=' * 60}\n评估报告：{name}（PASS 阈值={_PASS_THRESHOLD}）\n{'=' * 60}")
    if scored:
        p = sum(1 for s in scored if s["score"] >= _PASS_THRESHOLD)
        a = sum(s["score"] for s in scored) / len(scored)
        print(
            f"用例数: {t}  已评分: {len(scored)}  未评分: {len(unscored)}  "
            f"通过率: {p}/{len(scored)} ({p / len(scored) * 100:.1f}%)  平均分: {a:.2f}"
        )
        print(
            f"满分: {sum(1 for s in scored if s['score'] >= 0.99)}  "
            f"零分: {sum(1 for s in scored if s['score'] == 0.0)}"
        )
    else:
        print(f"用例数: {t}  已评分: 0  未评分: {len(unscored)}")

    failed = [
        s
        for s in scored
        if s["score"] is not None and s["score"] < _PASS_THRESHOLD
    ]
    if failed:
        print(f"\n失败 case ({len(failed)}):")
        for s in failed:
            print(f"  [{s['score']}] 输入: {s['input']}")
            print(f"    期望: {s['expected'][:100]}  Judge: {s['comment']}")
            for tr in s.get("turns", []):
                n = tr.get("turn", "?")
                pt = tr.get("product_type", "?")
                intent = tr.get("intent") or "?"
                reply_s = (tr.get("reply_text") or "")[:80]
                trace = tr.get("trace") or "(无 trace)"
                qpassed = tr.get("quote_passed") or ""
                quote_info = (
                    f" | quote={len(qpassed)}c {qpassed[:50]!r}" if qpassed else " | quote=无"
                )
                err_info = f" | ERROR: {tr['error']}" if tr.get("error") else ""
                print(f"    第{n}轮 [{pt}/{intent}]{quote_info}{err_info}")
                print(f"      trace : {trace}")
                print(f"      reply : {reply_s or '(无回复)'}")
    if unscored:
        print(f"\n未评分 case ({len(unscored)}):")
        for s in unscored:
            print(f"  [未评分] 输入: {s['input']}")
            print(f"    期望: {s['expected'][:100]}  Judge: 未评分")
    if not failed and not unscored:
        print("\n全部通过")


# ── 本地 unified_golden.jsonl 支持 ──
class _LocalItem:
    """模拟 LangFuse dataset item 接口。"""

    def __init__(self, case: GoldenCase, suite: str = DEFAULT_SUITE):
        self.case = case
        self.id = case.id
        self.metadata = {
            "id": case.id,
            "type": case.type,
            "category": case.category,
            "test_function": case.category,
            "overview": build_overview(case),
            "source": case.source,
            "suite": suite,
            "tags": [tag for tag in (case.category, case.source, suite) if tag],
            "turns": len(case.turns),
        }
        self.input = {
            "turns": [
                {
                    "send_text": turn.send_text,
                    "at_bot": turn.at_bot,
                    "quote_previous": turn.quote_previous,
                    "quote_desc": turn.quote_desc,
                    "quote_content": turn.quote_content,
                    "history": turn.history,
                    "prev_product_type": turn.prev_product_type,
                }
                for turn in case.turns
            ]
        }
        # B 方言带 expected.output；A 方言没有，用逐轮 expected + 文本断言拼期望，Judge 不盲评
        self.expected_output = case.expected_output or build_expected_text(case)
        # Dataset 同款 expectedOutput：本地确定性评估器（intent_match / instrument_match）读这份
        self.expected_structured = dataset_expected(case)
        self.has_instruments = any(bool(turn.expected.get("instruments")) for turn in case.turns)
        self.has_rejections = any(bool(turn.expected.get("rejection")) for turn in case.turns)


async def run_local(
    golden_paths,
    filter_func,
    ids,
    max_concurrency,
    limit,
    dry_run,
    no_judge=False,
    suite: str = DEFAULT_SUITE,
    report: Path | None = None,
) -> dict[str, Any] | None:
    """本地评估；返回摘要（dry-run 返回 None）。意图集用确定性评估器，业务集用 Judge。"""
    no_judge = not judge_enabled(suite, no_judge=no_judge)
    cases = load_golden(golden_paths)
    print(f"加载 {len(cases)} 条 (local, suite={suite})")
    cases, unrunnable = select_runnable(cases)
    if unrunnable:
        print(f"跳过不可执行 case: {len(unrunnable)} 条 (某轮 raw_content 为空，见 skip_reason；Issue #113)")
    if _SKIP_IMAGE_CASES:
        skipped = [case for case in cases if _is_image_case(case)]
        cases = [case for case in cases if not _is_image_case(case)]
        if skipped:
            print(f"跳过图片/Excel case: {len(skipped)} 条 (golden 标注'用户发送图片'但无图片数据)")
    if ids:
        cases = filter_by_ids(cases, ids)
        print(f"按 id 过滤: {len(cases)} 条")
    if filter_func:
        cases = filter_by_category(cases, filter_func)
        print(f"按 category 过滤: {len(cases)} 条")
    if limit:
        cases = cases[:limit]
        print(f"限制: {len(cases)} 条")
    items = [_LocalItem(c, suite=suite) for c in cases]
    if dry_run:
        for item in items:
            raw = "; ".join(t["send_text"][:60] for t in item.input["turns"][:2])
            print(f"  {item.id}: {raw}")
        return None

    # 启用 Langfuse 时，把 pipeline 调用包到 outer span 里，使 CallbackHandler 的
    # per-node trace 自动嵌套（OTel context propagation），并能拿到稳定 trace_id 挂 score。
    # 双 key 不齐（CI / 纯本地）就不构造客户端：SDK 无 key 时静默 no-op，会误报"写入成功"
    lf: object | None = None
    if _langfuse_enabled():
        try:
            from langfuse import Langfuse  # type: ignore[import-not-found]

            lf = Langfuse()
        except Exception:
            lf = None
    run_name = f"local-{time.strftime('%Y%m%d-%H%M%S')}"

    sem = asyncio.Semaphore(max_concurrency)

    def _evaluate(item, output: dict[str, Any]) -> list:
        if suite == "intent":
            return code_evaluations(item, output)
        if no_judge:
            return [reply_check(output)]
        return [
            judge_by_deepseek(
                output=output, expected_output=item.expected_output, metadata=item.metadata
            )
        ]

    def _turns_out(output: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "turn": t.get("turn"),
                "raw": t.get("raw_content", ""),
                "reply": t.get("reply_text", ""),
                "product_type": t.get("product_type"),
                "intent": t.get("intent"),
                "tickers": t.get("tickers"),
                "place_params": t.get("place_params"),
                "api_result": t.get("api_result"),
                "api_code": t.get("api_code"),
                "error": t.get("error"),
                "trace": t.get("trace", ""),
                "quote_passed": t.get("quote_passed", ""),
            }
            for t in output.get("turns", [])
        ]

    def _evaluation_dicts(evaluations: list) -> list[dict[str, Any]]:
        return [
            {"name": ev.name, "value": float(ev.value), "comment": ev.comment}
            for ev in evaluations
        ]

    async def _run_one(item):
        async with sem:
            trace_id: str | None = None
            if lf is not None:
                with lf.start_as_current_observation(  # type: ignore[union-attr]
                    name=item.id,
                    as_type="chain",
                    input=item.input,
                    metadata={**item.metadata, "run_name": run_name},
                ) as span:
                    trace_id = span.trace_id
                    output = await run_langgraph_pipeline(item=item, suite=suite)
                    # 在 span 内完成评分，把分数 / 期望 / 评价理由也写到 output，AI 一处可读全部
                    evaluations = _evaluate(item, output)
                    ev = evaluations[0]
                    turns_out = _turns_out(output)
                    # 富 output：顶层 expected/score/comment + 每轮 turn/raw/reply/trace + 抽取详情
                    span_output: dict[str, Any] = {
                        "expected": item.expected_output,
                        "score": float(ev.value),
                        "judge_comment": ev.comment,
                        "evaluations": _evaluation_dicts(evaluations),
                    }
                    if turns_out:
                        span_output["turns"] = turns_out
                    else:
                        span_output["reply"] = output.get("reply_text", "")
                    span.update(output=span_output)
            else:
                output = await run_langgraph_pipeline(item=item, suite=suite)
                evaluations = _evaluate(item, output)
                ev = evaluations[0]
            return {
                "item": item,
                "output": output,
                "eval": ev,
                "evals": evaluations,
                "trace_id": trace_id,
            }

    mode = "code-evaluators" if suite == "intent" else ("no-judge" if no_judge else "with judge")
    print(f"开始实验 ({len(items)} 条, 并行 {max_concurrency}, {mode})...\n")
    t0 = time.time()
    results = await asyncio.gather(*[_run_one(it) for it in items])
    elapsed = time.time() - t0

    scores = []
    for r in results:
        evaluations = r["evals"]
        scores.append(
            {
                "id": r["item"].id,
                "score": float(evaluations[0].value),
                "comment": evaluations[0].comment,
                "passed": case_passed(suite, evaluations),
                "expected_rejection": r["item"].has_rejections,
                "evaluations": _evaluation_dicts(evaluations),
                "reply": r["output"].get("reply_text", ""),
                "expected": r["item"].expected_output,
                "turns": r["output"].get("turns", []),
                "trace_log": r["output"].get("trace_log", ""),
            }
        )

    passed = sum(1 for s in scores if s["passed"])
    avg = sum(s["score"] for s in scores) / len(scores) if scores else 0
    pass_rate = passed / len(scores) if scores else 0.0
    print(f"\n{'=' * 60}")
    print(
        f"套件: {suite}  用例数: {len(scores)}  通过率: {passed}/{len(scores)} ({pass_rate * 100:.1f}%)"
        f"  平均分: {avg:.2f}  耗时: {elapsed:.1f}s"
    )
    failed = [s for s in scores if not s["passed"]]
    if failed:
        print(f"\n失败 case ({len(failed)}):")
        for s in failed:
            print(f"  [{s['score']}] {s['id']}: {s['comment']}")
            for ev in s["evaluations"]:
                print(f"    [{ev['name']}={ev['value']}] {ev['comment']}")
            print(f"    期望: {str(s['expected'])[:100]}")
            for tr in s.get("turns", []):
                n = tr.get("turn", "?")
                pt = tr.get("product_type", "?")
                intent = tr.get("intent") or "?"
                reply = (tr.get("reply_text") or "")[:80]
                trace = tr.get("trace") or "(无 trace)"
                qpassed = tr.get("quote_passed") or ""
                quote_info = (
                    f" | quote={len(qpassed)}c {qpassed[:50]!r}" if qpassed else " | quote=无"
                )
                err_info = f" | ERROR: {tr['error']}" if tr.get("error") else ""
                print(f"    第{n}轮 [{pt}/{intent}]{quote_info}{err_info}")
                print(f"      trace : {trace}")
                print(f"      reply : {reply or '(无回复)'}")
    else:
        print("\n全部通过")

    # LangFuse 评分写回：每个评估器一个 score，挂到 _run_one 里 outer span 的 trace_id 上。
    # 这样 per-node trace（CallbackHandler 写的）和 score 在同一个 trace 里。
    if lf is not None:
        try:
            for r in results:
                if not r.get("trace_id"):
                    continue
                for ev in r["evals"]:
                    lf.create_score(  # type: ignore[union-attr]
                        trace_id=r["trace_id"],
                        name=ev.name,
                        value=float(ev.value),
                        comment=ev.comment,
                    )
            lf.flush()  # type: ignore[union-attr]
            host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
            print(f"\nLangFuse 写入成功  run={run_name}  host={host}")
        except Exception as e:
            print(f"\nLangFuse 写入失败（不影响本地结果）: {e}")

    summary: dict[str, Any] = {
        "suite": suite,
        "run_name": run_name,
        "total": len(scores),
        "passed": passed,
        "pass_rate": pass_rate,
        "elapsed_seconds": round(elapsed, 1),
        "cases": [
            {
                "id": s["id"],
                "passed": s["passed"],
                "expected_rejection": s["expected_rejection"],
                "score": s["score"],
                "evaluations": s["evaluations"],
                "turns": s["turns"],
            }
            for s in scores
        ],
    }
    if suite == "intent":
        buckets = {}
        for name, is_rejection in (("executable", False), ("expected_rejection", True)):
            selected = [score for score in scores if score["expected_rejection"] == is_rejection]
            count = sum(score["passed"] for score in selected)
            buckets[name] = {"total": len(selected), "passed": count,
                             "pass_rate": count / len(selected) if selected else None}
            print(f"验收分桶 {name}: {count}/{len(selected)}")
        summary["acceptance_buckets"] = buckets
    if report is not None:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print(f"报告已写入 {report}")
    return summary


# ── 主流程（LangFuse 云端） ──
def select_dataset_items(items: list, ids: list[str] | None) -> list:
    selected = []
    wanted = set(ids or [])
    for item in items:
        status = getattr(item, "status", "ACTIVE")
        if getattr(status, "value", status) != "ACTIVE":
            continue
        metadata = item.metadata if isinstance(item.metadata, dict) else {}
        if not wanted or item.id in wanted or metadata.get("id") in wanted:
            selected.append(item)
    return selected


async def run_eval(
    dataset_name,
    filter_func,
    ids,
    max_concurrency,
    limit,
    dry_run,
    no_judge=False,
    suite: str = DEFAULT_SUITE,
):
    from functools import partial

    from langfuse import Langfuse

    no_judge = not judge_enabled(suite, no_judge=no_judge)
    lf = Langfuse()
    items = select_dataset_items(list(lf.get_dataset(dataset_name).items), None)
    print(f"加载 {len(items)} 条 (suite={suite})")
    if ids:
        items = select_dataset_items(items, ids)
        print(f"按 id 过滤: {len(items)} 条")
    if filter_func:
        items = [i for i in items if filter_func in (i.metadata or {}).get("test_function", "")]
        print(f"按 test_function 过滤: {len(items)} 条")
    if limit:
        items = items[:limit]
        print(f"限制: {len(items)} 条")
    if dry_run:
        for item in items:
            inp = item.input if isinstance(item.input, dict) else json.loads(item.input)
            # 上传结构是 send_text + sub_scenes（无 turns 键），与报告共用同一投影
            print(f"  {item.id}: {_report_input(inp)}")
        return
    mode = "no-judge" if no_judge else "with judge"
    print(f"开始实验 ({len(items)} 条, 并行 {max_concurrency}, {mode})...\n")
    experiment_prefix = "intent-eval" if suite == "intent" else "option-eval"
    experiment_options = {
        "name": f"{experiment_prefix}-{time.strftime('%Y%m%d-%H%M%S')}",
        "data": items,
        "task": partial(run_langgraph_pipeline, suite=suite),
        "max_concurrency": max_concurrency,
    }
    if not no_judge:
        experiment_options["evaluators"] = [judge_by_deepseek]
    result = lf.run_experiment(**experiment_options)
    print(f"\n实验完成: {result.name}")
    _print_report(result.name, result)
    print(
        f"\nLangfuse: {os.environ.get('LANGFUSE_HOST', 'https://cloud.langfuse.com')}/project/{os.environ.get('LANGFUSE_PROJECT', 'otc-agent')}"
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ids")
    p.add_argument("--limit", type=int)
    p.add_argument("--filter")
    p.add_argument("--dataset", default=DATASET_NAME)
    p.add_argument("--concurrency", type=int, default=1)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--no-judge", action="store_true", help="跳过 Judge 打分，只检查 reply_text 是否非空"
    )
    p.add_argument(
        "--local",
        action="append",
        default=None,
        help="本地 categories / intent JSONL 文件或目录，可重复传入（不走 LangFuse Dataset）",
    )
    p.add_argument(
        "--suite",
        choices=SUITES,
        help="套件；默认按 --local 路径（intent/）或 --dataset 前缀（intent_ / intent-）判定。intent 不跑 Judge",
    )
    p.add_argument(
        "--fail-under",
        type=float,
        default=None,
        help="通过率低于该值时退出码 1（CI 门槛；仅 --local 生效）",
    )
    p.add_argument(
        "--report",
        type=Path,
        default=None,
        help="把本地评估摘要写成 JSON（仅 --local 生效）",
    )
    args = p.parse_args()
    id_list = [x.strip() for x in args.ids.split(",")] if args.ids else None
    local_paths = [Path(value) for value in args.local] if args.local else None
    suite = resolve_suite(args.suite, local_paths, None if args.local else args.dataset)
    if local_paths:
        summary = asyncio.run(
            run_local(
                local_paths,
                args.filter,
                id_list,
                args.concurrency,
                args.limit,
                args.dry_run,
                args.no_judge,
                suite=suite,
                report=args.report,
            )
        )
        if (
            args.fail_under is not None
            and summary is not None
            and not passes_quality_gate(summary, args.fail_under)
        ):
            print(f"质量门未通过：总体/正向通过率要求 {args.fail_under:.1%}，明确拒绝要求 100%")
            return 1
        return 0
    asyncio.run(
        run_eval(
            args.dataset,
            args.filter,
            id_list,
            args.concurrency,
            args.limit,
            args.dry_run,
            args.no_judge,
            suite=suite,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
