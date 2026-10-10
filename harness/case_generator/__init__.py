"""Golden case 生成器（grill-with-docs 2026-05-10 第 4 决策）。

策略：B + C 组合
- business_seed (B): 业务方手写种子，每节点 6-8 条
- llm_paraphrase (C): 基于种子的对抗式 LLM 生成
- production_log (A): 生产日志抽样（已搁置，由 D 桶客户真实输入替代，本模块不处理）

子模块：
- seed_template: 生成业务方种子收集 markdown 模板
- llm_paraphrase: LLM 对抗式生成器
"""
from harness.case_generator.seed_template import (
    NODE_REGISTRY,
    NodeSeedSpec,
    render_seed_template,
)

__all__ = ["NODE_REGISTRY", "NodeSeedSpec", "render_seed_template"]
