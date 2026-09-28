# 工作计划 · 原生 LangGraph 重构 + 数据集评测 + Harness 工程

> 目标口径：[ADR 0030](./adr/0030-goal-restatement-native-langgraph-dataset-eval-harness.md)。
> 不维护任务码与 owner 表。需人工裁决 / 执行的项以 GitHub issue 跟踪（`ready-for-human`），完成项直接从表里划掉。

## 1. 三条主线与现状

| 主线 | 已落地（截至 2026-09-24） | 未完成 |
|---|---|---|
| **原生 LangGraph 重构** | 子图原生嵌入、单动作多订单、RetryPolicy、State 分层与 output schema（ADR 0024 / 0028）；会话持久化与回执处理；现有字段来源记录（0027 的归一化与数字校验新边界待迁移）；标的识别移交 Java（0025）；Dify 资产冻结（0024 D1） | 单次工具调用一次模型请求重构（ADR 0031，见 §1.1）；取消本地二阶段要求及确认参数收敛（ADR 0021，见 §1.2）；请求幂等、回放、重投静默与对账代码清理（ADR 0026，见 §1.3）；字段归一化与数字校验清理（§1.4）；deepseek-v4-pro 统一配置与输入能力核对（§1.5）；协议原生化暂缓，保留现行 Java wire 契约（#222）；Store（按诉求） |
| **数据集评测与评估** | 显式业务验收集 `tests/datasets/biz/` + 意图集 `tests/datasets/intent/`（A 方言；Excel 导出共用 biz）；REJECTED 单独成桶、早停记失败；既有评测脚本（Judge 路径待移除）；节点调试 API 与 `harness node-run`（0029，旧 git 节点 fixture 已退役） | 统一确定性断言、Langfuse 回归闭环（§1.6）；目标模型生产同拓扑基线与 7 天观察仍待验收，现有默认值只是原有 dry-run 参考；D 桶（客户真实输入）回流与标注运营（#236）；写类 case `expected.place_params` 补齐（#220） |
| **Harness 工程** | CI 在 push / PR 上跑 fast + slow 两个 job（ruff、mypy、五项一致性 lint、全量 pytest；真实 MySQL 用例不进 CI）；PromptSpec（0023）；trace_id 贯穿与结构化日志（0004 / 0024 D5） | 真实数据库回归按本地环境 opt-in；节点 fixture 漂移守护；deepseek-v4-pro 零重试基线重测；本阶段不处理独立 VL 接线及拆分阈值 |

评测门只有一套，见 ADR 0030 D3：数据集 PASS 率不低于前值 → 节点 fixture 回归 → CI 全绿 → 上线观察指标。

## 1.1 单次工具调用最多一次模型请求（规范已采纳，代码待重构）

[ADR 0031](./adr/0031-single-model-request-per-message.md) 本阶段覆盖互换、期权、平仓的文本与 Excel，图片暂不处理；按每次工具调用独立计算模型额度；调用端对同一消息重试时重新计数，总重试预算归调用端。当前代码仍存在主图分类后子图再次解析、图片 OCR 后抽取、Excel 逐行调用及 LLM 图层重试；尚未满足新规范。

- 合并产品/意图/原文候选及有歧义的候选选择；规则明确产品时用产品专用联合解析，歧义输入一次得到完整语义结果。保留平仓引用、订单查询等上下文依赖和确定性业务节点。
- 关闭调用内所有 LLM 重试，分离模型解析与可重试的后端只读查询；在模型请求边界落实本次调用额度，错误后停止本次模型处理，不通过自行重启整图重置额度。
- Excel 确定性读取后一次批量解析；图片暂不处理，旧图片 / OCR 链不作为本阶段实现目标，收到图片时引导改用文本或 Excel。容量超限时保留全部订单与来源，不静默截断。
- 迁移 PromptSpec、节点执行目录、fixture 与主图/子图各自的流程文档；验证请求次数与业务正确性，并按零重试口径重测失败率、成本和延迟。执行 ADR 0030 统一评测门。

本轮只完成规范与文档，不代表上述代码迁移或业务验收完成。

## 1.2 确认指令职责收敛（规范已采纳，代码待调整）

[ADR 0021](./adr/0021-text-confirm-replaces-interrupt.md) 明确不做 LangGraph 二阶段处理：每次识别并提交本次动作，Java 决定业务流程。现有确认 type 保留用于用户明确输入，不把普通动作自动提升为确认。当前互换与平仓确认主要提交订单号；期权 `app/subgraphs/option/extract_confirm_place.py` 仍通过 `place_params.py` 从引用与历史拼装完整参数。

- 清理 LangGraph 提示词、路由和展示中强制"申请后再确认"的本地要求，不新增等待态或 interrupt；Java 既有 type / DTO 语义及真实回执保持不变。
- 收敛期权确认提取：普通确认只携带订单号等必需字段；允许补参时只提取本次明确给出的增量，已有订单数据由 Java 获取。保留现有接口、DTO、机器人上下文与确认口令，不扩展补参准入。
- 保留消息动作与引用范围的一致性校验，确认不依赖本地订单历史；Java 的订单不存在、状态或权限拒绝按现有回执规则处理。checkpointer 配置与运行要求不变。
- 代码调整按 RED → GREEN 验证：普通动作不被本地二次确认拦截、不自动变成确认动作，单单 / 多单引用确认、明确补参、没有本地订单历史、历史或卡片旧值不回填、Java 业务拒绝；再跑受影响关键测试，真实写入回归按授权验收安排执行。

本轮仅修订文档与开发规则；上述代码调整与业务验收尚未完成。

## 1.3 调用端幂等职责与工具调用边界（规范已采纳，代码待调整）

[ADR 0026](./adr/0026-request-idempotency-uncertain-receipts-reconciliation.md) 明确消息防重、并发调度、重投和重复通知归调用端，交易执行幂等与结果核查归 Java 业务端；LangGraph 返回单次合法调用的真实结果。当前代码仍按消息 ID 占位、回放成功或失败快照，并保留重投静默与对账能力，尚未符合该职责规范。

- 清理 HTTP 入口的占位、防重、快照读写及历史响应回放，移除应用启动接线、幂等存储与配套配置；同一消息 ID 的合法调用每次独立执行，继续传递原消息标识并生成独立 trace。
- 清理系统重投通知投影及配套对账模块、CLI；不再由 LangGraph 根据重投标记静默 `code=900`，也不读取 Java 访问日志重建回放响应。保留其它既有业务静默条件。
- 同步处理响应中的 `replayed`、`idempotency_status` 和重投静默元数据，以及部署模板、HTTP tape 工具、相关测试中的幂等依赖；届时核对调用端兼容性并更新真实 wire 契约，不借此扩大协议迁移范围。
- 会话 checkpointer、节点审计、原文与身份传递、确认校验、单次调用预算、E1–E5、真实回执和 `set-intent` 回复契约独立保留。交易写节点不自动重试；回执不确定只描述执行结果，不作为消息锁。
- 在后续实施中核对 `langgraph_message_log` 的剩余使用者与审计需求，单列历史记录保留和表结构处置方案；本轮不修改 SQL、迁移或清理数据。Java 源码、配置和业务接口保持不变，外部幂等能力不列为本仓已完成项。
- 代码调整按 RED → GREEN 验证：相同消息 ID 连续调用分别执行；首次 502 / 504 后再次调用不回放旧错误；并发调度不由 LangGraph 消息锁接管；重投标记不改变本次业务回复；同一消息的每次调用独立遵守模型额度，内部重试不能重置额度。回归超时取消、回执校验、消息写回与审计，真实交易验证按授权验收安排执行。

本轮仅完成规范、关联文档及开发规则同步。运行时的幂等开关、存储、HTTP 行为和历史记录均未改变，后续代码清理与业务验收尚未完成。

## 1.4 字段来源与业务参数边界（规范已采纳，代码待迁移）

[ADR 0027](./adr/0027-field-evidence-contract.md) 已改为保留结构、来源、引用选择与字段记录，不做 LangGraph 业务归一化和数字校验；Java 校验业务值并处理默认值。

- 核对现有 Java DTO 对数量、价格、比例、枚举和日期的输入要求，列出提取值与 wire 字段的差异；不修改 Java 源码 / DTO，不静默透传不兼容值。
- 清理 `app/extraction/fields.py` 的数字独立边界检查，以及各产品 normalize / sanitize / place_params 与客户端 validator 中的业务换算、数值范围、精度重算与默认值补齐；保留必要的结构、传输类型、身份和引用范围处理。
- 同步 PromptSpec / Pydantic 字段描述、字段账本、锁定与原文来源，确保实际提交值可追踪，不把纯序列化改成另一套隐藏业务计算。
- 最小 RED → GREEN 覆盖单位、比例、小数、未提供字段、多订单字段关联及 Java 拒绝；采用确定性 expected 比较，不降低字段或订单覆盖。真实接口兼容性未经验证前不能宣称该迁移完成。

## 1.5 deepseek-v4-pro 统一配置（规范已采纳，配置与验收待核对）

[ADR 0020](./adr/0020-unify-all-llm-on-deepseek-v4-pro.md) 指定统一模型 `deepseek-v4-pro`，本阶段仅处理文本与 Excel，图片暂不处理，也不接独立 VL；本轮仅更新文档，没有修改 `.env`、代码默认值、密钥或部署配置。

- 核对当前与现场网关的 Pro 模型标识、文本及结构化输出，统一各模型工厂；沿用 `QWEN_*` 名称作为兼容配置，不因保留旧 VL 配置而调用另一型号。
- Excel 先由代码读取，全部行共用 ADR 0031 的一次请求；图片及含图片的混合输入在请求模型前提示改用文本或 Excel，不静默忽略图片、不调用 OCR 或备用模型；容量超限同样明确失败。
- 在 Pro、关闭思考与零重试条件下重跑授权范围的文本 / Excel 样本，核对订单与 Excel 数据完整性、准确性、失败率、成本和延迟；图片只核对未进入业务解析的入口边界，不做识别质量验收；既有告警数值先保留，实测后按 ADR 0019 同步更新。
- 独立 VL 接线与按 VL 型号拆阈值不属于本阶段任务。

## 1.6 确定性评分与 Langfuse 回归闭环（规范已采纳，代码待迁移）

[ADR 0005](./adr/0005-annotation-roles-judge-plus-business-spotcheck.md) 规定意图、业务及节点数据集均用确定性断言；[ADR 0029](./adr/0029-node-level-debug-api-and-regression-workbench.md) 规定逐步迁移到 Langfuse Dataset / Experiment / Score 闭环，保留 harness 执行与比较能力。

- 清理批量评测的 LLM Judge 请求、默认配置与失败兜底评分；未迁移前显式使用 `--no-judge`，且不能把仅关闭 Judge 当成全量字段断言已达标。异步评分结果须完整汇总再决定退出码。
- 统一期望字段、文本断言、差异报告与退出码；缺少 required expected、执行结果或上下文时不能判 PASS。评测数值比较独立于 ADR 0027 的业务数值校验边界。
- 现役 biz / intent 以审阅后的 fixture 为基线，按稳定 case ID、套件和版本单向发布 Dataset；Langfuse 新业务 / 意图标注导出、复核后合入对应 fixture，不自动双向覆盖。
- 旧 git 节点 fixture 目录已退役且无现成替代；从 observation 复核节点样本后逐步接入 Langfuse 数据集，不恢复退役目录。缺少有效样本时记录待验收，不宣称节点回归通过。
- 逐节点接入 Experiment、确定性 Scores 和来源 observation；同批输入在本地与平台的结果必须一致，带写副作用节点仍 SKIP，真实 Java 全链路验收继续按授权调度。
- 完成 Trace → 标注 → Dataset → Experiment → 断言差异 → 修复重跑的闭环，记录数据集 / 断言 / 代码 / 模型版本；迁移期间不升级 SDK 或自托管部署，不变更外部账号、数据和评分器配置。

## 2. 客户现场部署与运维（已就绪的能力）

- `scripts/deploy-customer.sh` 一键部署 + smoke 自检；`.env.customer.template`；`infra/langfuse/` self-hosted 栈
- `scripts/rollback_canary.sh` 应急回切、`scripts/drill_smoke.sh` 演练 smoke、`scripts/canary_status.py` / `scripts/metrics_snapshot.py` 灰度状态与指标快照、`scripts/run_alerts.py` 阈值告警干跑、Grafana 面板模板（`infra/`）
- `docs/operations/on-call-runbook.md` 值班手册（严重等级对齐 ADR 0019）；回切演练在首次切流前执行
- `scripts/shadow_compare.py` 为可选对照工具，不进任何门
- 待办：离线依赖包（pip wheel + docker save）；runbook 附录 A 真实 URL / 联系人回填与回切演练后升 v1.0（#234）

## 3. 后续优化方向（不阻塞主线）

- 评估 → 优化 → 再评估的自动闭环：错例聚类 → 改进 patch → A/B 评估
- Agentic memory：跨会话经验记忆 + 客户级隔离
- 回流集自动化：生产流量 → D 桶 + 人工标注 UI + 客户内网合规同步（需先与客户对齐"AI 数据标注员"角色）
- 提示词持续调优与解析契约对比（目标统一 deepseek-v4-pro，ADR 0020；暂不建设多模型矩阵）

## 4. 相关文档

- `docs/adr/README.md` · 决策索引与待办表
- `docs/testing/README.md` · 测试分层与真后端切换
- `docs/operations/on-call-runbook.md` · 值班手册 / `docs/operations/troubleshooting-sop.md` · 生产排障
