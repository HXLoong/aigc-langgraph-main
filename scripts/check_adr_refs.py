#!/usr/bin/env python3
"""ADR 一致性复检 lint（CI fast job）。

三项检查：
  1. ADR 互引虚悬——正文出现的 `ADR NNNN` 必须指向存在的文件；ADR 与 README 中的
     Markdown 相对链接（`./NNNN-*.md`、`../xxx.md` 等，忽略 URL 与页内锚点）目标必须存在
  2. ADR 引用代码路径存在性——反引号内的仓库路径必须存在；
     **跳过 ``~~删除线~~`` 段**（删除线标注的过期原文不参与检查）；
     行号后缀（`app/x.py:42`）与 glob/占位符（`*` `<` `{`）自动豁免
  3. 引用热度 / 孤儿 ADR 统计——信息性输出，不计入失败

跑法：
    python scripts/check_adr_refs.py            # 全部检查
    python scripts/check_adr_refs.py --json     # 机器可读
    python scripts/check_adr_refs.py --heat     # 附带打印引用热度与孤儿 ADR

退出码：
    0  全部通过
    1  发现虚悬引用或失效路径
    2  docs/adr 目录缺失

"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 反引号内的仓库相对路径（限这些顶级目录，避免误伤 URL / 包名）
_PATH_RX = re.compile(
    r"`((?:app|scripts|harness|tests|docs|infra|sql|dify)/"
    r"[A-Za-z0-9_.\-/]+\.(?:py|md|yaml|yml|json|jsonl|sql|sh|txt))"
    r"(?::[0-9,\-]+)?(?::[A-Za-z_][A-Za-z0-9_]*)?`"
)
_STRIKE_RX = re.compile(r"~~.*?~~", re.S)
_ADR_REF_RX = re.compile(r"ADR ?(0[0-9]{3})")
_REL_LINK_RX = re.compile(r"\]\(([^)\s#]*)(?:#[^)]*)?\)")


@dataclass(frozen=True)
class Finding:
    location: str  # "0001-xxx.md"
    detail: str


@dataclass
class CheckResult:
    dangling: list[Finding] = field(default_factory=list)
    missing_paths: list[Finding] = field(default_factory=list)
    heat: dict[str, int] = field(default_factory=dict)
    orphans: list[str] = field(default_factory=list)


def _adr_files(adr_dir: Path) -> list[Path]:
    return sorted(adr_dir.glob("00*.md"))


def _existing_numbers(adr_dir: Path) -> set[str]:
    return {p.name[:4] for p in _adr_files(adr_dir)}


def find_dangling_adr_refs(adr_dir: Path) -> list[Finding]:
    """检查 1：互引虚悬（编号引用 + ADR / README 中的相对链接目标）。"""
    known = _existing_numbers(adr_dir)
    findings: list[Finding] = []
    readme = adr_dir / "README.md"
    docs = _adr_files(adr_dir) + ([readme] if readme.exists() else [])
    for adr in docs:
        text = adr.read_text(encoding="utf-8")
        for num in sorted(set(_ADR_REF_RX.findall(text))):
            if num not in known:
                findings.append(Finding(adr.name, f"虚悬 ADR 引用: ADR {num}"))
        for target in sorted(set(_REL_LINK_RX.findall(text))):
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            if not (adr_dir / target).exists():
                findings.append(Finding(adr.name, f"相对链接目标不存在: {target}"))
    return findings


def find_missing_paths(adr_dir: Path, repo_root: Path) -> list[Finding]:
    """检查 2：反引号内仓库路径存在性（跳过删除线段）。"""
    findings: list[Finding] = []
    for adr in _adr_files(adr_dir):
        text = _STRIKE_RX.sub("", adr.read_text(encoding="utf-8"))
        for m in _PATH_RX.finditer(text):
            rel = m.group(1)
            if any(ch in rel for ch in "*<{"):
                continue
            if not (repo_root / rel).exists():
                findings.append(Finding(adr.name, f"引用路径不存在: {rel}"))
    return findings


def compute_heat(adr_dir: Path, repo_root: Path) -> tuple[dict[str, int], list[str]]:
    """检查 3：全仓引用热度（不含 ADR 自引）与孤儿 ADR。"""
    counter: Counter[str] = Counter()
    scan_dirs = ["docs", "app", "scripts", "harness", "tests"]
    for d in scan_dirs:
        base = repo_root / d
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.suffix not in {".py", ".md"} or not path.is_file():
                continue
            # 排除本 lint 自身与其测试（含虚构编号的测试夹具）
            if "check_adr_refs" in path.name:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for num in _ADR_REF_RX.findall(text):
                # ADR 文件自己引用自己不计
                if path.parent == adr_dir and path.name.startswith(num):
                    continue
                counter[num] += 1
    known = _existing_numbers(adr_dir)
    orphans = sorted(n for n in known if counter.get(n, 0) == 0)
    return dict(counter), orphans


def check_repo(repo_root: Path) -> CheckResult:
    adr_dir = repo_root / "docs" / "adr"
    if not adr_dir.exists():
        raise FileNotFoundError(f"ADR 目录不存在: {adr_dir}")
    result = CheckResult()
    result.dangling = find_dangling_adr_refs(adr_dir)
    result.missing_paths = find_missing_paths(adr_dir, repo_root)
    result.heat, result.orphans = compute_heat(adr_dir, repo_root)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ADR 一致性复检 lint")
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    parser.add_argument("--heat", action="store_true", help="打印引用热度与孤儿 ADR")
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT, help="仓库根目录")
    args = parser.parse_args(argv)

    try:
        result = check_repo(args.root)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    problems = result.dangling + result.missing_paths
    if args.json:
        print(
            json.dumps(
                {
                    "dangling": [f.__dict__ for f in result.dangling],
                    "missing_paths": [f.__dict__ for f in result.missing_paths],
                    "heat": result.heat,
                    "orphans": result.orphans,
                    "ok": not problems,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for f in problems:
            print(f"❌ {f.location}: {f.detail}")
        if args.heat:
            print("— 引用热度（次数 · ADR）—")
            for num, cnt in sorted(result.heat.items(), key=lambda kv: -kv[1]):
                print(f"  {cnt:4d} · ADR {num}")
            if result.orphans:
                print(f"⚠️ 孤儿 ADR（无任何外部引用，信息性提示）: {', '.join(result.orphans)}")
        if not problems:
            print("✅ ADR 互引与路径引用全部有效")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
