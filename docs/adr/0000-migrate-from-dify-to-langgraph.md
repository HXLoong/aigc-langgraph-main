# ADR 0000 · 从 Dify 工作流迁移到 LangGraph

- **Status**: Accepted（元 ADR：项目存在的根本动机）
- **Date**: 2026-05-10
- **Note**: 本 ADR 回答"为什么从 Dify 迁过来"。"如何重写当前 `app/`"由 ADR 0001 接管。

原系统用 Dify 编排意图识别 + 业务子图。随着业务需求增长，Dify 工作流暴露了四个长期累积的核心痛点：

1. **业务逻辑藏在提示词里**，无法在代码层 review、无法静态分析、无法 diff，每次提示词改动都是黑盒变更。
2. **无法自动化监测**：节点级延迟、错误率、LLM 命中率不能在统一 APM/可观测体系里采集。
3. **无法自动化回归测试**：Dify 工作流必须真实部署才能跑，CI 跑不了 in-process 端到端验证，每次发版只能靠人工抽测。
4. **无法对大模型处理做评估**：缺少 golden set + 评分机制，提示词调整后只能凭直觉判断"是不是变好了"。

我们需要一个能让业务逻辑回到代码、能在 CI 里跑闭环、能产出结构化 trace 供监测和评估的运行时。LangGraph + FastAPI 满足这四条，且子图嵌套、HITL interrupt、checkpointer 都是一等公民。

我们决定迁移到 LangGraph + FastAPI，把 Dify YAML 中的提示词原封导出为 `app/prompts/**/*.md`（生产验证过的资产，只做加载不改写），用 shadow 双跑工具持续校准两侧差异率，直到金丝雀切换。

> **遗留目标**：完整的"评估 / 监测 / 回归"测试 Harness 尚未建成（详见 ADR-0002 草案）。当前只有 30 条 golden + shadow_compare，离自动化评估闭环还有距离。

## Considered Options

- **保留 Dify**：四个痛点无解，业务复杂度上限低。
- **完全自研 DAG 引擎**：可控性最高但开发量大，且失去 LangGraph 生态（checkpointer / interrupt / structured output）。
- **LangGraph + FastAPI（已选）**：成熟生态，子图嵌套和 interrupt 一等公民，可在 in-process 测试中跑通。

## Consequences

- 提示词必须严格保持与 Dify 原文一致，禁止改写 `app/prompts/**/*.md`，否则 shadow 双跑会失真。
- 需要长期维护一套 Dify YAML 同步工具（`dify/sync.py` + `scripts/export_dify_prompts.py`），让业务方继续用 Dify UI 调整提示词，再批量同步进代码。
- 新增意图/子图必须同步更新 `app/state.py` 的 TypedDict 和 `tests/fixtures/golden.jsonl`。
- 引入了"业务逻辑下沉到代码 vs. 业务方继续在 Dify UI 里改提示词"的双轨期，需要明确治理边界（提示词归 Dify、节点编排归代码）。
