# 架构决定记录（ADR）索引

本目录收录 otc-agent 的全部架构决定：**ADR 0000-0030（共 31 篇）**。

项目目标（[ADR 0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md)）：**用原生 LangGraph 重构场外衍生品 AI 指令链路，通过数据集进行评测和评估，按 Harness 工程的要求推进每一次改动。** 早期的 M1–M4 里程碑、任务码与 GitHub issue 跟踪口径已于 2026-09-22 从 ADR 退役；历史裁决只保留日期与结论。

每篇 ADR 按"现状口径"维护：读起来即当前实现；实现违背决策原意之处以"实现偏离"小节标注并写明裁决结论，不洗白。

## 总表

| 编号 | 标题 | 状态 | 取代/修订关系 |
|---|---|---|---|
| [0000](./0000-migrate-from-dify-to-langgraph.md) | 从 Dify 工作流迁移到 LangGraph | 已采纳（元 ADR） | 后果段被 **0024** 修订 |
| [0001](./0001-rewrite-app-with-harness-first.md) | 推倒重写 `app/`，Harness-first 范式 | 已采纳（重写已完成） | D4 / D6 ticker 段被 **0025** 反转；D8 / D9 里程碑段被 **0030** 退役 |
| [0002](./0002-comprehensive-runtime-harness.md) | 综合运行时 Harness（三位一体） | 已采纳（开发期 / 运行期 / 调优期三面均已建成；线上标注回流未启动） | 节点层由 **0029** 补充；评测门统一到 **0030** D3 |
| [0003](./0003-prompt-versioning-by-file-coexistence.md) | 提示词版本化：同目录文件并存 | 已采纳（机制在，当前无在跑灰度） | — |
| [0004](./0004-trace-granularity-node-level-with-langsmith.md) | Trace 颗粒度：节点级入库 + 完整 I/O 关联 | 已采纳（schema 已随 0009 共库调整入库） | trace 后台被 **0014** 修订（LangSmith→LangFuse） |
| [0005](./0005-annotation-roles-judge-plus-business-spotcheck.md) | 标注闭环：LLM judge + 业务方抽检 | 已采纳（离线 Judge 在用；线上标注运营未启动） | 平台随 **0014** 定为 LangFuse |
| [0006](./0006-hitl-interrupt-boundary.md) | HITL interrupt 边界：写 + 资金双轴 | interrupt 部分被 **0021** 取代；风险象限规则沿用 | — |
| [0007](./0007-subgraph-vs-intent-scope-rule.md) | 独立子图 vs 新意图：四条触发规则 | 已采纳 | — |
| [0008](./0008-ticker-resolution-as-react-agent.md) | 标的识别采用 ReAct Agent | **已被 0025 取代**（历史存根） | — |
| [0009](./0009-mysql-version-and-tdsql-compatibility.md) | MySQL 协议 + TDSQL 生产环境 | 已采纳（2026-09-18 共库调整段为现行建表口径） | 取代 **0021** §2 的 `.setup()` 建表 |
| [0010](./0010-llm-model-selection-rules.md) | Qwen 三型号分工 | **历史背景**（被 **0020** 取代） | — |
| [0011](./0011-split-option-intent-and-extraction.md) | option 拆分 intent 与 extraction | 已采纳（1 intent + 7 extract，其中 4 个已去 LLM 化） | 输出契约随 **0027** 收敛 |
| [0012](./0012-restore-backend-http-for-securities-instrument.md) | 标的查询恢复走后端 HTTP | 已采纳（结论由 **0025** 推到整个识别链路；LangGraph 侧调用点已退役） | — |
| [0013](./0013-load-dynamic-inference-prompt-fragment.md) | 加载后端动态 prompt 片段 | **已撤销**（历史存根） | ticker 域随 **0025** 删除 |
| [0014](./0014-langfuse-as-harness-backend.md) | LangFuse 作为 Harness 后台 | 已采纳 | 修订 **0004**/**0005** |
| [0015](./0015-intent-route-rules-first-llm-fallback.md) | 一级路由：规则前置 + LLM 兜底 | 已采纳（DSL v2 两层） | 入口层由 **0028** 前置 |
| [0016](./0016-m3-scope-engineering-loop-not-shadow.md) | M3 范围重定义：工程联调闭环 | **已被 0030 取代**（历史存根） | — |
| [0017](./0017-m4-canary-quantitative-exit-gate.md) | M4 金丝雀退出门量化指标 | **已被 0030 取代**（历史存根；指标并入 0030 D3） | — |
| [0018](./0018-dev-qwen-prod-deepseek-llm-split.md) | 开发 Qwen / 现场 DeepSeek 双模型分立 | **已被 0020 取代**（历史存根） | — |
| [0019](./0019-incident-severity-thresholds.md) | 故障升级阈值 P0/P1/P2 | 已采纳（VL 接线后"单一 vendor"论证待重估） | 与 **0030** D3 上线观察层互补 |
| [0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) | 全量统一 DeepSeek-V4-pro | 已采纳（§3 VL 例外已修订：视觉链路已接线） | 取代 **0018**、修订 **0010** |
| [0021](./0021-text-confirm-replaces-interrupt.md) | 文本二阶段确认替代 interrupt + checkpointer 接线 | 已采纳（§2 建表口径被 **0009** 取代） | 取代 **0006** interrupt 部分 |
| [0022](./0022-prompt-governance-after-code-migration.md) | 代码迁移完成后的提示词治理模型 | **已废弃**（2026-09-16） | 契约治理见 **0023** |
| [0023](./0023-prompt-as-code-langgraph.md) | 提示词即代码：PromptSpec | 已采纳 | 输出契约由 **0027** 收敛为原文候选 |
| [0024](./0024-langgraph-native-rearchitecture.md) | LangGraph 原生重构：目标架构 | 已采纳（**2026-09-22 冻结**，不再追加落地记录） | 取代 **0000** 后果段；D3 ticker 被 **0025** 撤销；D4 裁决见 **0026**；D6 节点层见 **0029**；D8 门槛统一到 **0030** D3 |
| [0025](./0025-instrument-resolution-delegated-to-backend.md) | 标的识别职责移交 Java 后端：LangGraph 只提取原文候选 | 已采纳（2026-09-20 落地，追认） | 取代 **0008**；修订 **0001** D4/D6、**0012**、**0023** D5、**0024** D2/D3 |
| [0026](./0026-request-idempotency-uncertain-receipts-reconciliation.md) | 请求级幂等、不确定回执与运维对账 | 已采纳（2026-09-18 落地，追认） | 修订 **0024** D4；补 **0021** |
| [0027](./0027-field-evidence-contract.md) | 字段证据契约：模型只产原文候选，Code 归一化并记录来源与锁定 | 已采纳（2026-09-18 落地，接入进度见 migration 清单） | 修订 **0023** D2、**0024** D2 |
| [0028](./0028-session-entry-and-multi-instruction-send-orchestration.md) | 会话保护入口分流与单动作多订单 | 入口沿用，多指令编排已退役 | 修订 **0015**、**0024** D3 |
| [0029](./0029-node-level-debug-api-and-regression-workbench.md) | 节点级调试接口与节点回归工作台（含 HTTP 录放） | 已采纳（2026-09-22 落地，追认） | 修订 **0024** D6；沿用 **0002** |
| [0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md) | 目标重述：原生 LangGraph 重构 + 数据集评测 + Harness 工程 | 已采纳（2026-09-22） | 取代 **0016**、**0017**；修订 **0001** D8/D9、**0002**、**0005**、**0019**、**0024** D8 |

## 按目标主线分组

- **原生 LangGraph 重构**：0000（为什么迁）→ 0001（怎么重写）→ 0007（子图扩张规则）→ 0024（目标架构，已冻结）→ 0025（标的移交后端）· 0026（幂等 / 回执 / 对账）· 0027（字段证据契约）· 0028（入口分流与单动作多订单）· 0021（文本二阶段确认）· 0015（一级路由）· 0011（option 拆分）· 0009（MySQL / TDSQL 共库）
- **数据集评测与评估**：0002（Harness 三位一体）· 0005（Judge + 业务方抽检）· 0014（LangFuse 后台）· 0004（trace 颗粒度）· 0029（节点级回归工作台）· **0030 D3（统一评测门）**
- **Harness 工程纪律**：0003（提示词版本化）· 0023（PromptSpec）· 0020（模型统一）· 0019（故障升级阈值）· 0030 D1-3 / D4
- **历史存根**：0006（HITL interrupt）· 0008（ticker ReAct）· 0010（Qwen 分工）· 0013（动态片段）· 0016（M3 范围）· 0017（M4 退出门）· 0018（双模型）· 0022（manifest 治理）

## 状态词汇表

| 状态词 | 含义 | 写法 |
|---|---|---|
| 已采纳 | 决策有效且已落地或正在落地 | 括号里写一句现状（落地日期 / 未完成项），不写计数、不写任务码 |
| 已采纳（追认） | 先有实现后补 ADR，决策本体由用户在实现时指定 | 状态行注明落地 commit 与追认日期 |
| 已被 NNNN 取代 | 新 ADR 覆盖其决策；本篇改写为历史存根（保留决策 + 为何被取代 + 指向新篇） | 不删文件、不重编号 |
| 已撤销 | 决策被放弃且无替代 ADR；正文保留为历史原文 | 已删除的路径用 `~~删除线~~` 标注 |
| 已废弃 | 引入的机制已从代码库移除 | 同上 |
| 历史背景 | 仅为后续 ADR 提供上下文 | 同上 |

被修订而非取代的 ADR 状态词不变，在头部"修订"行与正文相应段落用"**YYYY-MM-DD 修订（ADR NNNN）**"标注；README 总表的状态列须与各篇头部一致。

## 待办（需人工裁决 / 执行的项以 GitHub issue 跟踪，其余完成后直接改本表）

| 项 | 出处 | 动作 | issue |
|---|---|---|---|
| CI slow job 已包含 MySQL service；本地真实数据库用例仍需 opt-in | 0009 / 0024 D4 | 保持 CI 与本地数据库回归 | — |
| `app/tools/ticker_client.py` 在 `app/` 内无调用方 | 0025 | 删除或写明保留理由 | #231 |
| VL 接线后 `llm_failure_high` 未按 `model` 拆分；`.env.customer.template` 视觉模型留空 | 0019 / 0020 | 阈值重估 + 部署 checklist | #232 |
| 上线观察层基线（5xx / cascade / P95）待当前模型口径重测 | 0030 D3 / 0020 | 跑 `scripts/langfuse/langfuse_eval.py` + P95 重测后回填 | #233 |
| Dify 明文 key 的 revoke 无记录 | 0024 附录 | 运维确认后打勾 | #218 |
| ADR 0001 / 0024 的落地记录仍在正文内 | 0030 D4 | 迁到 `docs/` 实施日志 | — |
| `unified_golden.jsonl` 是否并入统一验收 | 0030 后果 | 三选一裁决后统一 `harness run` 默认行为 | #235 |
| `POST /v1/runs` 原生协议与 Dify wire adapter 退役 | 0024 D7 | 与 Java 侧排期 | #222 |

## ADR 写作与卫生约定

**格式**：标题 `# ADR NNNN · 中文标题`；头部中文状态行（`状态 / 日期 / 起源(可选) / 取代(可选) / 修订(可选) / 作者`），状态词按上表；被取代的 ADR 改写为历史存根，**不删文件、不重编号**（全库交叉引用经不起断）。

**口径纪律**（ADR 0030 D2 / D4）：正文不写里程碑任务码、GitHub issue / PR 编号、会腐烂的裸计数（golden 条数、测试数、提示词数、节点数）；必须写数字时标注"截至 YYYY-MM-DD"并给出真源路径。ADR 编号一律"区间优先"——`ADR 0000-00XX（共 N 篇）`。

**落地记录**：ADR 正文只保留决策 + 理由 + 后果 + 一行状态；实施过程记到 `docs/`（如 `docs/langgraph-reconstruction-20260918.md`），ADR 只链接。先有实现后补 ADR 时用"已采纳（追认）"并注明 commit。

**卫生检查**（`scripts/check_adr_refs.py`，已进 CI fast job；每 5 个新 ADR 一次人工复核）：

1. ADR 互引完整性——引用的编号必须存在，无虚悬引用
2. ADR 中反引号书写的代码路径有效性——检查时跳过 `~~删除线~~` 标注的过期段
3. 孤儿 ADR 检测——无任何入引的篇目需评估归档

**审计边界**：

- ADR 的**论证逻辑**是否仍成立需人判断，工具只核事实性声明
- 脚本只匹配反引号内带扩展名的路径；目录引用、Markdown 链接到 `docs/` 的路径、README 总表与各篇头部状态的一致性目前须人工核对
- 对 Java 侧（`aigc/api` 仓）的跨仓库引用无法自动校验，改动 Java 契约时人工核对 `docs/api-contracts/`
