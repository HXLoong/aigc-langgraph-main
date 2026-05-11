"""case_generator CLI：批量生成业务方种子收集模板 + LLM 对抗式 paraphrase。

用法：
    python -m harness.case_generator generate-seeds [--out-dir docs/m2-golden-seeds]
    python -m harness.case_generator list-nodes
    python -m harness.case_generator paraphrase [--num 3] [--out docs/m2-llm-generated-cases.md]
"""
from __future__ import annotations

import argparse
import asyncio
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


async def _cmd_paraphrase_async(
    out_path: Path, num_variants: int, golden_path: Path
) -> int:
    """LLM 对抗式 paraphrase 子命令。"""
    from harness.case_generator.llm_paraphrase import (
        paraphrase_case,
        render_review_markdown,
    )
    from harness.golden import load_golden

    seeds = load_golden(golden_path)
    if not seeds:
        print(f"ERROR: no golden cases at {golden_path}", file=sys.stderr)
        return 2

    # 仅对 business_seed 来源的种子做 paraphrase（不对 LLM 生成的再 paraphrase）
    business_seeds = [
        s for s in seeds if getattr(s, "source", "business_seed") == "business_seed"
    ]
    print(f"paraphrasing {len(business_seeds)} business seeds, {num_variants} variants each ...")

    pairs: list[tuple] = []
    for i, seed in enumerate(business_seeds, 1):
        print(f"  [{i}/{len(business_seeds)}] {seed.id} ({seed.category}) ...", flush=True)
        try:
            variants = await paraphrase_case(seed, num_variants=num_variants)
            pairs.append((seed, variants))
        except Exception as exc:
            print(f"    SKIP: {exc}", file=sys.stderr)

    md = render_review_markdown(pairs)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")

    total_variants = sum(len(v) for _, v in pairs)
    print(f"\nGenerated {total_variants} variants from {len(pairs)} seeds")
    print(f"Review checklist → {out_path}")
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

    p_para = sub.add_parser(
        "paraphrase",
        help="LLM 对抗式生成候选 case（business_seed → llm_paraphrase 候选）",
    )
    p_para.add_argument(
        "--out",
        default="docs/m2-llm-generated-cases.md",
        type=Path,
        help="输出 review 候选清单 markdown（默认 docs/m2-llm-generated-cases.md）",
    )
    p_para.add_argument(
        "--num",
        type=int,
        default=3,
        help="每条种子生成的变体数（默认 3）",
    )
    p_para.add_argument(
        "--golden",
        default="tests/fixtures/golden.jsonl",
        type=Path,
        help="种子来源 golden.jsonl 路径",
    )

    args = parser.parse_args(argv)
    if args.cmd == "generate-seeds":
        return cmd_generate_seeds(args.out_dir, num_slots=args.num_slots)
    if args.cmd == "list-nodes":
        return cmd_list_nodes()
    if args.cmd == "paraphrase":
        return asyncio.run(
            _cmd_paraphrase_async(args.out, args.num, args.golden)
        )
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
