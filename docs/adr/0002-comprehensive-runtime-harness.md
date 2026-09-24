# ADR 0002 · 建设综合运行时 Harness（开发期 + 运行期 + 调优期三位一体）

- 状态：已采纳（三个能力面均已建成；线上标注回流未启动）
- 日期：2026-05-10
- 关系：节点层由 [ADR 0029](./0029-node-level-debug-api-and-regression-workbench.md) 补充；评测门统一到 [ADR 0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md) D3
- 作者：图灵科技 + Tony

## 背景与目标

[ADR 0000](./0000-migrate-from-dify-to-langgraph.md) 的四个痛点不是一个"评测脚本"能解决的。目标：**让"提示词改一行"或"节点逻辑改一行"成为有 CI、有指标、有 review 的工程动作**，而不是一次黑盒保存。

## 决策：覆盖三个阶段

| 阶段 | 能力 | 载体 |
|---|---|---|
| 开发期 | 节点 / 子图 / 模型单元测试；节点级回归工作台 | `tests/`；`python -m harness node-run`（ADR 0029） |
| 运行期 | 每节点结构化 trace；延迟与错误率告警 | `langgraph_node_trace` 表 + LangFuse（[ADR 0004](./0004-trace-granularity-node-level.md) / [0014](./0014-langfuse-as-harness-backend.md)）；`/metrics` + `app/observability/alerts.py` |
| 调优期 | 提示词版本化与灰度；数据集自动评分 | `_versions.yaml`（[ADR 0003](./0003-prompt-versioning-by-file-coexistence.md)）；`scripts/langfuse/langfuse_eval.py`（LLM Judge，[ADR 0005](./0005-annotation-roles-judge-plus-business-spotcheck.md)） |

## 现状

| 能力面 | 状态 |
|---|---|
| 数据集（`tests/fixtures/`，B / C / D 三桶）+ 全链路回归 | 已建成 |
| 节点级 trace 落库 + LangFuse 后台 | 已建成 |
| 提示词版本化 + 自动评分 + 按会话稳定分流 | 已建成（当前无在跑灰度） |
| 节点级回归 + HTTP 录放 | 已建成 |
| 线上 trace → 人工标注 → 数据集反哺 | 平台已定为 LangFuse，标注运营待启动 |

`harness/` 与 `app/` 解耦，只经 HTTP 入口驱动；CLI 为 `run` / `doctor` / `node-run`，评估主入口是 `scripts/langfuse/langfuse_eval.py`；运行成本可由 `harness/token_tracker.py` 与 `scripts/llm_cost_report.py` 度量。

## 备选方案

- **仅离线评分**：解决调优期，但回归与线上监测无解。
- **仅 CI 回归框架**：解决开发期，但缺少提示词调优与线上监测。
- **综合运行时 Harness（已选）**：覆盖三个阶段，代价是建设范围更大。

## 后果

- Shadow 对照（`scripts/shadow_compare.py`）只是可选工具，不作为迁移成功指标。
- 每新增意图 / 子图，必须同步补数据集用例；由 CI 中的 `scripts/check_fixture_consistency.py` 守护。
