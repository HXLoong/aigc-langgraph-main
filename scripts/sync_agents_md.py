#!/usr/bin/env python3
"""把 Claude Code 的指令层渲染为 Codex 读取的 AGENTS.md 与 .agents/skills/（单一真源，生成物禁止手改）。

背景：团队主用 Codex。Codex 读仓库根与各级子目录的 AGENTS.md、`.agents/skills/<name>/SKILL.md`
（开放的 Agent Skills 标准，只要求 frontmatter `name` + `description`），不读
CLAUDE.md / .claude/rules / .claude/skills / .claude/agents。项目纪律都写在后者，所以：

    AGENTS.md                         = CLAUDE.md 正文 + 并入 .claude/rules/{prompt-management,testing,docs}.md
                                        + 其余 rules 只列路径（按需读取，控制上下文体积）
    <dir>/AGENTS.md                   = <dir>/CLAUDE.md（app/prompts、tests、scripts 三个陷阱页）
    .agents/skills/<name>/SKILL.md    = .claude/skills/<name>/SKILL.md（frontmatter 收敛为标准字段）
                                        + references/ 等子目录原样复制
    .agents/skills/<agent>/SKILL.md   = .claude/agents/<agent>.md（Codex 无 subagent，转为技能：
                                        调用时 agent 以该角色执行）

Claude Code 专有写法（"/xxx skill"）改写为"见 .claude/skills/xxx/SKILL.md"；`$1`/`$2` 参数约定加说明。

用法：
    python scripts/sync_agents_md.py            # 生成 / 覆盖全部产物
    python scripts/sync_agents_md.py --check    # 提交前自检：任一产物缺失或过期 → 退出码 1
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
#: 并入根 AGENTS.md 正文的规则（其余只列路径，避免 Codex 每次会话加载 800+ 行）
MERGED_RULES: tuple[str, ...] = ("prompt-management.md", "testing.md", "docs.md")
HEADER = (
    "<!-- 自动生成：python scripts/sync_agents_md.py —— 禁止手改。\n"
    "     真源是 {source}；改那里再重新生成，提交前跑 python scripts/sync_agents_md.py --check 校验同步。 -->\n\n"
)
SKILL_NOTE = (
    "> 自动生成自 `{source}`（python scripts/sync_agents_md.py），禁止手改。"
    "{args_note}\n\n"
)
ARGS_NOTE = " 文中 `$1`、`$2` 指调用本技能时用户按顺序给出的第 1、2 个参数。"

_SKILL_RE = re.compile(r"`?/([a-z0-9-]+)`? skill")
_FM_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def _generalize(text: str) -> str:
    text = _SKILL_RE.sub(lambda m: f"`.claude/skills/{m.group(1)}/SKILL.md` 流程", text)
    return text.replace("（让 Claude Code 帮你逐条检查）", "（让 agent 帮你逐条检查）")


def _first_heading(md: Path) -> str:
    for line in md.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return md.stem


# ============================================================
# AGENTS.md
# ============================================================


def render_root(root: Path) -> str:
    claude = (root / "CLAUDE.md").read_text(encoding="utf-8")
    rules_dir = root / ".claude" / "rules"
    parts = [HEADER.format(source="CLAUDE.md + .claude/rules/*.md"), _generalize(claude).rstrip(), ""]
    parts.append("\n---\n\n# 附一：并入正文的仓库规则（.claude/rules 原文）\n")
    for name in MERGED_RULES:
        rule = rules_dir / name
        if rule.exists():
            parts.append(f"\n<!-- 来源：.claude/rules/{name} -->\n")
            parts.append(_generalize(rule.read_text(encoding="utf-8")).rstrip() + "\n")
    others = [r for r in sorted(rules_dir.glob("*.md")) if r.name not in MERGED_RULES]
    if others:
        parts.append("\n# 附二：其余仓库规则（按需读取，同样具有约束力）\n")
        for r in others:
            parts.append(f"- `.claude/rules/{r.name}` — {_first_heading(r)}")
    return "\n".join(parts).rstrip() + "\n"


def render_nested(claude_md: Path) -> str:
    rel = claude_md.relative_to(PROJECT_ROOT).as_posix() if claude_md.is_relative_to(PROJECT_ROOT) else claude_md.name
    return HEADER.format(source=rel) + _generalize(claude_md.read_text(encoding="utf-8")).rstrip() + "\n"


# ============================================================
# .agents/skills/
# ============================================================


def _parse_frontmatter_lenient(block: str) -> dict:
    """Claude Code 的 frontmatter 解析很宽松（如 `argument-hint: [--limit N] ...` 不是合法 YAML），
    先试 YAML，失败则按 `key: value` 逐行解析（支持 `>` / `|` 折行块）。"""
    import yaml

    try:
        data = yaml.safe_load(block)
        if isinstance(data, dict):
            return data
    except yaml.YAMLError:
        pass
    data: dict = {}
    lines = block.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if ":" not in line or line.startswith((" ", "\t")):
            i += 1
            continue
        key, _, rest = line.partition(":")
        rest = rest.strip()
        if rest in (">", "|", ">-", "|-"):
            buf = []
            i += 1
            while i < len(lines) and lines[i].startswith((" ", "\t")):
                buf.append(lines[i].strip())
                i += 1
            data[key.strip()] = (" " if rest.startswith(">") else "\n").join(buf)
            continue
        data[key.strip()] = rest
        i += 1
    return data


def _split_frontmatter(text: str) -> tuple[dict, str]:
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    return _parse_frontmatter_lenient(m.group(1)), text[m.end():]


def _standard_frontmatter(name: str, description: str, source: str, extra: dict | None = None) -> str:
    import yaml

    fm: dict = {"name": name, "description": " ".join(str(description).split())}
    meta = {"source": source, **(extra or {})}
    fm["metadata"] = meta
    return "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, width=10_000).rstrip() + "\n---\n\n"


def _rel(path: Path, root: Path) -> str:
    """相对仓库根的路径；测试用临时目录时退化为从 `.claude/` 起的相对路径。"""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        parts = path.parts
        return "/".join(parts[parts.index(".claude"):]) if ".claude" in parts else path.name


def _root_of(path: Path, root: Path | None) -> Path:
    if root is not None:
        return root
    parts = path.parts
    return Path(*parts[: parts.index(".claude")]) if ".claude" in parts else PROJECT_ROOT


def render_skill(skill_md: Path, root: Path | None = None) -> str:
    root = _root_of(skill_md, root)
    data, body = _split_frontmatter(skill_md.read_text(encoding="utf-8"))
    source = _rel(skill_md, root)
    extra = {"argument_hint": data["argument-hint"]} if data.get("argument-hint") else {}
    args_note = ARGS_NOTE if "$1" in body else ""
    return (
        _standard_frontmatter(data.get("name", skill_md.parent.name), data.get("description", ""), source, extra)
        + SKILL_NOTE.format(source=source, args_note=args_note)
        + _generalize(body).lstrip("\n").rstrip()
        + "\n"
    )


def render_agent_as_skill(agent_md: Path, root: Path | None = None) -> str:
    root = _root_of(agent_md, root)
    data, body = _split_frontmatter(agent_md.read_text(encoding="utf-8"))
    source = _rel(agent_md, root)
    return (
        _standard_frontmatter(data.get("name", agent_md.stem), data.get("description", ""), source)
        + SKILL_NOTE.format(source=source, args_note="")
        + "> 原为 Claude Code subagent 定义；在 Codex 中作为技能调用时，请以下述角色与职责完成任务。\n\n"
        + _generalize(body).lstrip("\n").rstrip()
        + "\n"
    )


# ============================================================
# 产物集合
# ============================================================


def targets(root: Path) -> dict[Path, str]:
    """{产物路径: 应有内容}。"""
    out = {root / "AGENTS.md": render_root(root)}
    for claude_md in sorted(root.rglob("CLAUDE.md")):
        if claude_md.parent == root or ".venv" in claude_md.parts or "node_modules" in claude_md.parts:
            continue
        out[claude_md.parent / "AGENTS.md"] = render_nested(claude_md)
    skills_out = root / ".agents" / "skills"
    for skill_dir in sorted((root / ".claude" / "skills").glob("*/")):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        out[skills_out / skill_dir.name / "SKILL.md"] = render_skill(skill_md, root)
        for extra in sorted(skill_dir.rglob("*")):
            if extra.is_file() and extra != skill_md:
                out[skills_out / skill_dir.name / extra.relative_to(skill_dir)] = extra.read_text(encoding="utf-8")
    for agent_md in sorted((root / ".claude" / "agents").glob("*.md")):
        out[skills_out / agent_md.stem / "SKILL.md"] = render_agent_as_skill(agent_md, root)
    return out


def write_all(root: Path) -> list[Path]:
    written = []
    for path, content in targets(root).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


def check_all(root: Path) -> list[str]:
    errs = []
    for path, content in targets(root).items():
        rel = _rel(path, root)
        if not path.exists():
            errs.append(f"❌ {rel} 不存在（python scripts/sync_agents_md.py 生成）")
        elif path.read_text(encoding="utf-8") != content:
            errs.append(f"❌ {rel} 已过期，与 CLAUDE.md / .claude/ 不同步（重新生成后提交）")
    return errs


def main() -> int:
    parser = argparse.ArgumentParser(description="CLAUDE.md + .claude/ → AGENTS.md + .agents/skills/")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        errs = check_all(PROJECT_ROOT)
        for e in errs:
            print(e)
        print("✅ AGENTS.md / .agents/skills 与 CLAUDE.md / .claude 同步" if not errs else f"{len(errs)} 处不同步")
        return 1 if errs else 0
    for p in write_all(PROJECT_ROOT):
        print(f"写入 {p.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
