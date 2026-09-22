#!/usr/bin/env python3
"""ADR 0019 §5 阈值变更程序的 CI lint。

校验三处文档之间的告警阈值数值一致：
  1. `app/observability/alerts.py:THRESHOLDS`（代码 · 真实生效）
  2. `docs/adr/0019-incident-severity-thresholds.md` §1 表（ADR 决策）
  3. `docs/on-call-runbook.md` §3 严重等级表（on-call 操作）

任一不一致 → exit 1 + 输出差异位置，避免"代码改了文档没跟上"
事故重演（ADR 0017 ↔ 0019 错位）。

跑法：
    python scripts/check_alert_threshold_consistency.py           # 全部检查
    python scripts/check_alert_threshold_consistency.py --json    # 机器可读
    python scripts/check_alert_threshold_consistency.py --verbose # 打印每条对比

退出码：
    0  全部对齐
    1  发现不一致（详见输出）
    2  文件缺失 / 解析失败
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALERTS_PY = PROJECT_ROOT / "app" / "observability" / "alerts.py"
ADR_0019 = PROJECT_ROOT / "docs" / "adr" / "0019-incident-severity-thresholds.md"
RUNBOOK = PROJECT_ROOT / "docs" / "on-call-runbook.md"


@dataclass(frozen=True)
class AlertSpec:
    """一个告警阈值的"事实"（用于跨源比对）。"""

    name: str
    severity: str  # P0 / P1 / P2
    threshold_value: float  # 单位由 kind 决定
    sustain_seconds: int


def _err(msg: str) -> None:
    """通过 stderr 报错（不污染 --json 主输出）。"""
    print(f"ERROR: {msg}", file=sys.stderr)


# ============================================================
# Source 1 · alerts.py THRESHOLDS（用 AST 解析，避免 import 环境依赖）
# ============================================================


def parse_alerts_py() -> dict[str, AlertSpec]:
    """从 alerts.py 抽 THRESHOLDS dict。

    用 AST 静态解析；不 import 模块，避免 M2_BASELINE_P95_MS env 影响 p95 数值
    （CI 跑时可能没设这个 env，会用代码默认 4200ms × 3 = 12600ms）。
    """
    if not ALERTS_PY.exists():
        _err(f"alerts.py 不存在: {ALERTS_PY}")
        sys.exit(2)

    tree = ast.parse(ALERTS_PY.read_text(encoding="utf-8"))

    # 找模块级常量：_P95_BASELINE_MS / _P95_MULTIPLIER / _P95_THRESHOLD_MS
    # 普通 Assign + 带注解 AnnAssign 都要扫
    consts: dict[str, float] = {}
    for node in ast.iter_child_nodes(tree):
        target_name: str | None = None
        value: ast.AST | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target_name = node.targets[0].id
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            target_name = node.target.id
            value = node.value
        if target_name is None or value is None:
            continue
        evaluated = _try_eval_const(value, consts)
        if evaluated is not None:
            consts[target_name] = evaluated

    # 找 THRESHOLDS = {...}（带类型注解，所以是 AnnAssign）
    for node in ast.walk(tree):
        target_name = None
        value = None
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            target_name = node.targets[0].id
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_name = node.target.id
            value = node.value
        if target_name == "THRESHOLDS" and isinstance(value, ast.Dict):
            return _parse_thresholds_dict(value, consts)

    _err("未在 alerts.py 找到 THRESHOLDS 定义")
    sys.exit(2)


def _try_eval_const(
    node: ast.AST, consts: dict[str, float]
) -> float | None:
    """尝试求值简单的常量表达式（数字字面量、命名常量、× / float() / os.environ.get)。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Name) and node.id in consts:
        return consts[node.id]
    # baseline = float(os.environ.get("M2_BASELINE_P95_MS", "4200"))
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "float"
        and node.args
    ):
        # 取 fallback 默认值
        inner = node.args[0]
        if (
            isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Attribute)
            and isinstance(inner.func.value, ast.Attribute)
            and getattr(inner.func.value, "attr", None) == "environ"
            and inner.func.attr == "get"
            and len(inner.args) >= 2
        ):
            default = inner.args[1]
            if isinstance(default, ast.Constant):
                try:
                    return float(default.value)
                except (TypeError, ValueError):
                    return None
        if isinstance(inner, ast.Constant):
            try:
                return float(inner.value)
            except (TypeError, ValueError):
                return None
        return None
    # baseline × multiplier
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        left = _try_eval_const(node.left, consts)
        right = _try_eval_const(node.right, consts)
        if left is not None and right is not None:
            return left * right
    return None


def _parse_thresholds_dict(
    node: ast.Dict, consts: dict[str, float]
) -> dict[str, AlertSpec]:
    """从 ast.Dict 解析 {name: AlertThreshold(...)} 结构。"""
    out: dict[str, AlertSpec] = {}
    for key_node, val_node in zip(node.keys, node.values):
        if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
            continue
        name = key_node.value
        if not (
            isinstance(val_node, ast.Call)
            and isinstance(val_node.func, ast.Name)
            and val_node.func.id == "AlertThreshold"
        ):
            continue
        kwargs: dict[str, ast.AST] = {kw.arg: kw.value for kw in val_node.keywords if kw.arg}
        severity = _get_str_kwarg(kwargs, "severity")
        threshold = _try_eval_const(kwargs.get("threshold_value"), consts) if "threshold_value" in kwargs else None
        sustain = _try_eval_const(kwargs.get("sustain_seconds"), consts) if "sustain_seconds" in kwargs else None
        if severity is None or threshold is None or sustain is None:
            _err(f"alerts.py 中告警 {name!r} 解析不全（severity={severity}, threshold={threshold}, sustain={sustain}）")
            sys.exit(2)
        out[name] = AlertSpec(
            name=name,
            severity=severity,
            threshold_value=threshold,
            sustain_seconds=int(sustain),
        )
    return out


def _get_str_kwarg(kwargs: dict[str, ast.AST], key: str) -> str | None:
    v = kwargs.get(key)
    if isinstance(v, ast.Constant) and isinstance(v.value, str):
        return v.value
    return None


# ============================================================
# Source 2 · ADR 0019 §1 表（Markdown 表格抽取）
# ============================================================


# 匹配形如：| `http_5xx_spike` | P0 | HTTP 5xx 率 ≥ 1% | 5 分钟 | ...
_ADR_ROW = re.compile(
    r"^\|\s*`(?P<name>[a-z0-9_]+)`\s*\|\s*(?P<sev>P[012])\s*\|"
    r"\s*(?P<thresh>[^|]+?)\s*\|\s*(?P<sustain>[^|]+?)\s*\|",
    re.M,
)


def parse_adr_0019() -> dict[str, AlertSpec]:
    """从 ADR 0019 §1 表抽阈值。

    格式约定：
      `name` | severity | 阈值文本（含 ≥ 数字 单位）| 持续文本（含分钟/秒）
    """
    if not ADR_0019.exists():
        _err(f"ADR 0019 不存在: {ADR_0019}")
        sys.exit(2)

    text = ADR_0019.read_text(encoding="utf-8")
    out: dict[str, AlertSpec] = {}
    for m in _ADR_ROW.finditer(text):
        name = m.group("name")
        sev = m.group("sev")
        thresh_text = m.group("thresh")
        sustain_text = m.group("sustain")
        thresh_value = _extract_threshold_value(thresh_text, name)
        sustain_sec = _extract_sustain_seconds(sustain_text)
        if thresh_value is None or sustain_sec is None:
            continue
        out[name] = AlertSpec(name, sev, thresh_value, sustain_sec)
    return out


def _extract_threshold_value(text: str, alert_name: str) -> float | None:
    """从阈值文本抽数字。优先级：≥ N% / ≥ N ms / ≥ N 计数。"""
    # ratio 百分比："≥ 1%" "≥ 5%" "≥ 10%"
    m = re.search(r"≥\s*([\d.]+)\s*%", text)
    if m:
        return float(m.group(1))
    # absolute ms："≥ 12600ms"
    m = re.search(r"≥\s*([\d.]+)\s*ms", text)
    if m:
        return float(m.group(1))
    # 计数 "≥ 1"（不带 %）
    m = re.search(r"≥\s*([\d.]+)\b", text)
    if m and "%" not in text and "ms" not in text:
        # 这是 non_canary_traffic 类型，约定为 0.0 阈值（"任何流量都告警"）
        # alerts.py 用 threshold_value=0.0 表示
        return 0.0
    return None


def _extract_sustain_seconds(text: str) -> int | None:
    """从持续文本抽秒数。'5 分钟' → 300, '即时（0 秒）' → 0。"""
    if "即时" in text or "0 秒" in text:
        return 0
    m = re.search(r"([\d.]+)\s*分钟", text)
    if m:
        return int(float(m.group(1)) * 60)
    m = re.search(r"([\d.]+)\s*秒", text)
    if m:
        return int(float(m.group(1)))
    return None


# ============================================================
# Source 3 · runbook §3 严重等级表（按 P0/P1 块解析）
# ============================================================


# runbook §3 的格式是合并多条触发条件到一行：
# | **P0** | · HTTP 5xx 率 ≥ 1% 持续 5 分钟<br>· Java 后端不可达...
# 我们只校验"可机器化的"4 条（与 alerts.py THRESHOLDS 5 条中 ratio 类对齐；
# p95_latency_degraded 在 runbook 是人工判定段，不在 §3 P0/P1 主表）。

# (alert_name, 在 runbook 中的关键词)
_RUNBOOK_KEYWORDS: dict[str, str] = {
    "http_5xx_spike": "HTTP 5xx 率 ≥",
    "cascade_fail_high": "Cascade fail 率 ≥",
    "llm_failure_high": "LLM 失败率 ≥",
    # 2026-08-27 裁决：runbook §3 P0 行已补 non_canary_traffic，解除豁免
    "non_canary_traffic": "非金丝雀流量泄漏 ≥",
    # p95_latency_degraded 在 runbook §3 有 P95 ≥ M2 baseline × 3 条目
    "p95_latency_degraded": "P95 延迟 ≥ M2 baseline",
}


def parse_runbook() -> dict[str, AlertSpec]:
    """从 runbook §3 严重等级表抽阈值（按关键词在 P0/P1 块匹配）。"""
    if not RUNBOOK.exists():
        _err(f"runbook 不存在: {RUNBOOK}")
        sys.exit(2)

    text = RUNBOOK.read_text(encoding="utf-8")
    # 切出 §3 严重等级段
    sev3_idx = text.find("## 3. 严重等级")
    sev4_idx = text.find("## 4.")
    if sev3_idx < 0 or sev4_idx < 0:
        _err("runbook §3 / §4 段找不到")
        sys.exit(2)
    section = text[sev3_idx:sev4_idx]

    out: dict[str, AlertSpec] = {}
    for alert_name, keyword in _RUNBOOK_KEYWORDS.items():
        # 找到包含 keyword 的行 + 推断 severity（从段内的 P0/P1 块前缀）
        kw_idx = section.find(keyword)
        if kw_idx < 0:
            continue
        # 向前找最近的 **P0** / **P1** / **P2** 块标记
        prefix = section[:kw_idx]
        sev_match = list(re.finditer(r"\*\*(P[012])\*\*", prefix))
        if not sev_match:
            continue
        severity = sev_match[-1].group(1)

        # 抽 keyword 之后的"≥ N% 持续 N 分钟" / "≥ M2 baseline × N 持续 N 分钟"
        # 截到当前 bullet 结束（<br>），避免相邻条目的"即时/N 分钟"串扰
        suffix = section[kw_idx : kw_idx + 200].split("<br>")[0]
        thresh_value = _extract_threshold_value(suffix, alert_name)
        # 对 P95：M2 baseline × N → 直接用代码侧的实际值（不在 runbook 文本里写绝对 ms）
        # 这里通过 multiplier 抽 → 由外部对账时与 alerts.py 比 multiplier 一致即可
        # 简化：runbook 不写绝对 ms，本检查只比 severity + sustain。threshold 用占位。
        if alert_name == "p95_latency_degraded":
            # 抽 × N 的 N
            mx = re.search(r"M2 baseline\s*×\s*(\d+)", suffix)
            if mx:
                thresh_value = float(mx.group(1))  # 用倍数当 placeholder
            else:
                thresh_value = None
        sustain_sec = _extract_sustain_seconds(suffix)
        if thresh_value is None or sustain_sec is None:
            continue
        out[alert_name] = AlertSpec(alert_name, severity, thresh_value, sustain_sec)
    return out


# ============================================================
# 比对
# ============================================================


@dataclass
class Diff:
    """一项不一致。"""

    alert_name: str
    field: str  # severity / threshold_value / sustain_seconds
    source_a: str
    value_a: object
    source_b: str
    value_b: object

    def __str__(self) -> str:
        return (
            f"❌ {self.alert_name}.{self.field}: "
            f"{self.source_a}={self.value_a!r} ≠ {self.source_b}={self.value_b!r}"
        )


def compare(
    name_a: str, a: dict[str, AlertSpec],
    name_b: str, b: dict[str, AlertSpec],
    *, skip_threshold_value_for: set[str] | None = None,
) -> list[Diff]:
    """两两比对：只检查两个 source 都有的 alert。

    Args:
        skip_threshold_value_for: 比对时跳过 threshold_value 字段的 alert name
            （runbook 用 multiplier 占位，与 alerts.py 的绝对 ms 不可直接比，
             由 ADR 0019 ↔ alerts.py 那对独立保证 ms 一致即可）
    """
    skip = skip_threshold_value_for or set()
    diffs: list[Diff] = []
    common = a.keys() & b.keys()
    for n in sorted(common):
        sa, sb = a[n], b[n]
        if sa.severity != sb.severity:
            diffs.append(Diff(n, "severity", name_a, sa.severity, name_b, sb.severity))
        if n not in skip and sa.threshold_value != sb.threshold_value:
            diffs.append(Diff(
                n, "threshold_value", name_a, sa.threshold_value, name_b, sb.threshold_value,
            ))
        if sa.sustain_seconds != sb.sustain_seconds:
            diffs.append(Diff(
                n, "sustain_seconds", name_a, sa.sustain_seconds, name_b, sb.sustain_seconds,
            ))
    return diffs


# ============================================================
# CLI
# ============================================================


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ADR 0019 §5 阈值变更程序的 CI lint"
    )
    parser.add_argument("--json", action="store_true", help="机器可读 JSON 输出")
    parser.add_argument("--verbose", "-v", action="store_true", help="打印每条对比")
    args = parser.parse_args()

    alerts = parse_alerts_py()
    adr = parse_adr_0019()
    runbook = parse_runbook()

    if args.verbose:
        for src, data in [("alerts.py", alerts), ("ADR 0019", adr), ("runbook", runbook)]:
            print(f"\n=== {src} ===")
            for n in sorted(data):
                s = data[n]
                print(f"  {n}: sev={s.severity} thresh={s.threshold_value} sustain={s.sustain_seconds}s")

    # 比对 alerts.py ↔ ADR 0019（精确比，含 threshold_value）
    diffs1 = compare("alerts.py", alerts, "ADR 0019", adr)
    # 比对 alerts.py ↔ runbook（跳过 P95 threshold_value，runbook 用倍数占位）
    diffs2 = compare(
        "alerts.py", alerts, "runbook", runbook,
        skip_threshold_value_for={"p95_latency_degraded"},
    )

    all_diffs = diffs1 + diffs2

    if args.json:
        out = {
            "alerts_py_vs_adr_0019": [d.__dict__ for d in diffs1],
            "alerts_py_vs_runbook": [d.__dict__ for d in diffs2],
            "ok": not all_diffs,
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if not all_diffs else 1

    if not all_diffs:
        print("✅ 三处阈值全部对齐（alerts.py / ADR 0019 / runbook）")
        # 列出各 source 覆盖的告警数
        print(f"   · alerts.py: {len(alerts)} 个告警")
        print(f"   · ADR 0019: {len(adr)} 个告警")
        print(f"   · runbook §3: {len(runbook)} 个告警")
        return 0

    print(f"❌ 发现 {len(all_diffs)} 项不一致：")
    print()
    print("--- alerts.py ↔ ADR 0019 ---")
    for d in diffs1:
        print(f"  {d}")
    if not diffs1:
        print("  ✅ 对齐")
    print()
    print("--- alerts.py ↔ runbook ---")
    for d in diffs2:
        print(f"  {d}")
    if not diffs2:
        print("  ✅ 对齐")
    print()
    print("修复参考 ADR 0019 §5 阈值变更程序：四处同步")
    return 1


if __name__ == "__main__":
    sys.exit(main())
