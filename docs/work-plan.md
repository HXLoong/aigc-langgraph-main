# 工作计划 · 原生 LangGraph 重构 + 数据集评测 + Harness 工程

> 目标口径：[ADR 0030](./adr/0030-goal-restatement-native-langgraph-dataset-eval-harness.md)。
> 本文件取代 2026-05 的 `docs/m3-m4-roadmap.md`（M1–M4 里程碑任务图，已于 2026-09-22 退役）；不再维护任务码与 owner 表。需人工裁决 / 执行的项以 GitHub issue 跟踪（`ready-for-human`），其余完成项直接从表里划掉。

## 1. 三条主线与现状

| 主线 | 已落地（截至 2026-09-22） | 未完成 |
|---|---|---|
| **原生 LangGraph 重构** | 子图原生嵌入、单动作多订单、RetryPolicy、State 分层与 output schema（ADR 0024 / 0028）；持久化与幂等、回执、对账（0026）；字段证据契约（0027）；标的识别移交 Java（0025）；Dify 资产冻结（0024 D1） | 协议原生化暂缓，保留现行 Java wire 契约（#222）；`app/tools/ticker_client.py` 去留（#231）；Store（按诉求） |
| **数据集评测与评估** | 显式验收集 `tests/fixtures/categories/`（三方言唯一加载器）；REJECTED 单独成桶、早停记失败；LLM Judge（`scripts/langfuse/langfuse_eval.py`）；节点级 fixture 与 `harness node-run`（0029） | 上线观察层基线（5xx / cascade / P95）按当前模型重测（#233）；`unified_golden.jsonl` 是否并入统一验收（#235）；D 桶（客户真实输入）回流与标注运营（#236）；写类 case `expected.place_params` 补齐（#220） |
| **Harness 工程** | CI 在 push / PR 上跑 fast + full 两个 job（ruff、mypy、四项一致性 lint、全量 pytest、MySQL service）；PromptSpec（0023）；trace_id 贯穿与结构化日志（0004 / 0024 D5） | 真实数据库回归按本地环境 opt-in；节点 fixture 漂移守护；VL 接线后 `llm_failure_high` 按模型拆阈值（#232） |

评测门只有一套，见 ADR 0030 D3：数据集 PASS 率不低于前值 → 节点 fixture 回归 → CI 全绿 → 上线观察指标。

## 2. 客户现场部署与运维（已就绪的能力）

- `scripts/deploy-customer.sh` 一键部署 + smoke 自检；`.env.customer.template`；`infra/langfuse/` self-hosted 栈
- `scripts/rollback_canary.sh` 应急回切、`scripts/drill_smoke.sh` 演练 smoke、`scripts/canary_status.py` / `scripts/metrics_snapshot.py` 灰度状态与指标快照、`scripts/run_alerts.py` 阈值告警干跑、Grafana 面板模板（`infra/`）
- `docs/on-call-runbook.md` 值班手册（严重等级对齐 ADR 0019）；回切演练在首次切流前执行
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
- `docs/on-call-runbook.md` · 值班手册 / `docs/troubleshooting-sop.md` · 生产排障
- `docs/langgraph-reconstruction-20260918.md` · 重构执行记录
