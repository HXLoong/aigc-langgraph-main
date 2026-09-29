# 架构决策记录（ADR）

本目录记录场外衍生品 AI 指令助手（otc-agent）现行有效的架构决策。只保留现行结论，被取代的决策已删除，编号不复用。

**项目目标**（[ADR 0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md)）：用原生 LangGraph 重构场外衍生品 AI 指令链路，通过数据集进行评测和评估，按 Harness 工程的要求推进每一次改动。

## 核心决策一览

| 主题 | 决策 | 带来的价值 | ADR |
|---|---|---|---|
| 为什么迁移 | 从 Dify 迁到 LangGraph + FastAPI，Dify 已完全退出上游 | 业务逻辑回到代码，可 review、可测试、可监测、可评估 | [0000](./0000-migrate-from-dify-to-langgraph.md) · [0024](./0024-langgraph-native-rearchitecture.md) |
| 图架构 | 原生子图、State 分层；后端只读查询可重试，LLM 与写节点不重试 | 结构清晰，失败可归因到具体节点，杜绝"重试导致重复下单" | [0024](./0024-langgraph-native-rearchitecture.md) |
| 解析与路由 | 每次工具调用全链路最多一次模型请求；规则优先，歧义一次联合解析，调用内零 LLM 重试 | 产品、意图与候选共用解析结果；调用端重试独立计数；覆盖文本 / Excel，图片暂不处理（代码待重构） | [0031](./0031-single-model-request-per-message.md) · [0028](./0028-session-entry-and-multi-instruction-send-orchestration.md) |
| 单次指令处理 | LangGraph 不强制二阶段，识别提交本次动作；Java 决定业务流程 | 现有确认 type 保留，普通动作不自动提升为确认；代码待收敛 | [0021](./0021-text-confirm-replaces-interrupt.md) |
| 调用与回执职责 | 消息防重与重投归调用端，交易幂等归 Java；LangGraph 返回本次真实结果 | 不确定回执不推断成败；占位、回放、重投静默与对账代码待清理 | [0026](./0026-request-idempotency-uncertain-receipts-reconciliation.md) |
| 字段来源 | 保留提取值、原文与来源；Code 清洗接口类型，Java 校验业务值 | 接口类型不兼容字段有记录地省略，业务数值和默认值归 Java | [0027](./0027-field-evidence-contract.md) |
| 标的识别 | LangGraph 提取表达或用户选择，Java 调用对应的识别工作流 | 识别职责集中在后端，LangGraph 无需维护证券清单或识别逻辑 | [0025](./0025-instrument-resolution-delegated-to-backend.md) |
| 提示词 | git 是唯一真源；每个 LLM 节点声明 PromptSpec；版本化用 git 分支 + 单文件，灰度按群切部署 | 提示词改动走 PR 审计，输入输出契约由测试守护 | [0023](./0023-prompt-as-code-langgraph.md) · [0003](./0003-prompt-versioning-by-git-branch.md) |
| 模型 | 通用三角色配置、显式厂商适配，当前基线为 deepseek-v4-pro | 通用配置已实现；切换模型需重新验收，图片暂不处理 | [0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) |
| 数据与合规 | MySQL 协议 / TDSQL 与 Java 共库；LangFuse 生产自托管 | 符合客户基础设施，trace 与数据不出境 | [0009](./0009-mysql-version-and-tdsql-compatibility.md) · [0014](./0014-langfuse-as-harness-backend.md) |
| 评测与运维 | 数据集 + 节点级 + CI + 上线观察四层统一评测门；P0/P1/P2 量化告警 | 每次改动有同一套可量化的放行标准 | [0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md) · [0002](./0002-comprehensive-runtime-harness.md) · [0019](./0019-incident-severity-thresholds.md) |

## 按目标主线阅读

**一、原生 LangGraph 重构**

- [0000](./0000-migrate-from-dify-to-langgraph.md) 迁移动机 → [0001](./0001-rewrite-app-with-harness-first.md) 重写方式 → [0024](./0024-langgraph-native-rearchitecture.md) 目标架构（已冻结）
- 业务结构：[0031](./0031-single-model-request-per-message.md) 单次工具调用最多一次模型请求 · [0028](./0028-session-entry-and-multi-instruction-send-orchestration.md) 入口分流与单动作多订单
- 交易正确性：[0021](./0021-text-confirm-replaces-interrupt.md) 单次指令处理边界 · [0026](./0026-request-idempotency-uncertain-receipts-reconciliation.md) 调用端幂等职责与单次调用回执 · [0027](./0027-field-evidence-contract.md) 字段证据契约
- 职责边界：[0025](./0025-instrument-resolution-delegated-to-backend.md) 标的识别由 Java 调用工作流完成
- 基础设施：[0009](./0009-mysql-version-and-tdsql-compatibility.md) MySQL / TDSQL

**二、数据集评测与评估**

- [0002](./0002-comprehensive-runtime-harness.md) 综合运行时 Harness · [0029](./0029-node-level-debug-api-and-regression-workbench.md) 节点级回归工作台 · [0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md) D3 统一评测门
- [0005](./0005-annotation-roles-judge-plus-business-spotcheck.md) 确定性断言 + 业务方复核 · [0014](./0014-langfuse-as-harness-backend.md) LangFuse 后台 · [0004](./0004-trace-granularity-node-level.md) trace 颗粒度

**三、Harness 工程纪律**

- [0023](./0023-prompt-as-code-langgraph.md) 提示词即代码 · [0003](./0003-prompt-versioning-by-git-branch.md) 提示词版本化 · [0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) 通用模型配置与当前基线 · [0019](./0019-incident-severity-thresholds.md) 故障升级阈值

## 总表

| 编号 | 标题 | 状态 | 关系 |
|---|---|---|---|
| [0000](./0000-migrate-from-dify-to-langgraph.md) | 从 Dify 工作流迁移到 LangGraph | 已采纳（元 ADR） | 现状见 0024 |
| [0001](./0001-rewrite-app-with-harness-first.md) | 推倒重写 `app/`，Harness-first | 已采纳（重写已完成） | 标的职责见 0025；评测门见 0030 |
| [0002](./0002-comprehensive-runtime-harness.md) | 综合运行时 Harness 三位一体 | 已采纳（确定性评分与闭环待迁移） | 节点层由 0029 补充 |
| [0003](./0003-prompt-versioning-by-git-branch.md) | 提示词版本化：git 分支 + 单文件 | 已采纳（形态为 git 分支 + 单文件；旧代码待迁移） | — |
| [0004](./0004-trace-granularity-node-level.md) | Trace 颗粒度：节点级入库 + LangFuse 完整 I/O | 已采纳 | 后台见 0014 |
| [0005](./0005-annotation-roles-judge-plus-business-spotcheck.md) | 标注闭环：确定性断言 + 业务方复核 | 已采纳（评分与闭环待迁移） | 平台由 0014 确定 |
| [0009](./0009-mysql-version-and-tdsql-compatibility.md) | MySQL 协议 + TDSQL 生产环境 | 已采纳（TDSQL 待现场实测） | — |
| [0014](./0014-langfuse-as-harness-backend.md) | LangFuse 作为 Harness 后台 | 已采纳 | 修订 0004 / 0005 |
| [0019](./0019-incident-severity-thresholds.md) | 故障升级阈值 P0 / P1 / P2 | 已采纳 | 与 0030 D3 互补 |
| [0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) | 通用模型配置与 DeepSeek Pro 当前基线 | 已采纳（通用配置已实现，切换模型需验收） | — |
| [0021](./0021-text-confirm-replaces-interrupt.md) | 单次指令处理：LangGraph 识别提交，Java 决定流程 | 已采纳（不做本地二阶段，代码待收敛） | 本次动作与引用选择见 0027 D5；会话持久化独立保留 |
| [0023](./0023-prompt-as-code-langgraph.md) | 提示词即代码：PromptSpec | 已采纳 | 输出契约由 0027 收敛 |
| [0024](./0024-langgraph-native-rearchitecture.md) | LangGraph 原生重构目标架构 | 已采纳（已冻结） | 拆出 0025-0029；D3 由 0031 修订，D4 幂等职责由 0026 修订 |
| [0025](./0025-instrument-resolution-delegated-to-backend.md) | 标的识别职责边界：Java 调用识别工作流 | 已采纳（追认） | 修订 0001 D4 / 0023 / 0024 |
| [0026](./0026-request-idempotency-uncertain-receipts-reconciliation.md) | 调用端幂等职责与单次调用回执契约 | 已采纳（职责规范，代码待调整） | 修订 0024 D4；模型额度见 0031 |
| [0027](./0027-field-evidence-contract.md) | 字段来源契约 | 已采纳（接口类型清洗，业务数值归 Java） | 修订 0023 D2；模型重试见 0031 |
| [0028](./0028-session-entry-and-multi-instruction-send-orchestration.md) | 会话保护入口分流与单动作多订单 | 已采纳 | 解析约束见 0031 |
| [0029](./0029-node-level-debug-api-and-regression-workbench.md) | 节点级调试接口与 Langfuse 回归闭环 | 已采纳（节点执行已建成，闭环待迁移） | 细化 0024 D6 |
| [0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md) | 目标重述与统一评测门 | 已采纳 | 修订 0001 / 0002 / 0005 / 0019 / 0024 D8 |
| [0031](./0031-single-model-request-per-message.md) | 单次工具调用全链路最多一次模型请求 | 已采纳（目标约束，代码待重构） | 修订 0001 D5 / 0024 D3 / 0027 D2；调用职责见 0026 |

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
