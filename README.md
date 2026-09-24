# OTC Agent · 场外衍生品 AI 指令助手

基于 **FastAPI + LangGraph + MySQL + LangFuse** 的企微场外衍生品指令解析平台，从 Dify 工作流迁移而来。

> 目标（[ADR 0030](./docs/adr/0030-goal-restatement-native-langgraph-dataset-eval-harness.md)）：**用原生 LangGraph 重构场外 AI 指令链路，通过数据集进行评测和评估，按 Harness 工程的要求推进每一次改动。** 现状与待办见 [docs/work-plan.md](./docs/work-plan.md)。

## 三条主线

| 主线 | 内容 | 主要 ADR |
|---|---|---|
| **原生 LangGraph 重构** | 子图原生嵌入、单动作多订单、RetryPolicy、State 分层与 output schema；幂等 / 回执 / 对账；字段证据契约；标的识别移交 Java 后端；Dify 只作历史参照 | 0024 · 0025 · 0026 · 0027 · 0028 |
| **数据集评测与评估** | ground truth 是数据集 `expected`：意图集 `tests/fixtures/intent/`（只调 LLM，CI 可跑）+ 业务验收集 `tests/fixtures/categories/`（依赖 Java）+ 节点级 fixture；harness HTTP 回归 + LLM Judge；错例先补 fixture 再修代码 | 0002 · 0005 · 0014 · 0029 · 0030 D3 |
| **Harness 工程** | 任何提示词 / 节点 / 契约改动走同一条门：TDD、pytest、五项一致性 lint、ruff / mypy、数据集 PASS 率不低于前值、trace 可归因；CI 在 push / PR 上跑 | 0003 · 0004 · 0023 · 0030 |

**已就绪的部署与运维工具链**：`scripts/deploy-customer.sh`（一键部署 + smoke）、`scripts/rollback_canary.sh`（应急回切）、`scripts/drill_smoke.sh`（演练）、`scripts/canary_status.py` / `scripts/metrics_snapshot.py`（灰度状态与指标快照）、`scripts/run_alerts.py`（阈值告警干跑）、`scripts/shadow_compare.py`（可选对照，不进任何门）、Grafana 面板模板（`infra/grafana/`）、[on-call 值班手册](./docs/operations/on-call-runbook.md)。

## 快速开始

```bash
pip install -e ".[dev]"                        # 安装
uvicorn app.main:app --reload                  # 启动：POST /v1/workflows/run（兼容 Dify Workflow Run API）
USE_MYSQL_CHECKPOINTER=false REQUEST_IDEMPOTENCY=false ENABLE_LANGFUSE=false \
  pytest tests/test_smoke.py -q                # 轻量测试
```

数据库初始化、LangFuse 自托管、业务回归与评测命令见 [docs/development/README.md](./docs/development/README.md)
与根 `CLAUDE.md`「关键命令」；测试分层见 [docs/testing/README.md](./docs/testing/README.md)。

## 架构一览

企微回调 → Java Worker → `POST /v1/workflows/run` → 主图入口分流（快速询价 / 存量指令 / 普通指令）→
swap / option / option_close 业务子图 → 经 Client Protocol 调用 Java。每条消息只执行一个业务动作（可含多笔订单）；
标的原文交 Java 识别（ADR 0025）。单页导览与分层见 [docs/architecture/README.md](./docs/architecture/README.md)。

## 目录

```text
app/        # LangGraph 应用：api / graph / nodes / subgraphs{swap,option,close} / extraction / execution / tools / prompts
harness/    # 评测台：python -m harness <doctor|run|node-run>、意图级 runner、Langfuse Evaluator
scripts/    # 评估入口、真后端探针、灰度与运维、一致性 lint（目录页见 scripts/CLAUDE.md）
infra/      # LangFuse self-hosted Compose + Grafana 面板模板
tests/      # 单测 / 子图 / 节点 / 集成；fixtures/ 为意图集、业务验收集与节点级 fixture
docs/       # 文档地图与存放规则见 docs/README.md
sql/        # 业务库初始化与迁移
mock_api/   # Java / GOATS 后端的本地 mock（意图集 CI 与集成测试用）
```

## 文档入口

- [docs/README.md](./docs/README.md) —— 文档地图与存放规则
- [CONTEXT.md](./CONTEXT.md) —— 领域术语与概念边界
- `CLAUDE.md` + `.claude/rules/` —— 项目纪律真源；团队主用的 Codex 读由 `scripts/sync_agents_md.py` 生成的 `AGENTS.md`
- [docs/training/skills-guide.md](./docs/training/skills-guide.md) —— Claude Code 与 Codex 共用的 Skills 用法

## License

Internal — 图灵科技
