# 架构决策记录（ADR）

本目录记录场外衍生品 AI 指令助手（otc-agent）现行有效的架构决策。只保留现行结论，被取代的决策已删除，编号不复用。

**项目目标**（[ADR 0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md)）：用原生 LangGraph 重构场外衍生品 AI 指令链路，通过数据集进行评测和评估，按 Harness 工程的要求推进每一次改动。

## 核心决策一览

| 主题 | 决策 | 带来的价值 | ADR |
|---|---|---|---|
| 为什么迁移 | 从 Dify 迁到 LangGraph + FastAPI，Dify 已完全退出上游 | 业务逻辑回到代码，可 review、可测试、可监测、可评估 | [0000](./0000-migrate-from-dify-to-langgraph.md) · [0024](./0024-langgraph-native-rearchitecture.md) |
| 图架构 | 原生子图、State 分层；后端只读查询可重试，LLM 与写节点不重试 | 结构清晰，失败可归因到具体节点，杜绝"重试导致重复下单" | [0024](./0024-langgraph-native-rearchitecture.md) · [0007](./0007-subgraph-vs-intent-scope-rule.md) |
| 解析与路由 | 每条消息全链路最多一次模型请求；规则优先，歧义一次联合解析，零 LLM 重试 | 产品、意图与候选共用解析结果；覆盖文本与附件（代码待重构） | [0031](./0031-single-model-request-per-message.md) · [0028](./0028-session-entry-and-multi-instruction-send-orchestration.md) |
| 交易确认 | 文本二阶段确认：明确动作 + 引用当前订单才执行写操作 | 写操作都有客户显式二次表达，不误触发 | [0021](./0021-text-confirm-replaces-interrupt.md) |
| 写路径正确性 | 消息级幂等、完整响应回放、不确定回执不重跑、只读对账 | 重投不重复下单；结果不确定时如实告知、人工核对 | [0026](./0026-request-idempotency-uncertain-receipts-reconciliation.md) |
| 参数可信度 | 模型只输出原文候选 + 证据，代码校验、归一化并锁定 | 模型幻觉值在提交前可机械检出，每个最终值可审计 | [0027](./0027-field-evidence-contract.md) |
| 标的识别 | LangGraph 只传原文，Java 后端权威识别 | 单一真源，代码不维护证券清单，少 3 路 LLM 调用 | [0025](./0025-instrument-resolution-delegated-to-backend.md) |
| 提示词 | git 是唯一真源；每个 LLM 节点声明 PromptSpec；同目录文件并存做灰度 | 提示词改动走 PR 审计，输入输出契约由测试守护 | [0023](./0023-prompt-as-code-langgraph.md) · [0003](./0003-prompt-versioning-by-file-coexistence.md) |
| 模型 | 全环境统一 DeepSeek-V4-pro，vendor 差异集中在一处适配 | 评测结论与现场同口径 | [0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) |
| 数据与合规 | MySQL 协议 / TDSQL 与 Java 共库；LangFuse 生产自托管 | 符合客户基础设施，trace 与数据不出境 | [0009](./0009-mysql-version-and-tdsql-compatibility.md) · [0014](./0014-langfuse-as-harness-backend.md) |
| 评测与运维 | 数据集 + 节点级 + CI + 上线观察四层统一评测门；P0/P1/P2 量化告警 | 每次改动有同一套可量化的放行标准 | [0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md) · [0002](./0002-comprehensive-runtime-harness.md) · [0019](./0019-incident-severity-thresholds.md) |

## 按目标主线阅读

**一、原生 LangGraph 重构**

- [0000](./0000-migrate-from-dify-to-langgraph.md) 迁移动机 → [0001](./0001-rewrite-app-with-harness-first.md) 重写方式 → [0024](./0024-langgraph-native-rearchitecture.md) 目标架构（已冻结）
- 业务结构：[0007](./0007-subgraph-vs-intent-scope-rule.md) 子图扩张规则 · [0031](./0031-single-model-request-per-message.md) 单条消息最多一次模型请求 · [0028](./0028-session-entry-and-multi-instruction-send-orchestration.md) 入口分流与单动作多订单
- 交易正确性：[0021](./0021-text-confirm-replaces-interrupt.md) 文本二阶段确认 · [0026](./0026-request-idempotency-uncertain-receipts-reconciliation.md) 幂等与回执 · [0027](./0027-field-evidence-contract.md) 字段证据契约
- 职责边界：[0025](./0025-instrument-resolution-delegated-to-backend.md) 标的识别归后端
- 基础设施：[0009](./0009-mysql-version-and-tdsql-compatibility.md) MySQL / TDSQL

**二、数据集评测与评估**

- [0002](./0002-comprehensive-runtime-harness.md) 综合运行时 Harness · [0029](./0029-node-level-debug-api-and-regression-workbench.md) 节点级回归工作台 · [0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md) D3 统一评测门
- [0005](./0005-annotation-roles-judge-plus-business-spotcheck.md) LLM Judge + 业务方抽检 · [0014](./0014-langfuse-as-harness-backend.md) LangFuse 后台 · [0004](./0004-trace-granularity-node-level.md) trace 颗粒度

**三、Harness 工程纪律**

- [0023](./0023-prompt-as-code-langgraph.md) 提示词即代码 · [0003](./0003-prompt-versioning-by-file-coexistence.md) 提示词版本化 · [0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) 模型统一 · [0019](./0019-incident-severity-thresholds.md) 故障升级阈值

## 总表

| 编号 | 标题 | 状态 | 关系 |
|---|---|---|---|
| [0000](./0000-migrate-from-dify-to-langgraph.md) | 从 Dify 工作流迁移到 LangGraph | 已采纳（元 ADR） | 现状见 0024 |
| [0001](./0001-rewrite-app-with-harness-first.md) | 推倒重写 `app/`，Harness-first | 已采纳（重写已完成） | 标的职责见 0025；评测门见 0030 |
| [0002](./0002-comprehensive-runtime-harness.md) | 综合运行时 Harness 三位一体 | 已采纳（线上标注回流未启动） | 节点层由 0029 补充 |
| [0003](./0003-prompt-versioning-by-file-coexistence.md) | 提示词版本化：同目录文件并存 | 已采纳（当前无在跑灰度） | — |
| [0004](./0004-trace-granularity-node-level.md) | Trace 颗粒度：节点级入库 + LangFuse 完整 I/O | 已采纳 | 后台见 0014 |
| [0005](./0005-annotation-roles-judge-plus-business-spotcheck.md) | 标注闭环：LLM Judge + 业务方抽检 | 已采纳（线上标注待启动） | 平台由 0014 确定 |
| [0007](./0007-subgraph-vs-intent-scope-rule.md) | 独立子图 vs 新意图：四条触发规则 | 已采纳 | — |
| [0009](./0009-mysql-version-and-tdsql-compatibility.md) | MySQL 协议 + TDSQL 生产环境 | 已采纳（TDSQL 待现场实测） | — |
| [0014](./0014-langfuse-as-harness-backend.md) | LangFuse 作为 Harness 后台 | 已采纳 | 修订 0004 / 0005 |
| [0019](./0019-incident-severity-thresholds.md) | 故障升级阈值 P0 / P1 / P2 | 已采纳 | 与 0030 D3 互补 |
| [0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) | 全量统一 DeepSeek-V4-pro | 已采纳 | — |
| [0021](./0021-text-confirm-replaces-interrupt.md) | 文本二阶段确认 + checkpointer 接线 | 已采纳 | 确认范围校验见 0027 D5 |
| [0023](./0023-prompt-as-code-langgraph.md) | 提示词即代码：PromptSpec | 已采纳 | 输出契约由 0027 收敛 |
| [0024](./0024-langgraph-native-rearchitecture.md) | LangGraph 原生重构目标架构 | 已采纳（已冻结） | 拆出 0025-0029；D3 由 0031 修订 |
| [0025](./0025-instrument-resolution-delegated-to-backend.md) | 标的识别移交 Java 后端 | 已采纳（追认） | 修订 0001 D4 / 0023 / 0024 |
| [0026](./0026-request-idempotency-uncertain-receipts-reconciliation.md) | 请求级幂等、不确定回执与对账 | 已采纳（追认） | 细化 0024 D4；D2 由 0031 修订 |
| [0027](./0027-field-evidence-contract.md) | 字段证据契约 | 已采纳（追认） | 修订 0023 D2；模型重试见 0031 |
| [0028](./0028-session-entry-and-multi-instruction-send-orchestration.md) | 会话保护入口分流与单动作多订单 | 已采纳 | 解析约束见 0031 |
| [0029](./0029-node-level-debug-api-and-regression-workbench.md) | 节点级调试接口与回归工作台 | 已采纳（追认） | 细化 0024 D6 |
| [0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md) | 目标重述与统一评测门 | 已采纳 | 修订 0001 / 0002 / 0005 / 0019 / 0024 D8 |
| [0031](./0031-single-model-request-per-message.md) | 单条消息全链路最多一次模型请求 | 已采纳（目标约束，代码待重构） | 修订 0001 D5 / 0024 D3 / 0026 D2 / 0027 D2 |

现状与待办不在 ADR 中维护，统一见 [docs/work-plan.md](../work-plan.md)。

## 维护约定

**格式**：标题 `# ADR NNNN · 中文标题`；头部为 `状态 / 日期 / 关系（可选）/ 作者`；正文为 背景 → 决策 → 备选方案 → 后果（现状）。

**状态词**：

| 状态 | 含义 |
|---|---|
| 已采纳 | 决策有效；括号内一句现状 |
| 已采纳（追认） | 先有实现后补 ADR，注明落地 commit |

被修订的 ADR 状态不变，在"关系"行注明修订来源。**被取代的 ADR 直接删除**：仍有效的规则先并入取代它的 ADR，再删除原文件；编号不复用，原文可从 git 历史找回。本表状态须与各篇头部一致。

**写作纪律**（[ADR 0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md) D2 / D4）：

- 正文只写现行的决策、理由、后果与一句现状；不写演变史与过程记录（留在 PR 与 git 历史）。
- 不写里程碑任务码、issue / PR 编号、会过期的裸计数；必须写数字时注明"截至 YYYY-MM-DD"与真源路径。
- 不写凭据、内网地址、第三方系统配置细节等敏感信息。

**自动检查**（CI fast job）：

- `scripts/check_adr_refs.py`：ADR 互引无虚悬、反引号中的代码路径与 Markdown 相对链接存在（跳过 `~~删除线~~` 段）；`--heat` 可查看孤儿 ADR。
- `scripts/check_alert_threshold_consistency.py`：[ADR 0019](./0019-incident-severity-thresholds.md) §1 告警表与 `app/observability/alerts.py`、`docs/operations/on-call-runbook.md` §3 一致（修改该表须保持列格式）。

## 人工复核

论证是否仍成立、README 总表与各篇头部是否一致、跨仓库（Java 侧）契约引用，需人工复核；建议每新增 5 篇 ADR 做一次。
