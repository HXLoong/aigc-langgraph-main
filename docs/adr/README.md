# 架构决定记录（ADR）索引

本目录收录 otc-agent 的全部架构决定：**ADR 0000-0024（共 25 篇）**。

2026-08-27 全量整理（wayfinder map [#138](https://github.com/GZTL-AI/aigc-langgraph/issues/138)）：逐篇对照代码核查事实性声明后深度改写为**现状口径**——每篇读起来即当前实现；实现违背决策原意之处不洗白，以"实现偏离"小节标注并链接裁决 issue（[#153](https://github.com/GZTL-AI/aigc-langgraph/issues/153)–[#160](https://github.com/GZTL-AI/aigc-langgraph/issues/160)）。

## 总表

| 编号 | 标题 | 状态 | 取代/修订关系 |
|---|---|---|---|
| [0000](./0000-migrate-from-dify-to-langgraph.md) | 从 Dify 工作流迁移到 LangGraph | 已采纳（元 ADR） | — |
| [0001](./0001-rewrite-app-with-harness-first.md) | 推倒重写 `app/`，Harness-first 范式 | 已采纳（重写已完成） | 4 项偏离 → [#154](https://github.com/GZTL-AI/aigc-langgraph/issues/154)/[#160](https://github.com/GZTL-AI/aigc-langgraph/issues/160) |
| [0002](./0002-comprehensive-runtime-harness.md) | 综合运行时 Harness（三位一体） | 已采纳（Phase 2 因 `node_trace` schema 缺失为 🟡 / 4 🔄） | — |
| [0003](./0003-prompt-versioning-by-file-coexistence.md) | 提示词版本化：同目录文件并存 | 已采纳 | #156/#159 已裁决；同步防覆盖已落地 |
| [0004](./0004-trace-granularity-node-level-with-langsmith.md) | Trace 颗粒度：节点级入库 + 完整 I/O 关联 | 已采纳（写入代码已落地，schema 未入库） | trace 后台被 **0014** 修订（LangSmith→LangFuse）；#156 已裁决 |
| [0005](./0005-annotation-roles-judge-plus-business-spotcheck.md) | 标注闭环：LLM judge + 业务方抽检 | 已采纳（Phase 4 运营未立项） | 平台随 **0014** 定为 LangFuse；judge 版本化已由 #159 修复 |
| [0006](./0006-hitl-interrupt-boundary.md) | HITL interrupt 边界：写 + 资金双轴 | interrupt 部分被 **0021** 取代；风险象限规则沿用 | #153 已裁决 |
| [0007](./0007-subgraph-vs-intent-scope-rule.md) | 独立子图 vs 新意图：四条触发规则 | 已采纳 | 1 项偏离 → [#160](https://github.com/GZTL-AI/aigc-langgraph/issues/160) |
| [0008](./0008-ticker-resolution-as-react-agent.md) | 标的识别采用 ReAct Agent | ⚠️ 已采纳但**生产为确定性 resolver，ReAct 为死代码** | 去向裁决 → [#154](https://github.com/GZTL-AI/aigc-langgraph/issues/154) |
| [0009](./0009-mysql-version-and-tdsql-compatibility.md) | MySQL 协议 + TDSQL 生产环境 | 已采纳 | checkpointer 已随 **0021** 接线（#153 修复） |
| [0010](./0010-llm-model-selection-rules.md) | Qwen 三型号分工 | **历史背景**（被 **0020** 取代） | 强制规则从未执行 → [#158](https://github.com/GZTL-AI/aigc-langgraph/issues/158) |
| [0011](./0011-split-option-intent-and-extraction.md) | option 拆分 intent 与 extraction | 已采纳（DSL v2：7 意图 → 7 extract） | 旧 1+5 形态已被 DSL v2 演进取代；#159/#113 已关闭 |
| [0012](./0012-restore-backend-http-for-securities-instrument.md) | 标的查询恢复走后端 HTTP | 已采纳（完整落地） | — |
| [0013](./0013-load-dynamic-inference-prompt-fragment.md) | 加载后端动态 prompt 片段 | 已采纳（主链路落地） | #156 已追认结构化日志 + metrics 方案 |
| [0014](./0014-langfuse-as-harness-backend.md) | LangFuse 作为 Harness 后台 | 已采纳 | 修订 **0004**/**0005**；例外决策 + 硬闸门已落地（#155） |
| [0015](./0015-intent-route-rules-first-llm-fallback.md) | 一级路由：规则前置 + LLM 兜底 | 已采纳（DSL v2：规则层 + unknown LLM） | #158 已追认工厂语义；当前演进见文末修订 |
| [0016](./0016-m3-scope-engineering-loop-not-shadow.md) | M3 范围重定义：工程联调闭环 | 已采纳（#82-#87 已关闭；量化退出门须看当前评估证据） | 修订 **0001** D8/D9 |
| [0017](./0017-m4-canary-quantitative-exit-gate.md) | M4 金丝雀退出门量化指标 | 已采纳 | 测量缺口已修复（#157）；展示层后置 #162；阈值待 DeepSeek 重测 |
| [0018](./0018-dev-qwen-prod-deepseek-llm-split.md) | 开发 Qwen / 现场 DeepSeek 双模型分立 | **已被 0020 取代**（历史存根） | — |
| [0019](./0019-incident-severity-thresholds.md) | 故障升级阈值 P0/P1/P2 | 已采纳 | 互补 **0017**；3 项偏离已修复（#157） |
| [0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) | 全量统一 DeepSeek-V4-pro | 已采纳 | 取代 **0018**、修订 **0010**；baseline 重建为 M3.3 前置 |
| [0021](./0021-text-confirm-replaces-interrupt.md) | 文本二阶段确认替代 interrupt + checkpointer 接线 | 已采纳 | 取代 **0006** interrupt 部分；修复 **0009** checkpointer 偏离 |
| [0022](./0022-prompt-governance-after-code-migration.md) | 代码迁移完成后的提示词治理模型（manifest + lint / 版本化收敛 / 瘦身纪律） | **已废弃**（2026-09-16：manifest / lint 机制已移除；契约治理见 **0023**） | 修订 **0001 D5**、**0003**；沿用 **0014** D3-2 |
| [0023](./0023-prompt-as-code-langgraph.md) | 提示词即代码：PromptSpec 把 AgentState 输入 / Pydantic 输出 / 占位符注入声明为节点契约 | 已采纳（12 节点试点落地，其余分两批） | 补 **0022** 契约层；修订 **0022 D5**；依赖 **0020** function calling |
| [0024](./0024-langgraph-native-rearchitecture.md) | LangGraph 原生重构：退出 Dify 形态的目标架构（State 分层 / 原生子图 / 持久化与可观测契约 / harness 唯一 gate / 协议原生化）与四阶段路线 | 已采纳（阶段 0 首批已落地） | 取代 **0000** 后果段、落实 **0001 D3**"另开 ADR"；修订 **0001 D6**、**0009**、**0014 D7**；沿用 **0021**、**0023** |

## 按主题分组

- **迁移与架构**：0000（为什么迁）→ 0001（怎么重写）→ 0002（Harness 三位一体）→ 0007（子图扩张规则）→ **0024（LangGraph 原生重构，退出 Dify 形态）**
- **LLM 模型**：0010（Qwen 分工，历史）→ 0018（双轨制，历史存根）→ **0020（现行：全量 DeepSeek-V4-pro）**
- **提示词管理**：0003（版本化机制）· 0011（option 拆分）· 0013（后端动态片段）· 0022（资产治理，已废弃）· **0023（提示词即代码 / PromptSpec）**
- **数据与后端契约**：0009（MySQL/TDSQL）· 0012（标的查询走 HTTP）
- **可观测与评估**：0004（trace 颗粒度）· 0005（标注闭环）· 0014（LangFuse 后台）
- **路由与交互**：0015（一级路由四层）· 0006（HITL 边界，历史）· 0021（文本二阶段确认）· 0008（ticker 识别）
- **上线与运维**：0016（M3 = 工程闭环）· 0017（M4 退出门）· 0019（故障升级阈值）

## 实现偏离裁决索引（2026-08-27 核查产出，同日裁决）

全量核查共发现 **37 项实现偏离**，按根因聚为 8 张裁决 issue；裁决与落地状态：

| Issue | 主题 | 涉及 ADR | 状态 |
|---|---|---|---|
| [#153](https://github.com/GZTL-AI/aigc-langgraph/issues/153) | HITL/checkpoint 基础设施 | 0006 / 0008c / 0009 | ✅ 已裁决落地（ADR 0021） |
| [#154](https://github.com/GZTL-AI/aigc-langgraph/issues/154) | ticker ReAct 死代码 vs 生产 resolver | 0008 / 0001 D5 | ⏸ 暂缓（Tony 指示） |
| [#155](https://github.com/GZTL-AI/aigc-langgraph/issues/155) | LangFuse 合规与提示词闸门 | 0014 | ✅ 已裁决落地（例外决策 + 生产 raise 闸门） |
| [#156](https://github.com/GZTL-AI/aigc-langgraph/issues/156) | trace 可观测缺口 | 0004 / 0013 / 0003 | ✅ 已裁决落地（trace_id 贯穿 + 追认/轻修） |
| [#157](https://github.com/GZTL-AI/aigc-langgraph/issues/157) | 告警与退出门指标失真 | 0017 / 0019 | ✅ 已裁决落地（核心四项修复；展示层 → #162） |
| [#158](https://github.com/GZTL-AI/aigc-langgraph/issues/158) | 模型选型规则从未执行 | 0010 / 0015 / 0020 | ✅ 已裁决落地（追认 + 分化前置纪律） |
| [#159](https://github.com/GZTL-AI/aigc-langgraph/issues/159) | 提示词与 golden 治理债 | 0003 / 0005 / 0011 | ✅ 已裁决落地（judge 版本化 + 同步防覆盖；golden 缺口 → #113） |
| [#160](https://github.com/GZTL-AI/aigc-langgraph/issues/160) | 工程纪律遗留 | 0001 / 0007 | ✅ 已裁决落地（business_params 校验 + PR 模板 + 两项追认） |

## ADR 写作与卫生约定

**格式**：标题 `# ADR NNNN · 中文标题`；头部中文状态行（`状态 / 日期 / 起源(可选) / 修订(可选) / 作者`）；被取代的 ADR 改写为历史存根（保留决策 + 为何被取代 + 指向新篇），**不删文件、不重编号**（全库交叉引用经不起断）。

**卫生检查**（定期跑 `scripts/check_adr_refs.py`，落地任务 [#161](https://github.com/GZTL-AI/aigc-langgraph/issues/161)；建议每 5 个新 ADR 一次，F4 切流与 M4 退出门前必跑）：

1. ADR 互引完整性——引用的编号必须存在，无虚悬引用
2. ADR 中以 Markdown 链接书写的代码路径有效性——检查时跳过 `~~删除线~~` 标注的过期段
3. 孤儿 ADR 检测——无任何入引的篇目需评估归档

**审计边界**（沿承 2026-05-13 一致性审计的约定）：

- ADR 的**论证逻辑**是否仍成立需人（Tony）判断，工具只核事实性声明
- 反引号中的裸路径（如 `sql/schema.sql`）目前不在脚本覆盖范围，须人工核对；不要把脚本绿灯解释为全部代码路径存在
- 头部字段格式的历史差异属背景包袱，统一一次即可、不逐篇追溯 git 历史
- 对 Java 侧（`aigc/api` 仓）的跨仓库引用无法自动校验，改动 Java 契约时人工核对 `docs/api-contracts/`

**引用计数写法**：一律"区间优先"——`ADR 0000-00XX（共 N 篇）`。区间自校验，裸计数易腐。
