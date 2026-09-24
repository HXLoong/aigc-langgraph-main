# 工作计划 · 原生 LangGraph 重构 + 数据集评测 + Harness 工程

> 目标口径：[ADR 0030](./adr/0030-goal-restatement-native-langgraph-dataset-eval-harness.md)。
> 不维护任务码与 owner 表。需人工裁决 / 执行的项以 GitHub issue 跟踪（`ready-for-human`），完成项直接从表里划掉。

## 1. 三条主线与现状

| 主线 | 已落地（截至 2026-09-23） | 未完成 |
|---|---|---|
| **原生 LangGraph 重构** | 子图原生嵌入、单动作多订单、RetryPolicy、State 分层与 output schema（ADR 0024 / 0028）；持久化与幂等、回执、对账（0026）；字段证据契约（0027）；标的识别移交 Java（0025）；Dify 资产冻结（0024 D1） | 单消息一次模型请求重构（ADR 0031，见 §1.1）；协议原生化暂缓，保留现行 Java wire 契约（#222）；Store（按诉求） |
| **数据集评测与评估** | 显式业务验收集 `tests/fixtures/biz/` + 意图集 `tests/fixtures/intent/`（A 方言）；REJECTED 单独成桶、早停记失败；LLM Judge（`scripts/langfuse/langfuse_eval.py`）；节点级调试 API 与 `harness node-run`（0029，节点级 fixture 已退役） | 生产同拓扑基线（本地 dry-run 参考值已回填告警默认值）与 7 天观察仍待验收；D 桶（客户真实输入）回流与标注运营（#236）；写类 case `expected.place_params` 补齐（#220） |
| **Harness 工程** | CI 在 push / PR 上跑 fast + full 两个 job（ruff、mypy、五项一致性 lint、全量 pytest；真实 MySQL 用例不进 CI）；PromptSpec（0023）；trace_id 贯穿与结构化日志（0004 / 0024 D5） | 真实数据库回归按本地环境 opt-in；节点 fixture 漂移守护；VL 接线后 `llm_failure_high` 按模型拆阈值（#232） |

评测门只有一套，见 ADR 0030 D3：数据集 PASS 率不低于前值 → 节点 fixture 回归 → CI 全绿 → 上线观察指标。

## 1.1 单条消息最多一次模型请求（规范已采纳，代码待重构）

[ADR 0031](./adr/0031-single-model-request-per-message.md) 覆盖互换、期权、平仓与附件。当前代码仍存在主图分类后子图再次解析、图片 OCR 后抽取、Excel 逐行调用及 LLM 图层重试；尚未满足新规范。

- 合并产品/意图/原文候选及有歧义的候选选择；规则明确产品时用产品专用联合解析，歧义输入一次得到完整语义结果。保留平仓引用、订单查询等上下文依赖和确定性业务节点。
- 关闭所有 LLM 重试，分离模型解析与可重试的后端只读查询；在模型请求边界落实单轮额度，错误后停止本轮模型处理。
- Excel 确定性读取后一次批量解析，图片一次多模态解析；容量超限或能力不足时明确引导调整输入，保留全部订单与附件证据。
- 迁移 PromptSpec、节点执行目录、fixture 与主图/子图各自的流程文档；验证请求次数与业务正确性，并按零重试口径重测失败率、成本和延迟。执行 ADR 0030 统一评测门。

本轮只完成规范与文档，不代表上述代码迁移或业务验收完成。

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
- 提示词持续调优与多模型矩阵（当前统一 DeepSeek-V4-pro，ADR 0020）

## 4. 相关文档

- `docs/adr/README.md` · 决策索引与待办表
- `docs/testing/README.md` · 测试分层与真后端切换
- `docs/operations/on-call-runbook.md` · 值班手册 / `docs/operations/troubleshooting-sop.md` · 生产排障
