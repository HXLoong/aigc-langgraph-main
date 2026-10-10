# ADR 0000 · 从 Dify 工作流迁移到 LangGraph

## 状态

- 状态：已采纳
- 日期：2026-05-10
- 关系：2026-09-28 按迁移前 Dify 资产实测重写「背景」的论证与动机排序，2026-09-29 统一为「所有权」口径（简单单向图同样以所有权转移为主因；④ 的前提写明为"已经复杂"而非"未来可能复杂"）；后果段被 [ADR 0024](./0024-langgraph-native-rearchitecture.md) 修订（Dify 退出上游）；"如何重写"见 [ADR 0001](./0001-rewrite-app-with-harness-first.md）
- 作者：图灵科技 + Tony

## 背景：痛点不在"图复杂度"，而在 Workflow 的所有权

迁移理由与图复杂度无关：**即使工作流再简单，所有权也应从低代码平台转移到代码库**——配置态对象进不了 Git / PR / Test / CI，改一个规则也得在平台 UI 上手工操作。本项目连这条"简单"的前提也不成立：迁移前的工作流是一个**多分支多出口**的编排（而非单向 DAG），所以"未来可能变复杂"更不构成理由——它已经复杂。按迁移前 Dify 导出快照（`kind: app`、`version: 0.5.0`、`mode: advanced-chat`）实测：

| 维度 | 实测值 |
|---|---|
| 规模 | 76 个节点 / 107 条边 |
| 节点构成 | LLM 28、Code 22、if-else 10、variable-aggregator 5、answer 5、http-request 5、start 1 |
| 出口 | 5 个 answer 节点（按产品与机器人版本分流） |
| 外部依赖 | 仅 5 个 http-request：4 × `message/set-intent` + 1 × `financial-orders/query-close-order` |
| 入参契约 | start 节点 17 个输入（`conversation_id` / `message_id` / `quote_content` / `existing_command` / `robot_version` / `retry_origin` / `retry_attempt` / 对手清单等） |
| 模型 | qwen3-30b-a3b + qwen2.5-vl-3b-instruct（含图片识别节点） |
| **没有**的节点 | 无 loop / iteration、无 agent、无知识检索、无 tool |

由此得到两条必须写清的边界：

- 复杂度**不是待证明的假设**：10 个条件分支 + 5 个变量聚合器，本身就是多分支、多出口、手工模拟并行汇合的编排。
- 循环与 HITL **都不是**迁移理由：迁移前没有 loop 节点；现行架构也明确不做二阶段与 interrupt（[ADR 0021](./0021-text-confirm-replaces-interrupt.md)）。

真正的痛点是**所有权**：

> Dify：Workflow = **Application Configuration**（平台里的配置对象）
> LangGraph：Workflow = **Program / Runtime Object**（仓库里的程序对象）

配置态对象进不了软件工程流程，具体表现为四个痛点（[ADR 0002](./0002-comprehensive-runtime-harness.md) 按这四个痛点承接目标）：

1. **业务逻辑的所有权在平台上，不在代码库里**：22 个 Code 节点 + 10 个 if-else 承载参数解析与意图分流，规则只能作为平台配置对象存在，无法 diff、review 或静态分析，每次改动都是黑盒变更，也无法按分支 / commit 追踪版本。
2. **无法自动化监测**：节点级延迟、错误率、LLM 命中率留在平台内，进不了统一可观测体系，日志与指标也无法与业务链路关联。
3. **无法自动化回归（CI/CD 缺位）**：改动必须真实部署到平台才能验证，测试集进不了流水线、没有门禁，发版只能人工抽测，误改随改动量线性放大。
4. **无法评估大模型处理质量**：缺少数据集与评分机制，提示词调整只能凭直觉。

### 动机排序：哪一条是决定性的

| 序 | 动机 | 本项目判定 |
|---|---|---|
| ① | 需要**代码优先**的软件工程流程（Git / PR / Test / CI） | **决定性**：28 个 LLM 节点与 22 个 Code 节点的规则必须可 diff、可回归、可按版本灰度 |
| ② | Workflow 必须**深度嵌入现有代码系统**（SDK / DB / 权限 / 业务逻辑） | **决定性**：业务依赖 Java 内部接口与 GOATS；密钥与地址只能以平台环境变量 / secret 寄存，沙盒里没有依赖包、连接池、类型检查与统一日志 |
| ③ | 已明确需要 **LangGraph 运行时语义**（State / Persistence / 图级控制流） | **成立但需精确**：17 个入参表明会话状态、引用消息与重试语义必须显式建模；5 个 variable-aggregator 是平台里手工模拟的并行汇合。**循环与 HITL 不在此列** |
| ④ | 未来可能变复杂 | **不单独成立**：只作方向性加分项，后续由子图与意图扩张规则承接（[ADR 0024](./0024-langgraph-native-rearchitecture.md)；归属判定见 PR 模板「子图归属判定」） |

一条与本决议直接相关的差异：迁移前的重试是 http-request 节点内的配置（`max_retries` 1~3），对图不可见，因此无法表达"重试不得连带重跑模型"；图级重试与模型调用零重试是迁到代码之后才有的语义（[ADR 0031](./0031-single-model-request-per-message.md)）。

## 决策

迁移到 **LangGraph + FastAPI**：① ② ③ 三项诉求在配置态工作流里无解，业务逻辑因此回到代码（可 diff / review / 静态分析），能在 CI 里跑数据集闭环，节点产出结构化 trace 与指标供监测和评估，外部依赖经 Client Protocol 直连现有代码系统。④ 只作方向性加分项，不写入成功判据。

## 备选方案

- **保留 Dify**：低代码平台在简单单向图里确实省事——改一个提示词或参数在画布上点两下就生效；Web UI、API Key 管理、多租户、鉴权、文档切片与向量检索开箱即用；PM 与运营可直接改画布，不必排队等后端发版。但这条"更划算"只成立于**不要求工程流程与内部集成**的场景，本项目即使按简单单向图衡量也不成立：核心是场外衍生品交易指令——提示词与解析规则的改动不允许绕过 PR 与数据集回归直接进生产（[ADR 0005](./0005-annotation-roles-judge-plus-business-spotcheck.md)）；Web UI 与鉴权由客户侧 Java 与企微承载，LangGraph 只接收已带身份的入参（`room_id` / `operator_user_id` / `guid`）；迁移前资产**没有**知识检索节点（内置 RAG 用不上）；协作改由业务方复核数据集承担。① ② ③ 三项诉求在配置态工作流里无解。
- **自研 DAG 引擎**：可控但开发量大，且失去 LangGraph 生态（checkpointer、structured output、子图）。
- **LangGraph + FastAPI（已选）**：生态成熟，子图嵌套为一等公民，可在进程内完整测试。

## 现状

评测与追踪基础能力已建成（见 [ADR 0002](./0002-comprehensive-runtime-harness.md)）：`harness/` 评测台、节点级 trace（MySQL + LangFuse）与业务数据集。自动评分按 ADR 0005 统一为确定性断言，Langfuse 回归闭环按 ADR 0029 逐步迁移，现状与待办见工作计划。

现状：**Dify 已退出上游地位**（[ADR 0024](./0024-langgraph-native-rearchitecture.md) D1）：代码与 git 中的提示词是唯一真源，不再有 Dify 同步链路；Shadow 对照只是可选工具，验收以数据集评测门为准（[ADR 0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md) D3）。
