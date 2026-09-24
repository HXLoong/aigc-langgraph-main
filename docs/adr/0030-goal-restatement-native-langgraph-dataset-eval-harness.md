# ADR 0030 · 目标重述：原生 LangGraph 重构 + 数据集评测 + Harness 工程

- 状态：已采纳
- 日期：2026-09-22
- 关系：取代早期里程碑验收方案（原 0016 / 0017 号，已删除，有效论点并入本篇）；修订 [ADR 0001](./0001-rewrite-app-with-harness-first.md)（上线节奏段）、[ADR 0002](./0002-comprehensive-runtime-harness.md)（阶段表改为能力面）、[ADR 0005](./0005-annotation-roles-judge-plus-business-spotcheck.md)、[ADR 0019](./0019-incident-severity-thresholds.md)、[ADR 0024](./0024-langgraph-native-rearchitecture.md) D8
- 作者：图灵科技 + Tony

## 背景

迁移期的 ADR 用里程碑任务码和 issue 编号记录进度与裁决。到 2026-09-22，代码已经完成 Dify 形态退出（ADR 0024 D1）、标的移交后端（0025）、幂等与回执契约（0026）、字段证据契约（0027）、会话保护与单动作多订单（0028）、节点级工作台（0029）。这些任务码与 issue 不再反映工作的组织方式；留在 ADR 里只会让读者误以为它们仍是当前门槛，也让每篇 ADR 的状态行被"某个 issue 是否关闭"绑架。

## 决策

### D1 · 目标三主线

1. **原生 LangGraph 重构场外 AI 指令链路**：图即架构（子图原生嵌入、单动作多订单、RetryPolicy、State 分层与 output schema，[ADR 0024](./0024-langgraph-native-rearchitecture.md) D2 / D3、[ADR 0028](./0028-session-entry-and-multi-instruction-send-orchestration.md)）；持久化与可观测契约（0024 D4 / D5、[ADR 0026](./0026-request-idempotency-uncertain-receipts-reconciliation.md)）；提示词即代码与字段证据契约（[ADR 0023](./0023-prompt-as-code-langgraph.md)、[ADR 0027](./0027-field-evidence-contract.md)）；Dify 只作历史参照，标的识别与业务默认值归 Java 后端（[ADR 0025](./0025-instrument-resolution-delegated-to-backend.md)）。
2. **通过数据集进行评测和评估**：ground truth 是数据集的 `expected`，不是 Dify 输出（迁移动机恰恰是 Dify 的标的不准、参数错误与缺少评估，拿它作标准会冤枉新系统、美化旧系统）。数据集 = `tests/fixtures/categories/`（显式验收集）+ `tests/fixtures/unified_golden.jsonl`（历史参考集，显式选择）+ `tests/fixtures/nodes/`（节点级 fixture，[ADR 0029](./0029-node-level-debug-api-and-regression-workbench.md)）；评测入口 = harness HTTP 回归（[ADR 0002](./0002-comprehensive-runtime-harness.md) / 0024 D6）+ LLM Judge（[ADR 0005](./0005-annotation-roles-judge-plus-business-spotcheck.md) / [ADR 0014](./0014-langfuse-as-harness-backend.md)）；错例先补 fixture 再修代码。
3. **按 Harness 工程的要求重构**：任何提示词 / 节点 / 契约改动都经同一条门（D3）——TDD RED → GREEN、pytest、四项一致性 lint、ruff / mypy、数据集 PASS 率不低于前值、trace 可归因（[ADR 0004](./0004-trace-granularity-node-level-with-langsmith.md) / 0024 D5）。harness 与 `app/` 解耦，只经 HTTP 入口驱动。

### D2 · 退役口径

- 里程碑、任务码、roadmap 阶段表、issue / PR 编号不再出现在 ADR 正文与状态行；历史裁决只保留"日期 + 结论"。现状与待办统一见 [docs/work-plan.md](../work-plan.md)。
- 由里程碑定义的退出门全部改写为 D3 的评测门；旧基线数值（Qwen 口径的通过率与 P95）作废，以当前模型（[ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md)）重测报告为准。

### D3 · 统一评测门（取代阶段退出门）

| 层 | 门槛 | 载体 |
|---|---|---|
| 数据集 | 显式 `categories` 全量 PASS 率不低于上一基线（同模型、同后端模式）；`REJECTED` 单独成桶不计 PASS；写类 case 必须有 `expected.place_params`；多轮 case 早停未执行轮记失败 | `python -m harness run` / `scripts/local_eval.py` / `scripts/langfuse/langfuse_eval.py` |
| 节点级 | 被改动节点的 fixture 回归 PASS；带写副作用的 fixture 只留存标注不回放 | `python -m harness node-run`（ADR 0029） |
| 代码 | pytest 全量 GREEN；ruff / mypy 零错；`sync_agents_md` / 阈值 / fixture / ADR 四项 lint 通过；CI 在 push 与 PR 上跑 | `.github/workflows/ci.yml` |
| 上线观察 | 5xx < 0.1%、cascade fail < 1%、P95 ≤ 当前基线 × 1.5（7 天滚动）；业务方严重错例（标的错 / 参数错 / 意图大类错）≤ 5 次 / 7 天；故障期间定级与介入见 [ADR 0019](./0019-incident-severity-thresholds.md) | `/metrics` + `app/observability/alerts.py` + `scripts/metrics_snapshot.py` |

阈值取值理由：服务器崩溃应近似为零（0.1% 留瞬时抖动容差）；1% 是"用户能感知但不至于认为 AI 坏了"的临界；聊天体验由尾部延迟决定，×1.5 为真后端往返与写库留预算；错例阈值不取 0，以免业务方永远无法签字。测量口径：5xx 与 cascade 率取自 `/metrics`，分母为总请求数；P95 取 `/v1/workflows/run` 端到端延迟，剔除节点级样本。2026-09-24 已完成当前模型本地 dry-run 参考采样并回填告警默认值（见 [ADR 0019](./0019-incident-severity-thresholds.md)）；业务交易验收与生产同拓扑 7 天观察仍未通过，不由 dry-run 结果替代。

### D4 · ADR 写法

状态行只写日期与一句现状；正文不写会腐烂的计数与任务码；实施记录进 `docs/`（如 `docs/langgraph-reconstruction-20260918.md`、`docs/archive/history/adr-implementation-log-2026-09.md`），ADR 只链接；先有实现后补 ADR 时标"已采纳（追认）"并注明 commit。

## 备选方案

- **保留里程碑口径并逐篇标"已过期"**：读者仍要在每篇里分辨哪段是门槛、哪段是历史。否决。
- **全部 ADR 重新编号 / 归档重写**：全库交叉引用经不起断，历史决策的论证会丢失。否决。
- **新开一篇目标 ADR + 逐篇清理过期口径（已选）**。

## 后果

- 正面：ADR 只承载决策与契约；评测门只有一套，且与 CI、harness、Judge 的实际入口一一对应。
- 负面：生产同拓扑基线与观察窗口仍待部署验证；里程碑过程文档已删除（可从 git 历史找回）。
- 2026-09-23 裁决：统一验收与 `harness run` 默认只加载 `categories`；`unified_golden.jsonl` 保留为历史参考集，经 `--include-unified` 或 `--data` 显式选择，仍参加一致性 lint。
- 未决：节点 fixture 与代码演进的漂移守护；上线观察窗口的正式起点由部署决定。

## 关联

- [ADR 0002](./0002-comprehensive-runtime-harness.md) · Harness 三位一体 / [ADR 0024](./0024-langgraph-native-rearchitecture.md) · 原生重构目标架构 / [ADR 0029](./0029-node-level-debug-api-and-regression-workbench.md) · 节点级回归
