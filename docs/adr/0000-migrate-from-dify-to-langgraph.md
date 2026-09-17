# ADR 0000 · 从 Dify 工作流迁移到 LangGraph

- 状态：已采纳（元 ADR：项目存在的根本动机）
- 日期：2026-05-10
- 修订：2026-08-27 深度改写为现状口径（wayfinder map #138 / 核查 #139）
- 作者：图灵科技 + Tony
- 说明：本 ADR 回答"为什么从 Dify 迁过来"；"如何重写 `app/`"由 [ADR 0001](./0001-rewrite-app-with-harness-first.md) 接管

## 动机：Dify 的四个核心痛点

原系统用 Dify 编排意图识别 + 业务子图。随着业务需求增长，Dify 工作流暴露了四个长期累积的核心痛点：

1. **业务逻辑藏在提示词里**，无法在代码层 review、无法静态分析、无法 diff，每次提示词改动都是黑盒变更。
2. **无法自动化监测**：节点级延迟、错误率、LLM 命中率不能在统一 APM/可观测体系里采集。
3. **无法自动化回归测试**：Dify 工作流必须真实部署才能跑，CI 跑不了 in-process 端到端验证，每次发版只能靠人工抽测。
4. **无法对大模型处理做评估**：缺少 golden set + 评分机制，提示词调整后只能凭直觉判断"是不是变好了"。

我们需要一个能让业务逻辑回到代码、能在 CI 里跑闭环、能产出结构化 trace 供监测和评估的运行时。LangGraph + FastAPI 满足这四条，且子图嵌套、HITL interrupt、checkpointer 都是一等公民。

## 决策与落地现状（2026-08-27）

决定迁移到 **LangGraph + FastAPI**，把 Dify YAML 中的提示词导出为 `app/prompts/**/*.md`（现有 37 个业务提示词 .md）。

原决策的两条执行方式已按后续 ADR 演进：

- **"提示词只做加载不改写"** → 已由 [ADR 0001 D5](./0001-rewrite-app-with-harness-first.md) 在重构期解禁：合并/拆分/瘦身类改写须在 D5 处置表登记，Dify 原版以非活跃快照保留并在 ~~`app/prompts/_manifest.yaml`~~ 登记（2026-09-16 已废弃）；M4 后改写走 eval 门 + PR review（[ADR 0022](./0022-prompt-governance-after-code-migration.md)）。
- **"shadow 双跑校准到金丝雀切换"** → 已由 [ADR 0016](./0016-m3-scope-engineering-loop-not-shadow.md) 降级为 **F4.1（M4 阶段的第二意见）**，M3 的合格性判定改为 golden PASS 率退出门。

四个痛点的主要解药均已建成（详见 [ADR 0002](./0002-comprehensive-runtime-harness.md)）：`harness/` 评测台、`node_trace` 写入代码 + LangFuse trace、golden set 535 条（主）+ 34 条（ticker）按 B/C/D 桶管理、DeepSeek Judge 评估（`scripts/langfuse_eval.py`）。其中 `node_trace` 的建表/迁移资产尚未入库，部署不能仅凭当前仓库完成落库初始化。

## 备选方案

- **保留 Dify**：四个痛点无解，业务复杂度上限低。
- **完全自研 DAG 引擎**：可控性最高但开发量大，且失去 LangGraph 生态（checkpointer / interrupt / structured output）。
- **LangGraph + FastAPI（已选）**：成熟生态，子图嵌套和 interrupt 一等公民，可在 in-process 测试中跑通。

## 后果（现状口径）

- ~~需要长期维护 Dify YAML 同步工具（`dify/sync.py` + `scripts/export_dify_prompts.py`），让业务方继续用 Dify UI 调整提示词，再批量同步进代码~~ —— **已被 [ADR 0024](./0024-langgraph-native-rearchitecture.md) D1 取代（2026-09-17）**：代码即真源，Dify YAML 冻结为历史参照、不再同步。同步脚本的覆盖写风险见裁决 issue [#159](https://github.com/GZTL-AI/aigc-langgraph/issues/159)。
- 新增意图/子图必须同步更新 `app/graph/state.py` 的 TypedDict（`app/state.py` 仅剩兼容 shim）与 `tests/fixtures/old_typing/golden.jsonl`——后者已由 CI 的 `scripts/check_fixture_consistency.py` 强制。
- "业务逻辑下沉到代码 vs. 业务方继续在 Dify UI 改提示词"的双轨期治理边界：提示词归 Dify / 节点编排归代码；重构期内的改写例外由 ADR 0001 D5 处置表管理。
- 原文提到的"统一 APM 体系"最终由 **LangFuse** 承载（[ADR 0014](./0014-langfuse-as-harness-backend.md) 取代早期 LangSmith 方案）。
