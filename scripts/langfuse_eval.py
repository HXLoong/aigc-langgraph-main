"""期权链路评估。跑 LangGraph，DeepSeek v4 flash Judge 打分。

OTC_API_BASE_URL 从 .env 读取，指向真实后端地址。
前提: 对应的后端服务必须已启动
用法: uv run python scripts/langfuse_eval.py --ids opt-001 --concurrency 1
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

_DOTENV = Path(__file__).resolve().parent.parent / ".env"
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

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from langgraph.checkpoint.memory import InMemorySaver
from app.graph.main import build_main_graph
from app.prompts import load_prompt
from app.api.turn_state import inputs_to_state
from harness.golden import GoldenCase, build_overview, filter_by_category, filter_by_ids, load_golden
from harness.multi_turn import early_stop_kind, quote_for_turn

DATASET_NAME = "otc-option-golden"


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
async def _run_graph_once(graph, config, raw_content, has_mention=True, turn=1, quote_content=None):
    # 与生产 routes 同一条入口（ADR 0024 D2）：Dify 形态 inputs → inputs_to_state
    state = inputs_to_state({
        "rawContent": raw_content,
        "quoteContent": quote_content,
        "messageId": secrets.randbelow(900_000_000_000_000) + 100_000_000_000_000,
        "roomId": os.environ.get("EVAL_ROOM_ID", "eval-room"),
        "userId": os.environ.get("EVAL_USER_ID", "eval-user"),
        "guid": "",
        "at_bot": has_mention,
    })
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
        from langfuse.langchain import CallbackHandler

        return [CallbackHandler()]
    except Exception as exc:  # noqa: BLE001
        print(f"LangFuse CallbackHandler 不可用，per-node span 缺失：{exc}")
        return []


async def run_langgraph_pipeline(*, item, **kwargs):
    inp = item.input if isinstance(item.input, dict) else json.loads(item.input)
    turns_data = inp.get("turns", [])
    cp = InMemorySaver()
    graph = build_main_graph(cp)
    conversation_id = str(uuid.uuid4())
    # 与生产 routes._build_run_config 同一契约：thread + session + 审计 trace_id
    config = {
        "configurable": {"thread_id": conversation_id},
        "metadata": {
            "trace_id": uuid.uuid4().hex,
            "langfuse_session_id": conversation_id,
            "langfuse_tags": ["eval"],
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
        try:
            rs = await _run_graph_once(
                graph,
                config,
                raw_content=t.get("send_text", ""),
                has_mention=bool(t.get("at_bot", not results)),
                turn=len(results) + 1,
                quote_content=quote,
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

            # place_params 简化（保留 expected_action + orderList 字段，去掉 None 减少噪音）
            pp = rs.get("place_params") or {}
            orders_raw = pp.get("orderList", [])
            orders_simple = [
                {
                    k: v
                    for k, v in (
                        o
                        if isinstance(o, dict)
                        else (o.model_dump() if hasattr(o, "model_dump") else {})
                    ).items()
                    if v is not None
                }
                for o in orders_raw
            ]
            place_simple = (
                {
                    "action": pp.get("expected_action"),
                    "orderList": orders_simple,
                }
                if pp
                else None
            )

            err = rs.get("error")
            err_simple = None
            if err is not None:
                if hasattr(err, "model_dump"):
                    err_dict = err.model_dump()
                    err_simple = {
                        "node": err_dict.get("node"),
                        "type": err_dict.get("type"),
                        "message": (err_dict.get("message") or "")[:200],
                    }
                elif isinstance(err, dict):
                    err_simple = {
                        "node": err.get("node"),
                        "type": err.get("type"),
                        "message": (err.get("message") or "")[:200],
                    }
                else:
                    err_simple = {"message": str(err)[:200]}

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
        tr["raw_content"] = t.get("send_text", "")
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


def judge_by_deepseek(*, output, expected_output, metadata=None, **kwargs):
    from anthropic import Anthropic

    actual = output.get("reply_text", "")
    overview = (metadata or {}).get("overview", "")
    user = f"## 测试用例\n{overview}\n\n## 实际回复\n{actual}\n\n## 期望回复\n{expected_output}\n\n请评分："
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


# ── 报告 ──
def _print_report(name, result):
    items = result.item_results
    if not items:
        print("无评估结果")
        return
    scores = []
    for r in items:
        score = float(r.evaluations[0].value) if r.evaluations else 0.0
        comment = r.evaluations[0].comment if r.evaluations else ""
        reply = (
            (r.output or {}).get("reply_text", "") if isinstance(r.output, dict) else str(r.output)
        )
        inp, exp = "", ""
        if isinstance(r.item, dict):
            inp_data = r.item.get("input", {})
            exp = r.item.get("expected_output", "") or ""
        elif hasattr(r.item, "input"):
            inp_data = getattr(r.item, "input", {})
            exp = getattr(r.item, "expected_output", "") or ""
        else:
            inp_data = {}
        if isinstance(inp_data, dict):
            turns_data = inp_data.get("turns", [])
            inp = "; ".join(t.get("send_text", "") for t in turns_data[:3])
        out_turns = (r.output or {}).get("turns", []) if isinstance(r.output, dict) else []
        trace_log = (r.output or {}).get("trace_log", "") if isinstance(r.output, dict) else ""
        scores.append(
            {
                "score": score,
                "comment": comment,
                "reply": reply,
                "input": inp,
                "expected": exp,
                "turns": out_turns,
                "trace_log": trace_log,
            }
        )
    t = len(scores)
    p = sum(1 for s in scores if s["score"] >= _PASS_THRESHOLD)
    a = sum(s["score"] for s in scores) / t
    print(f"\n{'=' * 60}\n评估报告：{name}（PASS 阈值={_PASS_THRESHOLD}）\n{'=' * 60}")
    print(f"用例数: {t}  通过率: {p}/{t} ({p / t * 100:.1f}%)  平均分: {a:.2f}")
    print(
        f"满分: {sum(1 for s in scores if s['score'] >= 0.99)}  零分: {sum(1 for s in scores if s['score'] == 0.0)}"
    )
    failed = [s for s in scores if s["score"] < _PASS_THRESHOLD]
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
    else:
        print("\n全部通过")


# ── 本地 unified_golden.jsonl 支持 ──
class _LocalItem:
    """模拟 LangFuse dataset item 接口。"""

    def __init__(self, case: GoldenCase):
        self.case = case
        self.id = case.id
        self.metadata = {
            "id": case.id,
            "type": case.type,
            "category": case.category,
            "test_function": case.category,
            "overview": build_overview(case),
            "source": case.source,
            "tags": [case.category, case.source],
            "turns": len(case.turns),
        }
        self.input = {
            "turns": [
                {
                    "send_text": turn.send_text,
                    "at_bot": turn.at_bot,
                    "quote_previous": turn.quote_previous,
                }
                for turn in case.turns
            ]
        }
        self.expected_output = case.expected_output


async def run_local(
    golden_paths, filter_func, ids, max_concurrency, limit, dry_run, no_judge=False
):
    cases = load_golden(golden_paths)
    print(f"加载 {len(cases)} 条 (local)")
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
    items = [_LocalItem(c) for c in cases]
    if dry_run:
        for item in items:
            raw = "; ".join(t["send_text"][:60] for t in item.input["turns"][:2])
            print(f"  {item.id}: {raw}")
        return

    # 启用 Langfuse 时，把 pipeline 调用包到 outer span 里，使 CallbackHandler 的
    # per-node trace 自动嵌套（OTel context propagation），并能拿到稳定 trace_id 挂 score。
    try:
        from langfuse import Langfuse  # type: ignore[import-not-found]

        lf: object | None = Langfuse()
    except Exception:
        lf = None
    run_name = f"local-{time.strftime('%Y%m%d-%H%M%S')}"

    sem = asyncio.Semaphore(max_concurrency)

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
                    output = await run_langgraph_pipeline(item=item)
                    # 在 span 内完成 judge，把分数 / 期望 / 评价理由也写到 output，AI 一处可读全部
                    if no_judge:
                        reply = output.get("reply_text", "")
                        from langfuse.experiment import Evaluation

                        ev = Evaluation(
                            name="reply-check",
                            value=1.0 if reply.strip() else 0.0,
                            comment="有回复" if reply.strip() else "reply_text 为空",
                        )
                    else:
                        ev = judge_by_deepseek(
                            output=output,
                            expected_output=item.expected_output,
                            metadata=item.metadata,
                        )
                    # 富 output：顶层 expected/score/comment + 每轮 turn/raw/reply/trace + 抽取详情
                    turns_out = [
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
                    span_output = (
                        {
                            "expected": item.expected_output,
                            "score": float(ev.value),
                            "judge_comment": ev.comment,
                            "turns": turns_out,
                        }
                        if turns_out
                        else {
                            "reply": output.get("reply_text", ""),
                            "expected": item.expected_output,
                            "score": float(ev.value),
                            "judge_comment": ev.comment,
                        }
                    )
                    span.update(output=span_output)
            else:
                output = await run_langgraph_pipeline(item=item)
                if no_judge:
                    reply = output.get("reply_text", "")
                    from langfuse.experiment import Evaluation

                    ev = Evaluation(
                        name="reply-check",
                        value=1.0 if reply.strip() else 0.0,
                        comment="有回复" if reply.strip() else "reply_text 为空",
                    )
                else:
                    ev = judge_by_deepseek(
                        output=output, expected_output=item.expected_output, metadata=item.metadata
                    )
            return {"item": item, "output": output, "eval": ev, "trace_id": trace_id}

    print(
        f"开始实验 ({len(items)} 条, 并行 {max_concurrency}, {'no-judge' if no_judge else 'with judge'})...\n"
    )
    t0 = time.time()
    results = await asyncio.gather(*[_run_one(it) for it in items])
    elapsed = time.time() - t0

    scores = []
    for r in results:
        score = float(r["eval"].value)
        comment = r["eval"].comment
        scores.append(
            {
                "id": r["item"].id,
                "score": score,
                "comment": comment,
                "reply": r["output"].get("reply_text", ""),
                "expected": r["item"].expected_output,
                "turns": r["output"].get("turns", []),
                "trace_log": r["output"].get("trace_log", ""),
            }
        )

    passed = sum(1 for s in scores if s["score"] >= _PASS_THRESHOLD)
    avg = sum(s["score"] for s in scores) / len(scores) if scores else 0
    print(f"\n{'=' * 60}")
    print(
        f"用例数: {len(scores)}  通过率: {passed}/{len(scores)} ({passed / len(scores) * 100:.1f}%)  平均分: {avg:.2f}  耗时: {elapsed:.1f}s"
    )
    failed = [s for s in scores if s["score"] < _PASS_THRESHOLD]
    if failed:
        print(f"\n失败 case ({len(failed)}):")
        for s in failed:
            print(f"  [{s['score']}] {s['id']}: {s['comment']}")
            print(f"    期望: {s['expected'][:100]}")
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

    # LangFuse 评分写回：直接把 score 挂到 _run_one 里 outer span 的 trace_id 上。
    # 这样 per-node trace（CallbackHandler 写的）和 score 在同一个 trace 里。
    if lf is not None:
        try:
            for r in results:
                if not r.get("trace_id"):
                    continue
                lf.create_score(  # type: ignore[union-attr]
                    trace_id=r["trace_id"],
                    name="otc-option-judge",
                    value=float(r["eval"].value),
                    comment=r["eval"].comment,
                )
            lf.flush()  # type: ignore[union-attr]
            host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
            print(f"\nLangFuse 写入成功  run={run_name}  host={host}")
        except Exception as e:
            print(f"\nLangFuse 写入失败（不影响本地结果）: {e}")


# ── 主流程（LangFuse 云端） ──
async def run_eval(dataset_name, filter_func, ids, max_concurrency, limit, dry_run):
    from langfuse import Langfuse

    lf = Langfuse()
    items = list(lf.get_dataset(dataset_name).items)
    print(f"加载 {len(items)} 条")
    if ids:
        items = [i for i in items if i.id in ids]
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
            raw = "; ".join(t.get("send_text", "")[:60] for t in inp.get("turns", [])[:2])
            print(f"  {item.id}: {raw}")
        return
    print(f"开始实验 ({len(items)} 条, 并行 {max_concurrency})...\n")
    result = lf.run_experiment(
        name=f"option-eval-{time.strftime('%Y%m%d-%H%M%S')}",
        data=items,
        task=run_langgraph_pipeline,
        evaluators=[judge_by_deepseek],
        max_concurrency=max_concurrency,
    )
    print(f"\n实验完成: {result.name}")
    _print_report(result.name, result)
    print(
        f"\nLangfuse: {os.environ.get('LANGFUSE_HOST', 'https://cloud.langfuse.com')}/project/{os.environ.get('LANGFUSE_PROJECT', 'otc-agent')}"
    )


def main():
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
        help="本地 categories JSONL 文件或目录，可重复传入（不走 LangFuse）",
    )
    args = p.parse_args()
    id_list = [x.strip() for x in args.ids.split(",")] if args.ids else None
    if args.local:
        local_paths = [Path(value) for value in args.local]
        asyncio.run(
            run_local(
                local_paths,
                args.filter,
                id_list,
                args.concurrency,
                args.limit,
                args.dry_run,
                args.no_judge,
            )
        )
    else:
        asyncio.run(
            run_eval(args.dataset, args.filter, id_list, args.concurrency, args.limit, args.dry_run)
        )


if __name__ == "__main__":
    main()
