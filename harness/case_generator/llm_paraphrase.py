"""LLM 对抗式 paraphrase 生成器（grill-with-docs 第 4 决策 C 来源）。

输入：业务方种子 case（来自 golden.jsonl，source="business_seed"）
输出：候选 case 列表（source="llm_paraphrase"），等业务方 review 后合入 golden

策略：
- 用 thinking 模型（ADR 0010：复杂推理用 thinking）
- 给 LLM 一条种子，让它生成 N 条**与种子表达不同但 expected 相同**的对抗变体
- 变体覆盖：缩写 / 错别字 / 口语化 / 引用同义词 / 边界场景

注：生成的 case **不直接合入** golden.jsonl —— 必须经业务方 review pass。
本工具只产生 docs/archive/m2/m2-llm-generated-cases.md 候选清单。
"""
from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from app.llm.clients import get_qwen_thinking
from harness.golden import GoldenCase

# ============================================================
# Pydantic 输出 schema
# ============================================================


class ParaphrasedCase(BaseModel):
    """单条 LLM 生成的对抗式 case 候选。"""

    model_config = ConfigDict(extra="ignore")

    send_text: str
    quote_previous: bool | None = None
    notes: str = Field(description="变体类型说明，如 '缩写' / '口语化' / '错别字'")


class ParaphraseBatch(BaseModel):
    """LLM 一次生成的多条变体。"""

    model_config = ConfigDict(extra="ignore")

    variants: list[ParaphrasedCase] = Field(default_factory=list)


# ============================================================
# 生成 prompt
# ============================================================


_SYSTEM_PROMPT = """你是 golden case 对抗式变体生成器。

任务：根据一条业务种子 case，生成 N 条与种子**表达不同但 expected 相同**的变体，用于测试 LLM 节点的鲁棒性。

【绝对要求】
- 只输出 JSON 对象 {"variants": [{...}]}
- 每个变体 raw_content 必须与种子语义等价（expected 不变），但表达形式不同
- 变体类型至少覆盖：
  - 缩写（如"互换" → "TRS"）
  - 口语化（加语气词"帮我..."、"请..."）
  - 错别字（手抖打错关键词）
  - 同义词替换（"下单" → "成交"）
  - 词序调整
  - 引用上下文（如果种子是参数补充类，加 quote_content）
- notes 字段简短说明变体类型（如"缩写"、"口语化+错别字"）

【参考】

种子: {"raw_content": "做一笔招商银行的 TRS，买 1000 手，市价", "expected": {"product_type": "swap", "intent": "place_order_request"}}

输出（生成 3 条变体示例）:
{
  "variants": [
    {"raw_content": "招行 互换 1000 手 市价", "quote_content": null, "notes": "缩写+省略"},
    {"raw_content": "帮我做一笔总收益互换 招商银行 一千手 不限价", "quote_content": null, "notes": "口语化+同义词"},
    {"raw_content": "TRS下单 招商银行1000手", "quote_content": null, "notes": "TRS缩写+无空格"}
  ]
}

只输出 JSON 对象。
"""


_USER_TEMPLATE = """请基于以下种子生成 {num_variants} 条对抗式变体（保持 expected 不变）：

种子 raw_content: {raw_content}
种子 expected: {expected}
种子 quote_content: {quote_content}
"""


# ============================================================
# 生成器
# ============================================================


async def paraphrase_case(
    seed: GoldenCase, num_variants: int = 3
) -> list[ParaphrasedCase]:
    """对单条种子生成 N 条对抗式变体。"""
    llm = get_qwen_thinking().with_structured_output(ParaphraseBatch)
    user_msg = _USER_TEMPLATE.format(
        num_variants=num_variants,
        raw_content=seed.turns[-1].send_text,
        expected=json.dumps(seed.expected, ensure_ascii=False),
        quote_content="(首轮无引用)",
    )
    result = await llm.ainvoke(
        [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=user_msg)]
    )
    return list(result.variants)


def to_golden_dict(
    seed: GoldenCase,
    paraphrased: ParaphrasedCase,
    new_id: str,
) -> dict:
    """把 LLM 生成的变体转为 golden.jsonl 格式（不直接合入，等 review）。"""
    return {
        "id": new_id,
        "category": seed.category,
        "send_text": paraphrased.send_text,
        "at_bot": True,
        "response_contains": [],
        "response_not_contains": [],
        "sub_scenes": [],
        "expected": seed.expected,
        "notes": f"LLM paraphrase: {paraphrased.notes} (seed={seed.id})",
        "source": "llm_paraphrase",
    }


# ============================================================
# Markdown 候选清单渲染（业务方 review 用）
# ============================================================


_REVIEW_HEADER = """\
# LLM 对抗式变体候选清单（待业务方 review）

> grill-with-docs 第 4 决策 C 来源 · LLM 生成的 paraphrase 候选 case
>
> 业务方 review pass 的 case 转 jsonl 合入 `tests/fixtures/categories/`，
> 标记 `source: llm_paraphrase`（PASS 阈值 80%，比 business_seed 90% 阈值更宽松）。

## 使用流程

1. 业务方对每条候选打勾（`[x]`）或叉（`[ ]`）
2. 工程师批量将打勾的 case 合入 golden.jsonl
3. 跑 `python -m harness run` 验证整体 PASS 率不降

---

"""


def render_review_markdown(
    seed_with_paraphrases: list[tuple[GoldenCase, list[ParaphrasedCase]]],
) -> str:
    """渲染候选清单 markdown（含 review checkboxes）。"""
    lines = [_REVIEW_HEADER]
    for seed, variants in seed_with_paraphrases:
        lines.append(f"## 种子 {seed.id}（{seed.category}）")
        lines.append("")
        lines.append(f"**原话**: {seed.turns[-1].send_text}")
        lines.append(
            f"**expected**: `{json.dumps(seed.expected, ensure_ascii=False)}`"
        )
        lines.append("")
        lines.append("### 候选变体")
        lines.append("")
        for idx, v in enumerate(variants, 1):
            lines.append(
                f"- [ ] **{seed.id}-v{idx}** ({v.notes})\n  - send_text: `{v.send_text}`"
            )
        lines.append("")
    return "\n".join(lines)


__all__ = [
    "ParaphrasedCase",
    "ParaphraseBatch",
    "paraphrase_case",
    "to_golden_dict",
    "render_review_markdown",
]
