# ADR 0000 · 从 Dify 工作流迁移到 LangGraph

- 状态：已采纳（元 ADR：项目存在的根本动机）
- 日期：2026-05-10
- 关系：后果段被 [ADR 0024](./0024-langgraph-native-rearchitecture.md) 修订（Dify 退出上游）；"如何重写"见 [ADR 0001](./0001-rewrite-app-with-harness-first.md)
- 作者：图灵科技 + Tony

## 背景：Dify 的四个核心痛点

1. **业务逻辑藏在提示词里**：无法在代码层 review、静态分析或 diff，每次改动都是黑盒变更。
2. **无法自动化监测**：节点级延迟、错误率、LLM 命中率无法进入统一可观测体系。
3. **无法自动化回归**：工作流必须真实部署才能跑，发版只能靠人工抽测。
4. **无法评估大模型处理质量**：缺少数据集与评分机制，提示词调整只能凭直觉。

## 决策

迁移到 **LangGraph + FastAPI**：业务逻辑回到代码，能在 CI 里跑闭环，每个节点产出结构化 trace 供监测与评估。

## 备选方案

- **保留 Dify**：四个痛点无解，业务复杂度上限低。
- **自研 DAG 引擎**：可控但开发量大，且失去 LangGraph 生态（checkpointer、structured output、子图）。
- **LangGraph + FastAPI（已选）**：生态成熟，子图嵌套为一等公民，可在进程内完整测试。

## 现状

四个痛点的解法均已建成（见 [ADR 0002](./0002-comprehensive-runtime-harness.md)）：`harness/` 评测台、节点级 trace（MySQL + LangFuse）、按 B / C / D 桶管理的数据集、LLM Judge 自动评分。

现状：**Dify 已退出上游地位**（[ADR 0024](./0024-langgraph-native-rearchitecture.md) D1）：代码与 git 中的提示词是唯一真源，不再有 Dify 同步链路；Shadow 对照只是可选工具，验收以数据集评测门为准（[ADR 0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md) D3）。
