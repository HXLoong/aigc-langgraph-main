#!/usr/bin/env python3
"""从 Dify YAML 批量提取所有 LLM 节点的 system/user prompt。

用法:
    python scripts/export_dify_prompts.py path/to/dify-yamls/ output/prompts/

输出:
    output/prompts/
    ├── main/
    │   ├── swap_intent_classifier.md
    │   ├── swap_place_order.md
    │   └── ...
    ├── option_tool/
    └── ticker_inference/
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("请先安装 PyYAML: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


def sanitize_filename(name: str) -> str:
    """把节点标题转成合法的文件名。"""
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"\s+", "_", name.strip())
    return name.lower()[:80]


def extract_prompts_from_yaml(yaml_path: Path) -> list[dict]:
    """从单个 YAML 中提取所有 LLM 节点的提示词。"""
    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    workflow = data.get("workflow") or {}
    graph = workflow.get("graph") or {}
    nodes = graph.get("nodes") or []

    prompts = []
    for node in nodes:
        ndata = node.get("data") or {}
        if ndata.get("type") != "llm":
            continue

        title = ndata.get("title", "untitled")
        model = ndata.get("model") or {}
        model_name = model.get("name", "unknown")
        prompt_template = ndata.get("prompt_template") or []

        messages = []
        for p in prompt_template:
            role = p.get("role", "user")
            text = p.get("text", "")
            messages.append({"role": role, "text": text})

        prompts.append({
            "node_id": node.get("id"),
            "title": title,
            "model": model_name,
            "messages": messages,
        })
    return prompts


def save_prompt_as_md(prompt: dict, out_dir: Path, overwrite: bool = False) -> bool:
    """把一个提示词存成 markdown。

    #159 裁决（ADR 0003）：默认拒绝覆盖已存在文件——Dify 同步不允许静默
    覆盖生产提示词，需要覆盖时显式传 --overwrite，由人先 diff 再决定。
    返回是否实际写入。
    """
    title = prompt["title"]
    filename = sanitize_filename(title) + ".md"
    out_path = out_dir / filename
    if out_path.exists() and not overwrite:
        print(f"  [跳过] {out_path} 已存在（--overwrite 可强制覆盖，覆盖前请先 diff）")
        return False

    lines = [
        f"# {title}",
        "",
        f"- **node_id**: `{prompt['node_id']}`",
        f"- **model**: `{prompt['model']}`",
        "",
    ]
    for msg in prompt["messages"]:
        lines.append(f"## [{msg['role']}]")
        lines.append("")
        lines.append("```")
        lines.append(msg["text"])
        lines.append("```")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  [✓] {out_path}")
    return True


def main():
    parser = argparse.ArgumentParser(description="从 Dify YAML 导出 LLM 提示词")
    parser.add_argument("input_dir", type=Path, help="Dify YAML 目录")
    parser.add_argument("output_dir", type=Path, help="输出目录")
    parser.add_argument("--overwrite", action="store_true",
                        help="允许覆盖已存在文件（默认跳过，覆盖前请先 diff）")
    args = parser.parse_args()

    if not args.input_dir.is_dir():
        print(f"[×] 输入目录不存在: {args.input_dir}", file=sys.stderr)
        sys.exit(1)

    total = 0
    for yaml_path in sorted(args.input_dir.glob("*.yml")):
        print(f"\n处理 {yaml_path.name}")
        prompts = extract_prompts_from_yaml(yaml_path)
        if not prompts:
            print("  (无 LLM 节点)")
            continue

        subdir = args.output_dir / sanitize_filename(yaml_path.stem)
        subdir.mkdir(parents=True, exist_ok=True)

        for prompt in prompts:
            if save_prompt_as_md(prompt, subdir, overwrite=args.overwrite):
                total += 1

    print(f"\n完成：共导出 {total} 个提示词到 {args.output_dir}")


if __name__ == "__main__":
    main()
