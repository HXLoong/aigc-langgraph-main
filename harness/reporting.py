"""从保存的确定性结果生成逐轮报告，不执行模型、后端或重新评分。"""
from __future__ import annotations

import json
from typing import Any

from harness.evaluation import summarize


def value_type(value: Any) -> str:
    """区分字符串与数值等类型，避免把 10 和字符串 10 显示成相同结果。"""
    if value is None:
        return "空值"
    if isinstance(value, bool):
        return "布尔值"
    if isinstance(value, (int, float)):
        return "数值"
    if isinstance(value, str):
        return "字符串"
    return "数组" if isinstance(value, list) else "对象"


def json_text(value: Any) -> str:
    """保持 JSON 类型及完整原文，特殊对象仅用于诊断文本转换。"""
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _block(value: Any, language: str = "json") -> str:
    """使用比内容更长的围栏，防止输入中的 Markdown 打断报告结构。"""
    text = str(value) if language == "text" else json_text(value)
    fence = "```"
    while fence in text:
        fence += "`"
    return f"{fence}{language}\n{text}\n{fence}"


def _cell(value: Any) -> str:
    """表格单元只放概览，转义分隔符及换行；正文仍保存完整内容。"""
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def turn_reasons(turn: dict[str, Any]) -> list[str]:
    """从异常和原始字段差异解释失败；没有异常也可能是断言失败。"""
    reasons = []
    error = turn.get("error") or (turn.get("outputs") or {}).get("error")
    if error:
        reasons.append("执行错误：" + json_text(error))
    for diff in turn.get("diff") or []:
        expected, actual = diff.get("expected"), diff.get("actual")
        path = diff.get("path", "unknown")
        if path == "response_contains":
            reasons.append("实际回复缺少要求包含的文本：" + json_text(expected))
        elif path == "response_contains_any":
            reasons.append("实际回复未命中任一候选文本：" + json_text(expected))
        elif path == "response_not_contains":
            reasons.append("实际回复包含禁止文本：" + json_text(expected))
        else:
            reasons.append(f"{path}：预期 {json_text(expected)}（{value_type(expected)}），"
                           f"实际 {json_text(actual)}（{value_type(actual)}）")
    return reasons


def _turn_markdown(turn: dict[str, Any], *, executed: bool) -> list[str]:
    """一轮并列提供完整输入、引用、标注、回复、结构化输出与错误证据。"""
    lines = [f"### 第 {turn['turn']} 轮 · {turn.get('scene') or ''}", "",
             "#### 用户输入", "", _block(turn.get("raw", ""), "text"), ""]
    if "fast_query" in turn:
        lines += [f"入口标记：fast_query={turn['fast_query']}，at_bot={turn.get('at_bot')}；"
                  f"实际入口：{turn.get('entry_branch') or '未执行入口节点'}", ""]
    if turn.get("source_text") and turn["source_text"] != turn.get("raw"):
        lines += ["数据集原始文本（动态引用替换前）：", "", _block(turn["source_text"], "text"), ""]
    if not executed:
        lines += ["**未执行，没有实际输出。**", "", "停止原因：", "",
                  _block(turn.get("reason")), ""]
    else:
        lines += ["#### 完整引用上下文", "", _block(turn.get("quote_content") or "（无引用）", "text"), ""]
        if turn.get("quote_source"):
            lines += [f"引用来源：{turn['quote_source']}", ""]
        if turn.get("history"):
            lines += ["标注中的冻结历史上下文：", "", _block(turn["history"]), ""]
    lines += ["#### 预期输出（数据集原始标注）", "",
              "`expected` 是结构化字段约束；`response_contains` 要求全部包含，"
              "`response_contains_any` 要求至少命中一项，`response_not_contains` 为禁止内容。"
              "没有完整回复标注时，不补写完整预期回复。", "",
              _block(turn.get("assertions") or {}), ""]
    if executed:
        lines += ["#### 实际回复", "", _block(turn.get("reply") or "（没有用户回复，查看结构化输出）", "text"), "",
                  "#### 实际结构化输出（含业务参数和后端请求）", "", _block(turn.get("outputs") or {}), ""]
        if turn.get("model_failure_evidence"):
            lines += ["#### 失败模型原始输出（Langfuse Generation）", "",
                      _block(turn["model_failure_evidence"]), ""]
    reasons = turn_reasons(turn)
    lines += ["#### 具体错误原因与字段差异", "",
              _block(reasons if reasons else ["本轮没有记录到异常或字段差异；用例结论还需核对整体评分。"]), "",
              _block(turn.get("diff") or []), ""]
    if turn.get("trace_url"):
        lines += [f"[本轮 Langfuse Trace]({turn['trace_url']})", ""]
    return lines


def render_markdown(reports: list[dict[str, Any]]) -> str:
    """汇总后展开所有轮次，既展示失败证据，也保留通过用例的完整期望。"""
    summary = summarize(reports)
    lines = ["# Harness Regression Report", "",
             *(f"- {key}: {summary[field]}" for key, field in
               (("PASS", "passed"), ("FAIL", "failed"), ("REJECTED", "rejected"), ("TOTAL", "total"))), "",
             "| case | category | status | failure |", "|---|---|---|---|"]
    for report in reports:
        differences = sum(len(t.get("diff") or []) for t in report.get("turns", []))
        reason = report.get("failure") or (f"{differences} 项断言差异" if differences else "")
        lines.append(f"| `{_cell(report['case_id'])}` | `{_cell(report.get('category', ''))}` | "
                     f"{report['status']} | {_cell(reason)} |")
    for report in reports:
        lines += ["", f"## {report['case_id']} · {report['status']} · {report.get('name') or ''}", "",
                  f"数据来源：`{report.get('source_path') or ''}`；行号：{report.get('source_line') or ''}", ""]
        if report.get("analysis"):
            lines += ["本次证据核对：", "", _block(report["analysis"]), ""]
        if report.get("failure"):
            lines += ["用例执行错误：", "", _block(report["failure"]), ""]
        if report.get("evaluations"):
            lines += ["用例确定性评分：", "", _block(report["evaluations"]), ""]
        if report.get("case_diff"):
            lines += ["用例级断言差异：", "", _block(report["case_diff"]), ""]
        if not report.get("turns") and not report.get("unexecuted_turns"):
            # 初始化失败也保留已知输入/期望，不因缺少实际轮次而丢掉复核依据。
            lines += ["用例尚未返回实际轮次；原始输入：", "", _block(report.get("input")), "",
                      "原始预期输出：", "", _block(report.get("expected_output")), ""]
        for turn in report.get("turns", []):
            lines.extend(_turn_markdown(turn, executed=True))
        for turn in report.get("unexecuted_turns", []):
            lines.extend(_turn_markdown(turn, executed=False))
    return "\n".join(lines) + "\n"
