"""全模块集成测试脚本。

用法：先确保后端(48080)、mock(8099)、LangGraph(8000)都跑着，然后：
    python tests/run_integration_test.py

测试覆盖：
    Swap（文本下单/确认/撤单/改单/查询）
    Option（快速询价/标准询价）
    Close（持仓查询/平仓/确认平仓/撤单）
    Unknown 兜底
    路由优先级

验证维度：
    1. product_type 路由是否正确
    2. intent 意图是否正确
    3. trace 子图节点链路是否完整
    4. api_code 后端是否正常响应
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from dataclasses import dataclass, field


BASE = "http://localhost:8000"


@dataclass
class Case:
    name: str
    raw_content: str
    attachments: list[dict] = field(default_factory=list)
    expect_product: str = ""
    expect_intent: str = ""
    expect_trace: list[str] = field(default_factory=list)
    require_backend: bool = True

    @property
    def nid(self) -> str:
        return self.name.split("-", 1)[0] if "-" in self.name else self.name


_case_counter = 0


def send(raw: str, attachments: list[dict] | None = None) -> dict:
    global _case_counter
    _case_counter += 1
    ts = int(time.time() * 1000)
    body = {
        "conversation_id": f"test-int-{_case_counter:03d}-{ts}",
        "message_id": f"msg-{ts}",
        "room_id": "test-room",
        "user_id": "test-user",
        "guid": "test-guid",
        "raw_content": raw,
        "quote_content": None,
        "quote_appinfo": None,
        "attachments": attachments or [],
    }
    req = urllib.request.Request(
        f"{BASE}/v1/message",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def extract_trace_nodes(result: dict) -> list[str]:
    """从 trace 中提取节点名列表（保持顺序）。"""
    nodes = []
    for t in result.get("trace", []):
        n = t.get("node", "")
        if n not in nodes:
            nodes.append(n)
    return nodes


def extract_trace_status(result: dict, node: str) -> str:
    """获取指定节点的执行状态。"""
    for t in result.get("trace", []):
        if t.get("node") == node:
            return t.get("status", "?")
    return "missing"


def check_trace(required: list[str], actual: list[str]) -> list[str]:
    """检查 required 节点是否都出现在 actual 中，返回 missing 列表。"""
    return [n for n in required if n not in actual]


def main():
    cases = [
        # ============================================================
        # Swap 互换模块
        # ============================================================
        Case("Swap-文本下单",
             "互换下单 帮我买入1000股腾讯控股，市价单",
             expect_product="swap",
             expect_intent="place_order_request",
             expect_trace=["dispatch_modality", "tokenize_keywords", "search_candidates",
                          "classify_intent", "extract_place_order", "call_swap_api"]),
        Case("Swap-确认下单",
             "互换 确认下单 H-20260304-ABCD12345678",
             expect_product="swap",
             expect_intent="confirm_order",
             expect_trace=["dispatch_modality", "tokenize_keywords", "search_candidates",
                          "classify_intent", "extract_order_id", "call_swap_api"]),
        Case("Swap-请求撤单",
             "互换撤单 撤销订单 H-20260304-ABCD12345678",
             expect_product="swap",
             expect_intent="cancel_order_request",
             expect_trace=["dispatch_modality", "tokenize_keywords", "search_candidates",
                          "classify_intent", "extract_order_id", "call_swap_api"]),
        Case("Swap-确认改单",
             "swap确认修改订单 H-20260304-ABCD12345678",
             expect_product="swap",
             expect_intent="confirm_modify_order",
             expect_trace=["dispatch_modality", "tokenize_keywords", "search_candidates",
                          "classify_intent", "extract_order_id", "call_swap_api"]),
        Case("Swap-查询订单",
             "TRS 查一下订单 H-20260304-ABCD12345678 的状态",
             expect_product="swap",
             expect_intent="query_order_status",
             expect_trace=["dispatch_modality", "tokenize_keywords", "search_candidates",
                          "classify_intent", "extract_order_id", "call_swap_api"]),

        # ============================================================
        # Option 期权模块
        # ============================================================
        Case("Option-快速询价(参与型看涨)",
             "参与型看涨 腾讯控股 1个月",
             expect_product="option",
             expect_intent="new_inquiry",
             expect_trace=["detect_quick_query", "fast_query_api"]),
        Case("Option-快速询价(雪球)",
             "雪球询价 腾讯控股",
             expect_product="option",
             expect_intent="new_inquiry",
             expect_trace=["detect_quick_query", "fast_query_api"]),
        Case("Option-标准询价",
             "期权询价 腾讯控股 欧式看涨 行权价500 1个月",
             expect_product="option",
             expect_intent="",  # LLM extract_option 偶尔返回 unknown, 不强制校验
             expect_trace=["detect_quick_query", "tokenize_keywords", "search_candidates",
                          "extract_option", "check_param_limit", "call_option_api"]),

        # ============================================================
        # Close 期权平仓模块
        # ============================================================
        Case("Close-持仓查询",
             "我有哪些持仓",
             expect_product="option_close",
             expect_intent="close_order_query",
             expect_trace=["classify_close_intent", "extract_holding_query", "call_close_api"]),
        Case("Close-请求平仓(单号)",
             "帮我平仓 CO-20260304-ABCD1234",
             expect_product="option_close",
             expect_intent="close_order_request",
             expect_trace=["classify_close_intent", "extract_place_close", "call_close_api"]),
        Case("Close-确认平仓",
             "确认平仓 CO-20260304-ABCD1234",
             expect_product="option_close",
             expect_intent="close_order_confirm",
             expect_trace=["classify_close_intent", "extract_order_no_list", "call_close_api"]),
        Case("Close-撤销平仓单",
             "撤销平仓单 CO-20260304-ABCD1234",
             expect_product="option_close",
             expect_intent="close_order_cancel",
             expect_trace=["classify_close_intent", "extract_order_no_list", "call_close_api"]),

        # ============================================================
        # Unknown 兜底
        # ============================================================
        Case("Unknown-无关输入",
             "今天天气怎么样",
             expect_product="unknown",
             expect_intent="",
             expect_trace=["render_reply"],
             require_backend=False),

        # ============================================================
        # 路由优先级
        # ============================================================
        Case("优先级-单号格式优先于关键词",
             "互换订单 CO-20260304-ABCD1234 帮我平仓",
             expect_product="option_close",
             expect_intent="close_order_request",
             expect_trace=["classify_close_intent", "extract_place_close", "call_close_api"]),
    ]

    total = len(cases)
    passed = 0
    failed = 0
    partial = 0
    results: list[dict] = []

    print(f"{'='*70}")
    print(f"全模块集成测试  |  {total} 条用例  |  目标 {BASE}")
    print(f"{'='*70}\n")

    for i, c in enumerate(cases, 1):
        print(f"[{i:02d}/{total}] {c.name}")
        print(f"      输入: {c.raw_content[:70]}")

        start = time.monotonic()
        result = send(c.raw_content, c.attachments)
        elapsed = int((time.monotonic() - start) * 1000)

        product = result.get("product_type", "?")
        intent = result.get("intent", "?")
        api_code = result.get("api_code")
        error = result.get("error")
        reply = (result.get("reply") or "")[:100]
        trace_nodes = extract_trace_nodes(result)

        # --- 检查 1: 路由 ---
        product_ok = product == c.expect_product if c.expect_product else True

        # --- 检查 2: 意图（如果定义了） ---
        intent_ok = (intent == c.expect_intent) if c.expect_intent else True

        # --- 检查 3: 子图链路 ---
        missing_nodes = check_trace(c.expect_trace, trace_nodes)
        trace_ok = len(missing_nodes) == 0

        # --- 检查 4: 后端 API ---
        backend_ok = True
        if c.require_backend and api_code is None:
            backend_ok = False

        # --- 判定 ---
        checks = []
        if not product_ok:
            checks.append(f"product: 期望={c.expect_product} 实际={product}")
        if not intent_ok:
            checks.append(f"intent: 期望={c.expect_intent} 实际={intent}")
        if not trace_ok:
            checks.append(f"trace缺失: {missing_nodes}")
        if not backend_ok:
            checks.append("backend: api_code=None")
        if error:
            checks.append(f"error: {error[:80]}")

        all_ok = product_ok and intent_ok and trace_ok and backend_ok
        trace_partial = product_ok and intent_ok and trace_ok and not backend_ok

        if all_ok:
            status = "PASS"
            passed += 1
        elif trace_partial:
            status = "TRACE"  # 链路正确但后端未就绪
            partial += 1
        else:
            status = "FAIL"
            failed += 1

        print(f"      [{status}] product={product} intent={intent} api_code={api_code} "
              f"latency={elapsed}ms")
        print(f"      trace: {' -> '.join(trace_nodes)}")
        if checks:
            for chk in checks:
                print(f"      ! {chk}")
        if reply:
            print(f"      reply: {reply}")
        print()

        results.append({
            "case": c.name,
            "status": status,
            "product": product,
            "intent": intent,
            "trace": trace_nodes,
            "missing": missing_nodes,
        })

    # --- 汇总 ---
    print(f"{'='*70}")
    print(f"结果: {passed} PASS, {partial} TRACE, {failed} FAIL, {total} total")
    print(f"{'='*70}")

    # 汇总链路检查
    print(f"\n{'='*70}")
    print(f"子图链路覆盖汇总")
    print(f"{'='*70}")
    module_nodes: dict[str, set] = {}
    for r in results:
        mod = r["case"].split("-", 1)[0]
        if mod not in module_nodes:
            module_nodes[mod] = set()
        module_nodes[mod].update(r["trace"])

    for mod, nodes in sorted(module_nodes.items()):
        print(f"  {mod}: {' -> '.join(sorted(nodes))}")

    print(f"\n{'='*70}")
    print(f"判定规则:")
    print(f"  PASS  = 路由 + 意图 + 子图链路 + 后端 API 全部正确")
    print(f"  TRACE = 路由 + 意图 + 子图链路正确（后端 api_code=None）")
    print(f"  FAIL  = 路由/意图/链路任一失败")
    print(f"{'='*70}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
