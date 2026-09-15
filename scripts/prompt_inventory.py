#!/usr/bin/env python3
"""提示词清单 + 治理 lint（ADR 0022）。

`app/prompts/_manifest.yaml` 是"哪些 .md 活跃 / 灰度 / 非活跃"的机器可读真源，
本脚本据此产出清单并守四条不变量：

  1. 目录 ↔ manifest 双向无孤儿（新加 .md 必须登记；删 .md 必须注销）
  2. status=active 的条目：loader 文件存在且真的引用了该 name
  3. status=inactive 的条目：app/ 内零 load_prompt 引用，且登记了 reason
  4. status=gray（v2 灰度位）的条目：base（v1）自 v2 切出后未漂移
     （base_system_sha256 快照）；漂移必须写结构化 drift_acknowledged
     {at_base_sha: <确认时的 v1 sha>, note: ...}，v1 之后再变 → 必须重新 ack

另外做报告项（不 fail）：
  - 每文件 system / user 字符数、估算 tokens（字符 ÷ 1.6，与 swap 瘦身评估同口径）
  - 死重扫描：structured output 下失效的 JSON 格式禁令行数、Dify {{#...#}} 占位符数、
    无调用点的 [user] 段字符数
  - max_system_chars 预算（manifest 可选字段）超出 → fail
  - gray 条目 expires 到期未转正 → 警告
  - 上游漂移告警（ADR 0022 D1）：manifest `dify: {file, node_id, system_sha256}` 记录上次同步时
    Dify YAML 节点 system 的 sha；YAML 该节点变化 → 警告"上游有更新待人工 diff 合入"；
    YAML 里存在但 manifest 未映射的 llm 节点 → 警告；映射的 node 不存在 → 错误
  - --strict：悬空占位符（system 中未在 injects 登记的 {{#...#}}）与 structured output
    节点（有 output_model）里的 JSON 格式禁令 → fail（ADR 0022 D5 目标态，逐步收敛）

用法：
    python scripts/prompt_inventory.py            # 打印 markdown 清单 + lint 结果
    python scripts/prompt_inventory.py --check    # 仅 lint，退出码 0/1
    python scripts/prompt_inventory.py --check --strict   # 加严：悬空占位符 / JSON 禁令也 fail
    python scripts/prompt_inventory.py --json     # 机器可读清单

退出码：0 一致 / 1 有违反 / 2 manifest 缺失或解析失败
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = PROJECT_ROOT / "app" / "prompts"
MANIFEST = PROMPTS_DIR / "_manifest.yaml"

#: 与 app/prompts/__init__.py 的解析正则保持一致（闭合围栏须后跟下一节标题或文件尾）
_SYSTEM_RE = re.compile(
    r"##\s*\[system\]\s*\n+```[a-zA-Z]*\n(.*?)\n```(?=\s*(?:##\s*\[|\Z))", re.DOTALL
)
_USER_RE = re.compile(
    r"##\s*\[user\]\s*\n+```[a-zA-Z]*\n(.*?)\n```(?=\s*(?:##\s*\[|\Z))", re.DOTALL
)
_DIFY_PLACEHOLDER_RE = re.compile(r"\{\{#[^}]+#\}\}")
#: "只输出纯 JSON / 禁止 markdown 代码块" 之类的格式禁令——with_structured_output 下无从违反
_JSON_BAN_RE = re.compile(
    r"(纯\s*JSON|只输出\s*JSON|仅输出\s*JSON|不要输出\s*markdown|禁止.*```|"
    r"不要.*```|不得包含.*说明文字|不要有任何解释|JSON\s*格式输出，不要)",
    re.IGNORECASE,
)
#: 代码侧引用提示词的三种形态：load_prompt("cat", "name") /
#: resolve_prompt_version("cat", "name", ...) / 任意 helper("name")（如 _call_ticker_llm）
_LOAD_CALL_RE = re.compile(
    r"(?:load_prompt|resolve_prompt_version)\(\s*['\"]([\w/]+)['\"]\s*,\s*['\"](\w+)['\"]"
)

VALID_STATUS = {"active", "gray", "inactive"}
_DEFAULT_LOAD_CALLS = ("load_prompt", "resolve_prompt_version")
CHARS_PER_TOKEN = 1.6


# ============================================================
# 基础解析
# ============================================================


def split_md(text: str) -> tuple[str, str]:
    sm = _SYSTEM_RE.search(text)
    um = _USER_RE.search(text)
    return (sm.group(1).strip() if sm else ""), (um.group(1).strip() if um else "")


def system_sha256(md_path: Path) -> str:
    system, _ = split_md(md_path.read_text(encoding="utf-8"))
    return hashlib.sha256(system.encode("utf-8")).hexdigest()


def list_md_keys(prompts_dir: Path) -> list[str]:
    """`swap/intent` 形式的 key 列表（跳过 CLAUDE.md 与下划线前缀文件）。"""
    keys = []
    for p in sorted(prompts_dir.rglob("*.md")):
        if p.name in ("CLAUDE.md", "AGENTS.md") or p.name.startswith("_"):
            continue
        keys.append(str(p.relative_to(prompts_dir).with_suffix("")).replace("\\", "/"))
    return keys


def load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    import yaml

    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    prompts = data.get("prompts")
    return prompts if isinstance(prompts, dict) else {}


def _load_calls(project_root: Path) -> dict[str, list[str]]:
    """扫描 app/ + scripts/ + harness/ 的 load_prompt / resolve_prompt_version 字面量调用。

    返回 {key: [引用它的文件相对路径...]}。只统计 (category, name) 都是字面量的调用；
    动态 name（如 ticker 的 helper）由 check_loaders 用 loader 文件内的字面量 name 兜底。
    """
    refs: dict[str, list[str]] = {}
    for sub in ("app", "scripts", "harness"):
        base = project_root / sub
        if not base.exists():
            continue
        for py in base.rglob("*.py"):
            if py.parent == project_root / "app" / "prompts":
                continue  # 加载器自身的 docstring 示例不算引用
            text = py.read_text(encoding="utf-8", errors="ignore")
            for cat, name in _LOAD_CALL_RE.findall(text):
                refs.setdefault(f"{cat}/{name}", []).append(str(py.relative_to(project_root)))
    return refs


# ============================================================
# 不变量 1 · 目录 ↔ manifest 双向无孤儿
# ============================================================


def check_orphans(prompts_dir: Path, manifest: dict[str, dict[str, Any]]) -> list[str]:
    errs: list[str] = []
    on_disk = set(list_md_keys(prompts_dir))
    registered = set(manifest)
    for key in sorted(on_disk - registered):
        errs.append(
            f"❌ {key}.md 未登记到 app/prompts/_manifest.yaml"
            "（新提示词必须声明 status: active|gray|inactive）"
        )
    for key in sorted(registered - on_disk):
        errs.append(f"❌ manifest 条目 {key} 对应的 .md 不存在（删文件请同步注销）")
    for key, entry in manifest.items():
        status = (entry or {}).get("status")
        if status not in VALID_STATUS:
            errs.append(f"❌ {key} 的 status={status!r} 非法，应为 {sorted(VALID_STATUS)}")
    return errs


# ============================================================
# 不变量 2 / 3 · active 有真实加载点；inactive 零引用 + 有理由
# ============================================================


def _has_load_call(text: str, category: str, name: str, helper: str | None) -> bool:
    """loader 文件里是否真的有对该提示词的加载调用（而非任意同名字面量）。"""
    for fn in _DEFAULT_LOAD_CALLS:
        if re.search(rf"{fn}\(\s*['\"]{re.escape(category)}['\"]\s*,\s*['\"]{re.escape(name)}['\"]", text):
            return True
    return bool(helper and re.search(rf"{re.escape(helper)}\(\s*['\"]{re.escape(name)}['\"]", text))


def check_loaders(project_root: Path, manifest: dict[str, dict[str, Any]]) -> list[str]:
    errs: list[str] = []
    refs = _load_calls(project_root)
    for key, entry in manifest.items():
        entry = entry or {}
        status = entry.get("status")
        category, _, name = key.rpartition("/")
        if status == "active":
            loader = entry.get("loader")
            if not loader:
                errs.append(f"❌ {key} 为 active 但未声明 loader（引用它的 .py 相对路径）")
                continue
            loader_path = project_root / loader
            if not loader_path.exists():
                errs.append(f"❌ {key} 的 loader 文件不存在：{loader}")
                continue
            text = loader_path.read_text(encoding="utf-8", errors="ignore")
            if not _has_load_call(text, category, name, entry.get("loader_call")):
                errs.append(
                    f"❌ {key} 的 loader {loader} 未见 load_prompt/resolve_prompt_version(\"{category}\", \"{name}\")"
                    f" 或 loader_call helper 调用（是否已改名/去 LLM 化？）"
                )
        elif status == "inactive":
            if not entry.get("reason"):
                errs.append(f"❌ {key} 为 inactive 但未写 reason（保留理由 / 可删条件）")
            if key in refs:
                errs.append(f"❌ {key} 登记为 inactive 但仍被 {refs[key]} 加载")
    return errs


# ============================================================
# 不变量 4 · gray 相对 base 的漂移
# ============================================================


def check_gray_drift(prompts_dir: Path, manifest: dict[str, dict[str, Any]]) -> list[str]:
    errs: list[str] = []
    for key, entry in manifest.items():
        entry = entry or {}
        if entry.get("status") != "gray":
            continue
        base = entry.get("base")
        snapshot = entry.get("base_system_sha256")
        if not base or not snapshot:
            errs.append(f"❌ {key} 为 gray 但缺 base / base_system_sha256（切 v2 时 v1 的 system 快照）")
            continue
        base_path = prompts_dir / f"{base}.md"
        if not base_path.exists():
            errs.append(f"❌ {key} 的 base {base}.md 不存在")
            continue
        current = system_sha256(base_path)
        if current == snapshot:
            continue
        ack = entry.get("drift_acknowledged")
        if ack is not None and not isinstance(ack, dict):
            errs.append(
                f"❌ {key} 的 drift_acknowledged 必须是 {{at_base_sha: <确认时 v1 sha>, note: ...}}，"
                "字符串 ack 是永久静默开关，不接受"
            )
            continue
        acked_sha = (ack or {}).get("at_base_sha")
        if acked_sha == current:
            continue
        if acked_sha:
            errs.append(
                f"❌ {key} 的 base {base} 在上次 ack（at_base_sha={acked_sha[:8]}）之后再次被修改，"
                "必须重新 diff 并把 at_base_sha 更新为当前 v1 sha"
            )
        else:
            errs.append(
                f"❌ {key} 相对 base {base} 已漂移：v1 在 v2 切出后被修改，v2 缺少这些变更；"
                "放量前须重做 diff，并在 manifest 写 drift_acknowledged {at_base_sha, note}"
            )
    return errs


def check_gray_expiry(manifest: dict[str, dict[str, Any]], today: str) -> list[str]:
    """gray 条目 expires（ISO 日期）已过 → 警告（ADR 0003「>2 并存版本视为治理债」的可见化）。"""
    warns: list[str] = []
    for key, entry in manifest.items():
        entry = entry or {}
        if entry.get("status") != "gray":
            continue
        expires = entry.get("expires")
        if expires and str(expires) < today:
            warns.append(f"⚠️ {key} 灰度位已于 {expires} 到期仍未转正/删除（ADR 0003 治理债）")
    return warns


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def load_dify_llm_nodes(yaml_path: Path) -> dict[str, dict[str, str]]:
    """Dify 工作流 YAML → {node_id: {title, system}}（只取 llm 节点的 system 段）。"""
    import yaml

    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    nodes = (((data.get("workflow") or {}).get("graph") or {}).get("nodes")) or []
    out: dict[str, dict[str, str]] = {}
    for node in nodes:
        ndata = node.get("data") or {}
        if ndata.get("type") != "llm":
            continue
        system = ""
        for msg in ndata.get("prompt_template") or []:
            if msg.get("role") == "system":
                system = msg.get("text", "") or ""
        out[str(node.get("id"))] = {"title": ndata.get("title", ""), "system": system}
    return out


def check_upstream(yaml_dir: Path, manifest: dict[str, dict[str, Any]]) -> list[str]:
    """上游（Dify YAML）漂移告警：返回警告/错误文本列表；除"节点不存在"外均为告警不阻断。"""
    msgs: list[str] = []
    by_file: dict[str, dict[str, dict[str, str]]] = {}
    mapped: dict[str, set[str]] = {}
    for key, entry in manifest.items():
        dify = (entry or {}).get("dify")
        if not dify:
            continue
        fname = str(dify.get("file", ""))
        if fname not in by_file:
            path = yaml_dir / fname
            if not path.exists():
                msgs.append(f"❌ {key} 的 dify.file {fname} 不存在于 {yaml_dir}")
                by_file[fname] = {}
                continue
            by_file[fname] = load_dify_llm_nodes(path)
        node_id = str(dify.get("node_id", ""))
        mapped.setdefault(fname, set()).add(node_id)
        node = by_file[fname].get(node_id)
        if node is None:
            msgs.append(f"❌ {key} 映射的上游节点 {node_id} 不存在于 {fname}")
            continue
        current = text_sha256(node["system"])
        if current != dify.get("system_sha256"):
            msgs.append(
                f"⚠️ {key} 的上游 Dify 节点 {node_id}「{node['title']}」自上次同步后有更新，"
                f"待人工 diff 合入（合入后更新 dify.system_sha256={current[:12]}…）"
            )
    for fname, nodes in by_file.items():
        for node_id, node in nodes.items():
            if node_id not in mapped.get(fname, set()):
                msgs.append(
                    f"⚠️ {fname} 中 llm 节点 {node_id}「{node['title']}」未映射到任何 manifest 条目"
                    "（新增节点待迁移，或已去 LLM 化 → 在 manifest 用 inactive 条目记录）"
                )
    return msgs


# ============================================================
# 字符预算
# ============================================================


def check_budget(prompts_dir: Path, manifest: dict[str, dict[str, Any]]) -> list[str]:
    errs: list[str] = []
    for key, entry in manifest.items():
        entry = entry or {}
        limit = entry.get("max_system_chars")
        if not limit:
            continue
        p = prompts_dir / f"{key}.md"
        if not p.exists():
            continue
        system, _ = split_md(p.read_text(encoding="utf-8"))
        if len(system) > int(limit):
            errs.append(f"❌ {key} system 段 {len(system)} 字符，超出预算 {limit}")
    return errs


# ============================================================
# 报告项 · 死重扫描 + 清单
# ============================================================


def scan_dead_weight(md_path: Path) -> dict[str, Any]:
    text = md_path.read_text(encoding="utf-8")
    system, user = split_md(text)
    return {
        "system_chars": len(system),
        "user_chars": len(user),
        "est_tokens": round(len(system) / CHARS_PER_TOKEN),
        "json_format_ban_lines": sum(1 for ln in system.splitlines() if _JSON_BAN_RE.search(ln)),
        "dify_placeholders": len(set(_DIFY_PLACEHOLDER_RE.findall(system + "\n" + user))),
    }


def dangling_placeholders(md_path: Path, entry: dict[str, Any]) -> list[str]:
    """system 段里出现、但 manifest `injects` 未登记（即代码不会渲染）的 Dify 占位符。"""
    system, _ = split_md(md_path.read_text(encoding="utf-8"))
    found = set(_DIFY_PLACEHOLDER_RE.findall(system))
    injected = set(entry.get("injects") or [])
    return sorted(found - injected)


def check_strict(prompts_dir: Path, manifest: dict[str, dict[str, Any]]) -> list[str]:
    """--strict 加严项（ADR 0022 D5 目标态）：active 文件的悬空占位符 / structured output 下的 JSON 禁令。"""
    errs: list[str] = []
    for key, entry in manifest.items():
        entry = entry or {}
        if entry.get("status") != "active":
            continue
        p = prompts_dir / f"{key}.md"
        if not p.exists():
            continue
        dangling = dangling_placeholders(p, entry)
        if dangling:
            errs.append(f"❌ {key} 有 {len(dangling)} 个悬空占位符（代码未注入、LLM 看到的是变量名）：{dangling}")
        if entry.get("output_model"):
            bans = scan_dead_weight(p)["json_format_ban_lines"]
            if bans:
                errs.append(f"❌ {key} 走 structured output（{entry['output_model']}）却仍有 {bans} 行 JSON 格式禁令（死重）")
    return errs


def build_inventory(prompts_dir: Path, manifest: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for key in list_md_keys(prompts_dir):
        entry = manifest.get(key) or {}
        row = {"key": key, "status": entry.get("status", "unregistered"), "loader": entry.get("loader", "")}
        row.update(scan_dead_weight(prompts_dir / f"{key}.md"))
        row["dangling_placeholders"] = dangling_placeholders(prompts_dir / f"{key}.md", entry)
        if entry.get("status") == "gray":
            row["base"] = entry.get("base", "")
        if entry.get("status") == "inactive":
            row["reason"] = entry.get("reason", "")
        rows.append(row)
    return rows


def render_markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| 提示词 | 状态 | 加载点 | system 字符 | ≈tokens | JSON 禁令行 | 占位符(悬空) | user 段字符 |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| `{r['key']}` | {r['status']} | `{r['loader'] or r.get('base', '') or '-'}` | "
            f"{r['system_chars']:,} | {r['est_tokens']:,} | {r['json_format_ban_lines']} | "
            f"{r['dify_placeholders']}({len(r['dangling_placeholders'])}) | {r['user_chars']} |"
        )
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + r["system_chars"]
    lines.append("")
    lines.append("| 状态 | 文件数 | system 字符合计 | ≈tokens |")
    lines.append("|---|---:|---:|---:|")
    for status, chars in sorted(by_status.items()):
        n = sum(1 for r in rows if r["status"] == status)
        lines.append(f"| {status} | {n} | {chars:,} | {round(chars / CHARS_PER_TOKEN):,} |")
    return "\n".join(lines)


# ============================================================
# 主流程
# ============================================================


def run_checks(project_root: Path, prompts_dir: Path, manifest: dict[str, dict[str, Any]]) -> list[str]:
    return (
        check_orphans(prompts_dir, manifest)
        + check_loaders(project_root, manifest)
        + check_gray_drift(prompts_dir, manifest)
        + check_budget(prompts_dir, manifest)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="提示词清单 + 治理 lint（ADR 0022）")
    parser.add_argument("--check", action="store_true", help="只跑 lint，不打印清单")
    parser.add_argument("--json", action="store_true", help="输出机器可读清单")
    parser.add_argument("--strict", action="store_true", help="悬空占位符 / JSON 禁令也 fail")
    parser.add_argument("--today", default=None, help="ISO 日期，默认当天（测试用）")
    args = parser.parse_args()

    if not MANIFEST.exists():
        print(f"ERROR: 缺 {MANIFEST}", file=sys.stderr)
        return 2
    try:
        manifest = load_manifest(MANIFEST)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: 解析 {MANIFEST} 失败：{exc}", file=sys.stderr)
        return 2

    errs = run_checks(PROJECT_ROOT, PROMPTS_DIR, manifest)
    if args.strict:
        errs += check_strict(PROMPTS_DIR, manifest)
    from datetime import date

    warns = check_gray_expiry(manifest, args.today or date.today().isoformat())
    upstream = check_upstream(PROJECT_ROOT / "dify" / "yaml", manifest)
    errs += [m for m in upstream if m.startswith("❌")]
    warns += [m for m in upstream if m.startswith("⚠️")]
    if not args.check:
        rows = build_inventory(PROMPTS_DIR, manifest)
        print(json.dumps(rows, ensure_ascii=False, indent=1) if args.json else render_markdown(rows))
        print()
    for w in warns:
        print(w)
    for e in errs:
        print(e)
    if errs:
        print(f"\n{len(errs)} 处违反，见上")
        return 1
    print("✅ app/prompts 与 _manifest.yaml 一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
