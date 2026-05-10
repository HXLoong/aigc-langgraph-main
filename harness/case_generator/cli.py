"""case_generator CLI：批量生成业务方种子收集模板。

用法：
    python -m harness.case_generator generate-seeds [--out-dir docs/m2-golden-seeds]
    python -m harness.case_generator list-nodes
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from harness.case_generator.seed_template import (
    NODE_REGISTRY,
    render_seed_template,
)


def _file_name(node_name: str) -> str:
    """node_name → 文件名（点号转中划线，更友好）。"""
    return node_name.replace(".", "-") + ".md"


def cmd_generate_seeds(out_dir: Path, num_slots: int = 8) -> int:
    """为 NODE_REGISTRY 中的每个节点生成种子收集模板。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[tuple[str, Path]] = []
    for node_name in sorted(NODE_REGISTRY.keys()):
        md = render_seed_template(node_name, num_slots=num_slots)
        fp = out_dir / _file_name(node_name)
        fp.write_text(md, encoding="utf-8")
        written.append((node_name, fp))

    # 生成索引页
    index_lines = [
        "# M2 Golden 种子收集索引",
        "",
        "> grill-with-docs 2026-05-10 第 4 决策落地 · 业务方填空",
        "",
        f"共 **{len(written)}** 个 M2 节点等待业务方种子。每个节点至少 6-8 条，",
        "总目标 ≥ 80 条以满足 P0 退出门（ADR 0001 D9.2）。",
        "",
        "## 节点列表",
        "",
        "| 节点 | product_type | 模板文件 |",
        "|---|---|---|",
    ]
    for node_name, fp in written:
        spec = NODE_REGISTRY[node_name]
        index_lines.append(
            f"| `{node_name}` | `{spec.product_type}` | [{fp.name}]({fp.name}) |"
        )
    index_lines.extend(
        [
            "",
            "## 填空指南",
            "",
            "- 每个文件含 8 个 case 槽位，至少填 6 条",
            "- 只标 `expected.product_type` + `expected.intent`，参数细节不标",
            "- 写完后由工程师转 jsonl 合入 `tests/fixtures/golden.jsonl`",
            "- 所有种子标 `source: business_seed`（B 桶 PASS 阈值 ≥ 90%）",
            "",
        ]
    )
    (out_dir / "README.md").write_text("\n".join(index_lines), encoding="utf-8")

    print(f"Wrote {len(written)} seed templates + 1 index to {out_dir}")
    for node_name, fp in written:
        print(f"  - {node_name} → {fp.name}")
    return 0


def cmd_list_nodes() -> int:
    """列出已注册的节点。"""
    print(f"Registered nodes ({len(NODE_REGISTRY)}):")
    for node_name in sorted(NODE_REGISTRY.keys()):
        spec = NODE_REGISTRY[node_name]
        print(f"  - {node_name:40s} {spec.product_type:14s} {spec.description}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness.case_generator")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_gen = sub.add_parser(
        "generate-seeds", help="批量生成业务方种子收集 markdown 模板"
    )
    p_gen.add_argument(
        "--out-dir",
        default="docs/m2-golden-seeds",
        type=Path,
        help="输出目录（默认 docs/m2-golden-seeds）",
    )
    p_gen.add_argument(
        "--num-slots",
        type=int,
        default=8,
        help="每个节点的 case 槽位数（默认 8）",
    )

    sub.add_parser("list-nodes", help="列出已注册的节点")

    args = parser.parse_args(argv)
    if args.cmd == "generate-seeds":
        return cmd_generate_seeds(args.out_dir, num_slots=args.num_slots)
    if args.cmd == "list-nodes":
        return cmd_list_nodes()
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
