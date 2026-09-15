#!/usr/bin/env python3
"""把 CLAUDE.md + .claude/rules/*.md 渲染为 AGENTS.md（Codex 等 agent 读取的指令文件）。

背景：团队主用 Codex。Codex 读的是仓库根 AGENTS.md 与各级子目录 AGENTS.md，不读
CLAUDE.md / .claude/rules；而项目纪律（TDD、提示词治理 ADR 0022、红线）都写在后者。
为了只维护一份真源，AGENTS.md **全部由本脚本生成**，禁止手改：

    根 AGENTS.md            = CLAUDE.md 正文 + .claude/rules/*.md 逐篇追加（按文件名排序）
    <dir>/AGENTS.md         = <dir>/CLAUDE.md（app/prompts、tests、scripts 三个陷阱页）

Claude Code 专有写法（/xxx skill）会改写为"见 .claude/skills/<name>/SKILL.md"，Codex 可直接读该文件。

用法：
    python scripts/sync_agents_md.py            # 生成 / 覆盖全部 AGENTS.md
    python scripts/sync_agents_md.py --check    # CI：任一 AGENTS.md 缺失或过期 → 退出码 1
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HEADER = (
    "<!-- 自动生成：python scripts/sync_agents_md.py —— 禁止手改。\n"
    "     真源是 {source}；改那里再重新生成，CI（governance job）会校验同步。 -->\n\n"
)

#: Claude Code 专有写法 → 通用写法
_SKILL_RE = re.compile(r"`?/([a-z0-9-]+)`? skill")


def _generalize(text: str) -> str:
    text = _SKILL_RE.sub(lambda m: f"`.claude/skills/{m.group(1)}/SKILL.md` 流程", text)
    text = text.replace("（让 Claude Code 帮你逐条检查）", "（让 agent 帮你逐条检查）")
    return text


def render_root(root: Path) -> str:
    claude = (root / "CLAUDE.md").read_text(encoding="utf-8")
    parts = [HEADER.format(source="CLAUDE.md + .claude/rules/*.md"), _generalize(claude).rstrip(), ""]
    parts.append("\n---\n\n# 附：仓库规则（.claude/rules/*.md 原文）\n")
    for rule in sorted((root / ".claude" / "rules").glob("*.md")):
        parts.append(f"\n<!-- 来源：.claude/rules/{rule.name} -->\n")
        parts.append(_generalize(rule.read_text(encoding="utf-8")).rstrip() + "\n")
    return "\n".join(parts).rstrip() + "\n"


def render_nested(claude_md: Path) -> str:
    rel = claude_md.relative_to(PROJECT_ROOT).as_posix() if claude_md.is_relative_to(PROJECT_ROOT) else claude_md.name
    return HEADER.format(source=rel) + _generalize(claude_md.read_text(encoding="utf-8")).rstrip() + "\n"


def targets(root: Path) -> dict[Path, str]:
    """{AGENTS.md 路径: 应有内容}。"""
    out = {root / "AGENTS.md": render_root(root)}
    for claude_md in sorted(root.rglob("CLAUDE.md")):
        if claude_md.parent == root or ".venv" in claude_md.parts or "node_modules" in claude_md.parts:
            continue
        out[claude_md.parent / "AGENTS.md"] = render_nested(claude_md)
    return out


def write_all(root: Path) -> list[Path]:
    written = []
    for path, content in targets(root).items():
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


def check_all(root: Path) -> list[str]:
    errs = []
    for path, content in targets(root).items():
        rel = path.relative_to(root).as_posix()
        if not path.exists():
            errs.append(f"❌ {rel} 不存在（python scripts/sync_agents_md.py 生成）")
        elif path.read_text(encoding="utf-8") != content:
            errs.append(f"❌ {rel} 已过期，与 CLAUDE.md / .claude/rules 不同步（重新生成后提交）")
    return errs


def main() -> int:
    parser = argparse.ArgumentParser(description="CLAUDE.md + rules → AGENTS.md")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        errs = check_all(PROJECT_ROOT)
        for e in errs:
            print(e)
        print("✅ AGENTS.md 与 CLAUDE.md / .claude/rules 同步" if not errs else f"{len(errs)} 处不同步")
        return 1 if errs else 0
    for p in write_all(PROJECT_ROOT):
        print(f"写入 {p.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
