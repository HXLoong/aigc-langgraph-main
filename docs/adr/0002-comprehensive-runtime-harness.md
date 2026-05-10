---
status: proposed
---

# 建设综合运行时 Harness（开发期 + 运行期 + 提示词调优期三位一体）

ADR-0001 列出了 Dify 留下的四个痛点（业务逻辑藏在提示词、无法监测、无法回归、无法评估）。我们决定把"评估 Harness"目标定义为 **综合运行时 Harness**，而不只是单一的"评测脚本"或"CI 测试金字塔"。

**目标定义**：让"提示词改一行"或"节点逻辑改一行"成为一个有 CI、有指标、有 review 流程的工程动作，而不是 Dify UI 上一次黑盒保存。具体覆盖：

- **开发期**：节点 / 子图 / 模型层单元测试，in-process 闭环 demo（已有 30/30）+ 子图金字塔。
- **运行期**：每个节点产出结构化 trace 写入 MySQL，对接 LangSmith / OpenTelemetry，可基于 trace 做延迟、错误率、命中率告警。
- **提示词调优期**：提示词版本化 + golden set 自动评分 + 提示词 A/B 框架，量化决定"新提示词是否值得替换旧提示词"。

## Considered Options

- **A. 评估 Harness（仅 lm-eval 风格的离线评分）**：解决"提示词调优期"，但开发期的回归测试、运行期的监测都无解。
- **B. 测试 Harness（仅 CI 回归框架）**：解决"开发期"，但提示词调优要素和线上监测缺失。
- **C. 综合运行时 Harness（已选）**：覆盖三个阶段，是四个痛点真正的对应解。代价是建设范围更大、需要分阶段落地。

## Phases

1. **Phase 1（已完成）**：闭环 demo + golden set 30 条 + shadow_compare。
2. **Phase 2（进行中）**：节点级 trace 落库 + LangSmith 接入。决策见 **ADR-0004**。
3. **Phase 3（决策已立，建设进行中）**：提示词版本化基础。决策见 **ADR-0003**。剩余子项（golden 评分自动化、A/B 流量染色）待立项。
4. **Phase 4（决策已立，待 MVP）**：线上 trace → 人工标注 → golden 反哺。角色分工见 **ADR-0005**；标注 UI / 平台选型待立项。

## Consequences

- 不再把 shadow_compare 当作迁移成功的唯一指标——它只是 Phase 1 的产出，不能替代 Phase 3/4 的提示词评估能力。
- 后续每加一个意图/子图，必须同步生产 golden case + trace schema 字段，否则整个 Harness 价值被稀释。
- 需要为"提示词版本化"留出代码组织空间（不能让 `app/prompts/` 变成无版本号的扁平目录），见 prompt-management 规则的"v2.md 并存"约定。
