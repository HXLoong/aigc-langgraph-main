"""期权链路评估。跑 LangGraph，DeepSeek Judge 打分。

OTC_API_BASE_URL 从 .env 读取，指向真实后端地址。
前提: 对应的后端服务必须已启动
用法: uv run python scripts/langfuse_eval.py --ids opt-001 --concurrency 1
"""
from __future__ import annotations

import argparse, asyncio, json, os, re, sys, time
from pathlib import Path

_DOTENV = Path(__file__).resolve().parent.parent / ".env"
if _DOTENV.exists():
    for line in _DOTENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, _, v = line.partition("="); k, v = k.strip(), v.strip()
        # 去掉行内注释（如 "true  # 注释" → "true"）
        v = v.split("#")[0].strip()
        if k: os.environ[k] = v

# 清除 shell 中可能干扰 .env 配置的变量（如 Claude Code 设置的 ANTHROPIC_AUTH_TOKEN）
for _k in ("ANTHROPIC_AUTH_TOKEN",):
    os.environ.pop(_k, None)

# OTC_API_BASE_URL 由上方 .env 加载提供（mock 或真实 GOATS），不再强制覆盖
# Langfuse API 不走代理
os.environ["NO_PROXY"] = os.environ.get("NO_PROXY", "") + ",cloud.langfuse.com"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from langgraph.checkpoint.memory import InMemorySaver
from app.graphs.main_graph import build_main_graph
from app.state import WechatInput, make_initial_state

DATASET_NAME = "otc-option-golden"


def _fmt_trace(trace_entries) -> str:
    """把 TraceEntry list 格式化成 node[decision] → ... 字符串。"""
    parts = []
    for e in (trace_entries or []):
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
    wx = WechatInput(
        conversation_id=config["configurable"]["thread_id"],
        message_id=f"m-{config['configurable']['thread_id']}-t{turn}",
        room_id=os.environ.get("EVAL_ROOM_ID", "eval-room"),
        user_id=os.environ.get("EVAL_USER_ID", "eval-user"),
        guid="",
        raw_content=raw_content, quote_content=quote_content,
    )
    state = make_initial_state(wx)
    state["at_bot"] = has_mention
    result = await graph.ainvoke(state, config=config)
    return result

async def run_langgraph_pipeline(*, item, **kwargs):
    inp = item.input if isinstance(item.input, dict) else json.loads(item.input)
    turns_data = inp.get("turns", [])
    cp = InMemorySaver()
    graph = build_main_graph(cp)
    config = {"configurable": {"thread_id": f"eval-{item.id}"}}
    results, prev = [], None
    for t in turns_data:
        quote = None
        if t.get("quote_desc") and prev: quote = prev
        try:
            rs = await _run_graph_once(graph, config,
                raw_content=t.get("raw_content",""),
                has_mention=True,  # 期权测试全部需要 bot 响应
                turn=len(results)+1, quote_content=quote)
            tr = {
                "product_type": rs.get("product_type", "unknown"),
                "intent": rs.get("intent"),
                "reply_text": rs.get("reply_text", ""),
                "error": rs.get("error"),
                "trace": _fmt_trace(rs.get("trace")),
                "quote_passed": (quote or "")[:120],  # 实际传入的引用内容预览
            }
        except Exception as e:
            tr = {"product_type": "error", "intent": None, "reply_text": "", "error": str(e),
                  "trace": "", "quote_passed": (quote or "")[:120]}
        tr["turn"] = len(results)+1
        tr["raw_content"] = t.get("raw_content", "")
        results.append(tr)
        prev = tr.get("reply_text") or ""
    lines = []
    for r in results:
        l = f"[第{r['turn']}轮] 机器人回复: {r['reply_text'] or '(无回复)'}"
        if r.get("error"): l += f" [错误: {r['error']}]"
        lines.append(l)
    # trace_log 单独存储，方便 LangFuse 查看（不影响 Judge 评分的 reply_text）
    trace_log_lines = []
    for r in results:
        qlen = len(r.get("quote_passed") or "")
        qprev = (r.get("quote_passed") or "")[:60]
        tl = (f"[第{r['turn']}轮] input={r.get('raw_content','')[:40]!r}"
              f" | route={r['product_type']}/{r['intent'] or '?'}"
              f" | quote={qlen}c({qprev!r})"
              f" | trace: {r.get('trace','')}")
        if r.get("error"):
            tl += f" | ERROR: {r['error']}"
        trace_log_lines.append(tl)
    return {"reply_text": "\n".join(lines), "turns": results, "trace_log": "\n".join(trace_log_lines)}

# ── Judge ──
JUDGE = """你是场外衍生品AI指令助手的测试审查员。
评估: 1.产品路由 2.意图识别 3.参数提取 4.多轮逻辑 5.反案例
正案例完全正确=1.0,参数遗漏=0.7~0.9;反案例正确拒绝=1.0,错误执行=0
必须只输出JSON: {"pass":true/false,"score":0.0~1.0,"reason":"一句话"}"""

def judge_by_deepseek(*, output, expected_output, metadata=None, **kwargs):
    from anthropic import Anthropic
    actual = output.get("reply_text","")
    overview = (metadata or {}).get("overview","")
    user = f"## 测试用例\n{overview}\n\n## 实际回复\n{actual}\n\n## 期望回复\n{expected_output}\n\n请评分："
    client = Anthropic()
    resp = client.messages.create(
        model=os.environ.get("ANTHROPIC_MODEL","deepseek-v4-pro[1m]"), max_tokens=1024,
        system=JUDGE, messages=[{"role":"user","content":user},
            {"role":"assistant","content":"{"}],
        thinking={"type":"enabled","budget_tokens":4096})
    texts = []
    for block in resp.content:
        if hasattr(block,"text"): texts.append(block.text)
    text = "".join(texts).strip()
    if text and not text.startswith("{"): text = "{" + text
    try: result = json.loads(text)
    except:
        s = text.find("{"); e = text.rfind("}")
        try: result = json.loads(text[s:e+1]) if s>=0 and e>s else None
        except: result = None
    if not result: result = {"pass":False,"score":0.0,"reason":f"JSON解析失败:{text[:100]}"}
    from langfuse.experiment import Evaluation
    return Evaluation(name="otc-option-judge", value=float(result.get("score",0)),
        comment=result.get("reason",""), metadata={"pass":result.get("pass",False)})

# ── 报告 ──
def _print_report(name, result):
    items = result.item_results
    if not items: print("无评估结果"); return
    scores = []
    for r in items:
        score = float(r.evaluations[0].value) if r.evaluations else 0.0
        comment = r.evaluations[0].comment if r.evaluations else ""
        reply = (r.output or {}).get("reply_text","") if isinstance(r.output,dict) else str(r.output)
        inp, exp = "", ""
        if isinstance(r.item,dict):
            inp_data = r.item.get("input",{}); exp = r.item.get("expected_output","") or ""
        elif hasattr(r.item,"input"):
            inp_data = getattr(r.item,"input",{}); exp = getattr(r.item,"expected_output","") or ""
        else: inp_data = {}
        if isinstance(inp_data,dict):
            turns_data = inp_data.get("turns",[]); inp = "; ".join(t.get("raw_content","") for t in turns_data[:3])
        out_turns = (r.output or {}).get("turns", []) if isinstance(r.output, dict) else []
        trace_log = (r.output or {}).get("trace_log", "") if isinstance(r.output, dict) else ""
        scores.append({"score":score,"comment":comment,"reply":reply,"input":inp,"expected":exp,
                        "turns": out_turns, "trace_log": trace_log})
    t = len(scores); p = sum(1 for s in scores if s["score"]>=0.99); a = sum(s["score"] for s in scores)/t
    print(f"\n{'='*60}\n评估报告：{name}\n{'='*60}")
    print(f"用例数: {t}  通过率: {p}/{t} ({p/t*100:.1f}%)  平均分: {a:.2f}")
    print(f"满分: {sum(1 for s in scores if s['score']>=0.99)}  零分: {sum(1 for s in scores if s['score']==0.0)}")
    failed = [s for s in scores if s["score"]<0.99]
    if failed:
        print(f"\n失败 case ({len(failed)}):")
        for s in failed:
            print(f"  [{s['score']}] 输入: {s['input']}")
            print(f"    期望: {s['expected'][:100]}  Judge: {s['comment']}")
            for tr in s.get("turns", []):
                n = tr.get("turn", "?"); pt = tr.get("product_type", "?"); intent = tr.get("intent") or "?"
                reply_s = (tr.get("reply_text") or "")[:80]
                trace = tr.get("trace") or "(无 trace)"
                qpassed = tr.get("quote_passed") or ""
                quote_info = f" | quote={len(qpassed)}c {qpassed[:50]!r}" if qpassed else " | quote=无"
                err_info = f" | ERROR: {tr['error']}" if tr.get("error") else ""
                print(f"    第{n}轮 [{pt}/{intent}]{quote_info}{err_info}")
                print(f"      trace : {trace}")
                print(f"      reply : {reply_s or '(无回复)'}")
    else: print("\n全部通过")

# ── 本地 unified_golden.jsonl 支持 ──
def _build_local_overview(case: dict) -> str:
    if case.get("overview"):
        return case["overview"]

    expected = case.get("expected", {})
    lines = [
        f"ID: {case.get('id', '')}",
        f"类别: {case.get('category', '')}",
        f"用例类型: {case.get('type', '')}",
        f"来源: {case.get('source', '')}",
        f"期望路由: product_type={expected.get('product_type', '')}, intent={expected.get('intent', '')}",
        "对话:",
    ]
    for i, turn in enumerate(case.get("conversation", []), 1):
        raw = turn.get("raw_content", "")
        quote = turn.get("quote_desc", "")
        if quote:
            lines.append(f"  第{i}轮: raw_content={raw}; 引用上一轮机器人回复")
        else:
            lines.append(f"  第{i}轮: raw_content={raw}; 无引用")
    return "\n".join(lines)


class _LocalItem:
    """模拟 LangFuse dataset item 接口。"""
    def __init__(self, case: dict):
        self.id = case["id"]
        self.metadata = {
            "id": case.get("id", ""),
            "type": case.get("type", ""),
            "category": case.get("category", ""),
            "test_function": case.get("category", ""),
            "overview": _build_local_overview(case),
            "source": case.get("source", ""),
            "tags": [case.get("category", ""), case.get("source", "")],
            "turns": len(case.get("conversation", [])),
        }
        # 转成 run_langgraph_pipeline 期望的 input 格式
        conv = case.get("conversation", [])
        self.input = {"turns": [{"raw_content": c["raw_content"], "quote_desc": c.get("quote_desc", "")} for c in conv]}
        self.expected_output = case.get("expected", {}).get("output", "")


async def run_local(golden_path, filter_func, ids, max_concurrency, limit, dry_run, no_judge=False):
    with open(golden_path, encoding="utf-8") as f:
        cases = [json.loads(line) for line in f if line.strip()]
    print(f"加载 {len(cases)} 条 (local)")
    if ids: cases = [c for c in cases if c["id"] in ids]; print(f"按 id 过滤: {len(cases)} 条")
    if filter_func: cases = [c for c in cases if filter_func in c.get("category","")]; print(f"按 category 过滤: {len(cases)} 条")
    if limit: cases = cases[:limit]; print(f"限制: {len(cases)} 条")
    items = [_LocalItem(c) for c in cases]
    if dry_run:
        for item in items:
            raw = "; ".join(t["raw_content"][:60] for t in item.input["turns"][:2])
            print(f"  {item.id}: {raw}")
        return

    sem = asyncio.Semaphore(max_concurrency)
    async def _run_one(item):
        async with sem:
            output = await run_langgraph_pipeline(item=item)
            if no_judge:
                reply = output.get("reply_text", "")
                from langfuse.experiment import Evaluation
                ev = Evaluation(name="reply-check", value=1.0 if reply.strip() else 0.0,
                    comment="有回复" if reply.strip() else "reply_text 为空")
            else:
                ev = judge_by_deepseek(output=output, expected_output=item.expected_output, metadata=item.metadata)
            return {"item": item, "output": output, "eval": ev}

    print(f"开始实验 ({len(items)} 条, 并行 {max_concurrency}, {'no-judge' if no_judge else 'with judge'})...\n")
    t0 = time.time()
    results = await asyncio.gather(*[_run_one(it) for it in items])
    elapsed = time.time() - t0

    scores = []
    for r in results:
        score = float(r["eval"].value)
        comment = r["eval"].comment
        scores.append({
            "id": r["item"].id, "score": score, "comment": comment,
            "reply": r["output"].get("reply_text", ""),
            "expected": r["item"].expected_output,
            "turns": r["output"].get("turns", []),
            "trace_log": r["output"].get("trace_log", ""),
        })

    passed = sum(1 for s in scores if s["score"] >= 0.99)
    avg = sum(s["score"] for s in scores) / len(scores) if scores else 0
    print(f"\n{'='*60}")
    print(f"用例数: {len(scores)}  通过率: {passed}/{len(scores)} ({passed/len(scores)*100:.1f}%)  平均分: {avg:.2f}  耗时: {elapsed:.1f}s")
    failed = [s for s in scores if s["score"] < 0.99]
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
                quote_info = f" | quote={len(qpassed)}c {qpassed[:50]!r}" if qpassed else " | quote=无"
                err_info = f" | ERROR: {tr['error']}" if tr.get("error") else ""
                print(f"    第{n}轮 [{pt}/{intent}]{quote_info}{err_info}")
                print(f"      trace : {trace}")
                print(f"      reply : {reply or '(无回复)'}")
    else:
        print("\n全部通过")


# ── 主流程（LangFuse 云端） ──
async def run_eval(dataset_name, filter_func, ids, max_concurrency, limit, dry_run):
    from langfuse import Langfuse
    lf = Langfuse()
    items = list(lf.get_dataset(dataset_name).items)
    print(f"加载 {len(items)} 条")
    if ids: items = [i for i in items if i.id in ids]; print(f"按 id 过滤: {len(items)} 条")
    if filter_func: items = [i for i in items if filter_func in (i.metadata or {}).get("test_function","")]; print(f"按 test_function 过滤: {len(items)} 条")
    if limit: items = items[:limit]; print(f"限制: {len(items)} 条")
    if dry_run:
        for item in items:
            inp = item.input if isinstance(item.input,dict) else json.loads(item.input)
            raw = "; ".join(t.get("raw_content","")[:60] for t in inp.get("turns",[])[:2])
            print(f"  {item.id}: {raw}")
        return
    print(f"开始实验 ({len(items)} 条, 并行 {max_concurrency})...\n")
    result = lf.run_experiment(
        name=f"option-eval-{time.strftime('%Y%m%d-%H%M%S')}", data=items,
        task=run_langgraph_pipeline, evaluators=[judge_by_deepseek], max_concurrency=max_concurrency)
    print(f"\n实验完成: {result.name}")
    _print_report(result.name, result)
    print(f"\nLangfuse: {os.environ.get('LANGFUSE_HOST','https://cloud.langfuse.com')}/project/{os.environ.get('LANGFUSE_PROJECT','otc-agent')}")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ids"); p.add_argument("--limit",type=int); p.add_argument("--filter")
    p.add_argument("--dataset",default=DATASET_NAME); p.add_argument("--concurrency",type=int,default=1)
    p.add_argument("--dry-run",action="store_true")
    p.add_argument("--no-judge",action="store_true",help="跳过 Judge 打分，只检查 reply_text 是否非空")
    p.add_argument("--local",default=None,help="本地 unified_golden.jsonl 路径（不走 LangFuse）")
    args = p.parse_args()
    id_list = [x.strip() for x in args.ids.split(",")] if args.ids else None
    if args.local:
        asyncio.run(run_local(args.local, args.filter, id_list, args.concurrency, args.limit, args.dry_run, args.no_judge))
    else:
        asyncio.run(run_eval(args.dataset, args.filter, id_list, args.concurrency, args.limit, args.dry_run))

if __name__ == "__main__": main()
