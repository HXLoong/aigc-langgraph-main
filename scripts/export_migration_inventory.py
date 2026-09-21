"""Export actual fields and live prompt contracts; do not invent the missing 50-slot schema."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from app.graph.main import build_main_graph
from app.prompts import load_prompt
from app.prompts.spec import all_specs
from app.subgraphs.close.models import CloseOrderItem, HoldingQueryParams
from app.subgraphs.option.models import OptionInquiryRawItem, OptionOrderItemWithFastExec
from app.subgraphs.swap.models import SwapOrderItem
from app.tools.option_client import FinancialOrderOpenApiBaseSaveReqVO
from app.tools.swap_client import SwapOrderOpenApiBaseSaveReqVO

MODELS = (SwapOrderItem, OptionOrderItemWithFastExec, OptionInquiryRawItem,
          CloseOrderItem, HoldingQueryParams, SwapOrderOpenApiBaseSaveReqVO,
          FinancialOrderOpenApiBaseSaveReqVO)


def generate(java_root: Path, output: Path) -> None:
    build_main_graph()
    schemas = {model.__name__: model.model_json_schema(by_alias=True) for model in MODELS}
    java_fields: dict[str, Any] = {}
    for name in ("SwapOrderOpenApiBaseSaveReqVO", "FinancialOrderOpenApiBaseSaveReqVO"):
        matches = list(java_root.rglob(name + ".java"))
        if len(matches) != 1:
            raise ValueError(f"expected exactly one Java DTO source: {name}")
        source = matches[0].read_text()
        java_fields[name] = {
            "source": str(matches[0].relative_to(java_root)),
            "fields": [{"name": field, "java_type": kind} for kind, field in
                       re.findall(r"private\s+(?:transient\s+)?([\w<>?, .]+)\s+(\w+)\s*;", source)],
        }
    output.mkdir(parents=True, exist_ok=True)
    (output / "field-contracts.json").write_text(json.dumps({
        "models": schemas, "java": java_fields,
        "note": "实际契约清单；字段数按业务模型分别统计，不宣称缺失的 slot_schema.json 已复原。",
    }, ensure_ascii=False, indent=2) + "\n")
    lines = ["# 节点与字段迁移清单", "",
             "由 `python -m scripts.export_migration_inventory --java-root <local-java-api>` 生成。",
             "Java 只读。字段 JSON 是契约快照，运行时继续以 Pydantic 模型为真源。",
             "实际 Dify 节点映射见 [完整节点清单](../node-migration-20260918.md)。旧字符数为本仓起点 c7be6f1 的 system 段。", "",
             "| 活跃 PromptSpec | 输出契约 | 原文证据契约 | system 字符（前 → 后） |",
             "|---|---|---|---|"]
    for key, spec in sorted(all_specs().items()):
        filename = f"app/prompts/{key}.md"
        old = subprocess.run(["git", "show", f"c7be6f1:{filename}"], capture_output=True, text=True)
        before = "未找到"
        if old.returncode == 0:
            from app.prompts import _parse_prompt_md
            before = str(len(_parse_prompt_md(old.stdout)[0]))
        after = len(load_prompt(spec.category, spec.name).system)
        model = spec.output_model.__name__ if spec.output_model else "文本"
        if model.endswith("Candidates"):
            evidence = "原文候选核验 + Code 归一化"
        elif key.endswith("/intent") or key == "router/unknown_intent":
            evidence = "意图置信度/原文来源核验"
        elif key in {"swap/select_counterparty", "swap/select_ticker"}:
            evidence = "选择范围/原文核验 + 权威候选绑定"
        elif key == "swap/fresh_counterparty":
            evidence = "原文名称核验 + 授权名单绑定"
        elif key == "swap/image_ocr":
            evidence = "结构化转写，后续候选核验；非像素事实证明"
        elif key == "router/split_instructions":
            evidence = "连续原文覆盖/边界/依赖核验"
        elif key.startswith("ticker/"):
            evidence = "检索/排序候选；最终身份由 GOATS 校验"
        else:
            evidence = "需逐项核对"
        lines.append(f"| {key} | {model} | {evidence} | {before} → {after} |")
    lines += ["", "| 当前业务模型 | 声明字段数 |", "|---|---|"]
    lines += [f"| {model.__name__} | {len(model.model_fields)} |" for model in MODELS]
    lines += ["", "字段名、类型、描述及 Java 源码字段见 [field-contracts.json](field-contracts.json)。",
              "数值/枚举/比例/时间归一化见 swap/normalize.py；期权确定性规则见 option/normalize.py 与 place_params.py。",
              "尚未迁移的节点不能因为完成 PromptSpec 注册而计为符合节点迁移规范。", ""]
    (output / "README.md").write_text("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--java-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("tmp/migration-20260918"))
    args = parser.parse_args()
    generate(args.java_root, args.out)
