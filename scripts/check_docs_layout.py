#!/usr/bin/env python3
"""docs/ 存放规则 lint（CI fast job）。

规则真源：docs/README.md「存放规则」与 .claude/rules/docs.md。五项检查：
  1. 根目录布局——docs/ 根只放 README.md / work-plan.md，子目录只用白名单主题
  2. 目录索引——每个主题目录必须有 README.md
  3. 文件命名——小写 kebab-case（README.md 例外；`.` 分隔的后缀名允许）
  4. 一次性报告——文件名带日期的只能进 reports/，且 reports/ 下必须是 YYYY-MM-DD-<topic>.md
  5. 链接有效——docs 内 Markdown / HTML 相对链接；全仓文本对 `docs/...` 路径的引用

跑法：
    python scripts/check_docs_layout.py
    python scripts/check_docs_layout.py --json

退出码：0 全部通过；1 发现违规；2 docs 目录缺失
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

ALLOWED_ROOT_FILES: frozenset[str] = frozenset({"README.md", "work-plan.md"})
ALLOWED_TOPIC_DIRS: frozenset[str] = frozenset(
    {
        "adr",
        "agents",
        "api-contracts",
        "architecture",
        "deploy",
        "development",
        "langfuse",
        "operations",
        "reports",
        "testing",
        "training",
    }
)

_NAME_RX = re.compile(r"^[a-z0-9]+(?:[-.][a-z0-9]+)*$")
_DATE_RX = re.compile(r"(?<!\d)20\d{2}-\d{2}-\d{2}(?!\d)")
_REPORT_RX = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
_MD_LINK_RX = re.compile(r"\]\(<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\)")
_HTML_LINK_RX = re.compile(r"(?:href|src)=\"([^\"]+)\"")
# 仓库相对 docs 路径；前一个字符不能是路径或标识符字符，避免误伤 URL（x.com/docs/...）
_REPO_REF_RX = re.compile(r"(?<![\w./-])(docs/[A-Za-z0-9_./-]*[A-Za-z0-9_-]\.(?:md|html|png))")

_SCAN_SUFFIXES = {".md", ".py", ".sh", ".yml", ".yaml", ".toml", ".html", ".txt", ".ini"}
_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".harness-runs"}
# 本 lint 的测试文件里有故意写坏的路径
_SKIP_FILES = {"test_check_docs_layout.py"}


@dataclass(frozen=True)
class Finding:
    location: str
    detail: str


def _rel(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()


def _doc_files(docs: Path) -> list[Path]:
    return sorted(p for p in docs.rglob("*") if p.is_file() and p.name != ".DS_Store")


def check_root_layout(docs: Path) -> list[Finding]:
    """检查 1：根目录只放白名单文件与主题目录。"""
    findings: list[Finding] = []
    for entry in sorted(docs.iterdir()):
        if entry.is_file() and entry.name not in ALLOWED_ROOT_FILES:
            findings.append(Finding(f"docs/{entry.name}", "根目录不放散落文档，按主题归入子目录"))
        elif entry.is_dir() and entry.name not in ALLOWED_TOPIC_DIRS:
            findings.append(
                Finding(f"docs/{entry.name}/", "未登记的主题目录（白名单见 docs/README.md）")
            )
    return findings


def check_readmes(docs: Path) -> list[Finding]:
    """检查 2：每个主题目录有 README.md 索引。"""
    return [
        Finding(f"docs/{d.name}/", "主题目录缺 README.md 索引")
        for d in sorted(docs.iterdir())
        if d.is_dir() and not (d / "README.md").exists()
    ]


def check_file_names(docs: Path) -> list[Finding]:
    """检查 3：文件与目录名小写 kebab-case。"""
    findings: list[Finding] = []
    for path in sorted(docs.rglob("*")):
        if path.name == "README.md":
            continue
        stem = path.name if path.is_dir() else path.name.rsplit(".", 1)[0]
        if not _NAME_RX.match(stem):
            findings.append(Finding(f"docs/{_rel(path, docs)}", "命名须为小写 kebab-case"))
    return findings


def check_dated_names(docs: Path) -> list[Finding]:
    """检查 4：带日期的一次性报告只进 reports/，并以日期开头。"""
    findings: list[Finding] = []
    for path in _doc_files(docs):
        rel = _rel(path, docs)
        in_reports = rel.startswith("reports/")
        if in_reports:
            if path.name != "README.md" and not _REPORT_RX.match(path.name):
                findings.append(Finding(f"docs/{rel}", "reports/ 下须命名为 YYYY-MM-DD-<topic>.md"))
        elif _DATE_RX.search(path.name):
            findings.append(Finding(f"docs/{rel}", "带日期的一次性报告须放 docs/reports/"))
    return findings


def _is_external(target: str) -> bool:
    return (
        not target or target.startswith(("#", "mailto:", "data:", "javascript:")) or "://" in target
    )


def check_relative_links(docs: Path) -> list[Finding]:
    """检查 5a：docs 内 Markdown / HTML 相对链接目标存在。"""
    findings: list[Finding] = []
    for path in _doc_files(docs):
        if path.suffix == ".md":
            targets = _MD_LINK_RX.findall(path.read_text(encoding="utf-8"))
        elif path.suffix == ".html":
            targets = _HTML_LINK_RX.findall(path.read_text(encoding="utf-8"))
        else:
            continue
        for raw in sorted(set(targets)):
            if _is_external(raw):
                continue
            target = raw.split("#", 1)[0].split("?", 1)[0]
            if target and not (path.parent / target).exists():
                findings.append(Finding(f"docs/{_rel(path, docs)}", f"相对链接目标不存在: {raw}"))
    return findings


def _scan_files(root: Path) -> list[Path]:
    files: list[Path] = []
    stack = [root]
    while stack:
        current = stack.pop()
        for entry in current.iterdir():
            if entry.is_dir():
                if entry.name not in _SKIP_DIRS:
                    stack.append(entry)
            elif (
                entry.suffix in _SCAN_SUFFIXES or entry.name == "Dockerfile"
            ) and entry.name not in _SKIP_FILES:
                files.append(entry)
    return sorted(files)


def check_repo_refs(root: Path) -> list[Finding]:
    """检查 5b：全仓文本里 `docs/...` 仓库相对路径存在。"""
    findings: list[Finding] = []
    for path in _scan_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for ref in sorted(set(_REPO_REF_RX.findall(text))):
            if not (root / ref).exists():
                findings.append(Finding(_rel(path, root), f"引用的文档不存在: {ref}"))
    return findings


def check_repo(root: Path) -> list[Finding]:
    docs = root / "docs"
    if not docs.is_dir():
        raise FileNotFoundError(f"docs 目录不存在: {docs}")
    return (
        check_root_layout(docs)
        + check_readmes(docs)
        + check_file_names(docs)
        + check_dated_names(docs)
        + check_relative_links(docs)
        + check_repo_refs(root)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="docs/ 存放规则 lint")
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT, help="仓库根目录")
    args = parser.parse_args(argv)

    try:
        findings = check_repo(args.root)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        payload = {"findings": [asdict(f) for f in findings], "ok": not findings}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for f in findings:
            print(f"❌ {f.location}: {f.detail}")
        if not findings:
            print("✅ docs/ 布局、命名与链接全部符合存放规则")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
