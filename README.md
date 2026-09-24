# OTC Agent · 场外衍生品 AI 指令助手

基于 **FastAPI + LangGraph + MySQL + LangFuse** 的企微场外衍生品指令解析平台，从 Dify 工作流迁移而来。

> 目标（[ADR 0030](./docs/adr/0030-goal-restatement-native-langgraph-dataset-eval-harness.md)）：**用原生 LangGraph 重构场外 AI 指令链路，通过数据集进行评测和评估，按 Harness 工程的要求推进每一次改动。** 现状与待办见 [docs/work-plan.md](./docs/work-plan.md)。

## 三条主线

| 主线 | 内容 | 主要 ADR |
|---|---|---|
| **原生 LangGraph 重构** | 子图原生嵌入、单动作多订单、RetryPolicy、State 分层与 output schema；幂等 / 回执 / 对账；字段证据契约；标的识别移交 Java 后端；Dify 只作历史参照 | 0024 · 0025 · 0026 · 0027 · 0028 |
| **数据集评测与评估** | ground truth 是数据集 `expected`：显式验收集 `tests/fixtures/categories/` + 节点级 fixture；harness HTTP 回归 + LLM Judge；错例先补 fixture 再修代码 | 0002 · 0005 · 0014 · 0029 · 0030 D3 |
| **Harness 工程** | 任何提示词 / 节点 / 契约改动走同一条门：TDD、pytest、四项一致性 lint、ruff / mypy、数据集 PASS 率不低于前值、trace 可归因；CI 在 push / PR 上跑 | 0003 · 0004 · 0023 · 0030 |

**已就绪的部署与运维工具链**：`scripts/deploy-customer.sh`（一键部署 + smoke）、`scripts/rollback_canary.sh`（应急回切）、`scripts/drill_smoke.sh`（演练）、`scripts/canary_status.py` / `scripts/metrics_snapshot.py`（灰度状态与指标快照）、`scripts/run_alerts.py`（阈值告警干跑）、`scripts/shadow_compare.py`（可选对照，不进任何门）、Grafana 面板模板（`infra/`）、[on-call 值班手册](./docs/on-call-runbook.md)。

## 快速开始

详见 [HOW_TO_RUN.md](./HOW_TO_RUN.md)。简版：

```bash
# 1. 安装
pip install -e ".[dev]"

# 2. 启动依赖
# 先在 Java 现有数据库执行初始化；MYSQL_URI 为唯一数据库连接配置
mysql -h <HOST> -P <PORT> -u <USER> -p --database=<JAVA_DATABASE> < sql/init.sql
docker compose -f infra/langfuse/docker-compose.yml --env-file infra/langfuse/.env up -d

# 3. 启动应用
uvicorn app.main:app --reload   # POST /v1/workflows/run（兼容 Dify Workflow Run API）

# 4. 轻量测试（全套由统一验收时运行）
USE_MYSQL_CHECKPOINTER=false REQUEST_IDEMPOTENCY=false ENABLE_LANGFUSE=false pytest tests/test_smoke.py -q

# 5. 本地 HTTP 业务回归：先准备真实授权测试账号、群及业务数据
# 联调服务可使用 ENVIRONMENT=staging uvicorn app.main:app --host 127.0.0.1 --port 8201
python scripts/local_eval.py --base-url http://127.0.0.1:8201 --data tests/fixtures/categories --case case-025 --concurrency 1
# 统一验收去掉 --case，只跑显式 categories；不默认并入 unified。
# harness run 默认范围相同；历史参考集仅 --include-unified 或 --data 显式选择。

# 6. Langfuse Dataset Experiment
python scripts/langfuse/langfuse_eval.py --dataset golden_option_inquiry_case --ids case-022 --concurrency 1

# 7. 节点级回归
python -m harness node-run --data tests/fixtures/nodes
```

## 架构

标的名称 / 代码由 LangGraph 按原文提取，Java 业务接口调用标的识别、分词和排序工具；本地不运行 ticker 子图（[ADR 0025](./docs/adr/0025-instrument-resolution-delegated-to-backend.md)，边界见 [docs/backend-instrument-boundary.md](docs/backend-instrument-boundary.md)）。

询价入口由请求标志决定：`fast_query=1` 走主图 `quick_inquiry`，调用 GOATS 解析并以 `optionRfq` 提交；普通入口的 `new_inquiry` 只走模型提取、归一化和 `orderList` 提交。文本中出现雪球、参与型或“快速询价”等词不改变入口。

每条消息按既有产品与意图优先级进入一个业务分支，同一动作允许多笔订单。
混合输入沿用原路由，不做多动作拆分、依赖调度或新增识别门禁。
选定本轮动作后，该业务分支识别出的订单统一使用这个动作，不再按分句分配不同动作。
例如“撤单 A；查询 B”：若本轮选中撤单申请且识别到 A、B，则统一申请撤单 A、B，不另行查询 B。
每笔订单仍须通过原有的身份、归属、状态和确认校验，识别到订单不等于已经完成交易。

```text
企微回调 → Java Worker → POST /v1/workflows/run（Dify-兼容）→ FastAPI
  → ingest（会话保护）→ entry_route
      ├─ 快速询价 → quick_inquiry ──────────────────────────┐
      ├─ 存量指令 → existing_command_query ────────────────┤
      └─ 普通指令 → pre_route → intent_route                │
          → swap / option / option_close / fallback        │
          → persist_intent（Java 消息会话与意图写回）────────┤
                                                           ↓
  render → remember_confirmed_params → record_history → persist → outputs

会话过期或入口异常：ingest → render。
业务子图通过 Client Protocol 调用 Java；请求级 callback 记录 Langfuse trace。
```

详见 [ADR 0024](./docs/adr/0024-langgraph-native-rearchitecture.md)（目标架构）+ [ADR 0028](./docs/adr/0028-session-entry-and-multi-instruction-send-orchestration.md)（入口与单动作多订单）+ [ADR 0014](./docs/adr/0014-langfuse-as-harness-backend.md)（LangFuse 后台）。

## 项目结构

```text
app/                        # LangGraph 应用层
├── main.py                 # FastAPI 入口 + lifespan + HTTPMetricsMiddleware + /metrics
├── api/                    # routes.py（/v1/workflows/run）+ nodes.py（/v1/nodes/*）+ idempotency / reconciliation / health
├── graph/                  # state + safe_node / retry + cascade + memory
├── nodes/                  # ingest / entry_route / pre_route / intent_route（+route_rules）/ fast_query / persist / render / fallback
├── subgraphs/
│   ├── swap/               # intent / place_order / select_counterparty / select_ticker / confirm / cancel / query_order / multimodal
│   ├── option/             # intent + extract_inquiry（子图）+ 6 个确定性 / LLM extract 节点
│   └── close/              # intent / place_close（子图）/ cancel_close / confirm_close / confirm_cancel / holding_query / query_status
├── extraction/ execution/  # 字段证据契约（FieldCandidate / FieldRecord / 锁定）与确认协议、批量提交
├── node_execution/         # 单节点调试执行（注册表 / prepare / executor）
├── tools/                  # OptionClient / SwapClient / MessageClient / GOATS + receipts + bot_context + http_pool
├── llm/clients.py          # LLM 统一工厂：全量 DeepSeek-V4-pro（ADR 0020；函数名沿用 get_qwen_*）
├── checkpointer/factory.py # AIOMySQLSaver（连接池）
├── observability/          # tracing / metrics / alerts / llm_metrics / logs / privacy
└── prompts/                # 提示词资产（git 唯一真源；router / swap / option / option_close / judge）

harness/                    # 评测台（python -m harness <doctor|run|node-run>，经 HTTP 调本地服务）+ 节点 fixture / HTTP 录放
scripts/                    # langfuse/（Judge 评估、数据集上传、提示词上传）/ local_eval.py / probe_*.py / canary_* / 一致性 lint
infra/langfuse/             # LangFuse self-hosted Docker Compose（PG + ClickHouse + Redis + MinIO + Web + Worker）
docs/adr/                   # 架构决定 ADR 现行 23 篇（编号 0000-0030，已取代的已删除）+ README 索引
docs/api-contracts/         # Java 后端真实业务 API 契约
tests/                      # 单测 / 子图 / 节点 / 集成（真实 MySQL 用例 RUN_LOCAL_MYSQL_TESTS=1 opt-in）
tests/fixtures/             # categories/（显式验收集）+ unified_golden.jsonl + nodes/（节点级 fixture）
```

## Langfuse Evaluator

评分**代码**与**清单**分开：代码是评分逻辑，清单说明「用哪个文件、产出什么分数、挂给谁」。

```text
harness/evaluators/                 # 评分逻辑，一个文件一个 Evaluator
├── response_contains.py            # 必含文本
├── response_contains_any.py        # 至少含其一
├── response_not_contains.py        # 禁止文本
├── intent_match.py                 # 意图集：逐轮比对 product_type / intent
└── instrument_match.py             # 标的识别比对

scripts/langfuse/definitions/
├── evaluators.json                 # 清单：name / source / score_name / suite / rule
└── score-configs.json              # 人工标注用的 Score Config
```

```json
// evaluators.json 里的一条
{
  "name": "response-contains",
  "source": "harness/evaluators/response_contains.py",
  "score_name": "det_required_text_pass",
  "suite": "business",
  "rule": { "target": "experiment_item_root" }
}
```

上传（`--dry-run` / `--apply` 二选一必填）：

```bash
python scripts/langfuse/upload_evaluators.py --dry-run    # 先看会推什么
python scripts/langfuse/upload_evaluators.py --apply      # 真推（含 Online Evaluation Rule）
python scripts/langfuse/upload_score_configs.py --apply   # Score Config 同理
```

`source` 必须是仓库内存在的文件；`rule.target` 目前只支持 `experiment_item_root`。

## 关键文档

| 文档 | 用途 |
|------|------|
| [docs/work-plan.md](./docs/work-plan.md) | 三条主线的现状与待办 |
| [docs/adr/](./docs/adr/) | 架构决定 ADR 现行 23 篇（编号 0000-0030，已取代的已删除），入口见 [索引](./docs/adr/README.md) |
| [节点执行接口](docs/nodes-run.md) | `/v1/nodes/run`：节点目录、State 契约、本地启动与真实后端切换 |
| [CLAUDE.md](./CLAUDE.md) | AI 工具加载的项目 memory |
| [CONTEXT.md](./CONTEXT.md) | 领域术语 + 概念边界 |
| [HOW_TO_RUN.md](./HOW_TO_RUN.md) | 完整启动流程 |
| [PLAN.md](./PLAN.md) | 期权链路评估与提示词迭代方案 |
| [QUICKSTART_CLAUDE_CODE.md](./QUICKSTART_CLAUDE_CODE.md) | Claude Code 实操指南 |
| [docs/testing/README.md](./docs/testing/README.md) | 测试分层与真后端切换 |
| [docs/on-call-runbook.md](./docs/on-call-runbook.md) | 上线 on-call SOP |
| [docs/api-contracts/java-backend.md](./docs/api-contracts/java-backend.md) | Java 后端真实契约 |
| [infra/langfuse/README.md](./infra/langfuse/README.md) | LangFuse self-hosted 启动 |

## 核心约定

- Python 3.11+，严格类型提示
- ruff lint（行宽 100）
- pytest + `asyncio_mode = "auto"`，提交前跑 `pytest tests/ -v`
- 任何 bug fix / 新功能走 TDD（先写失败测试，再改代码；详见 `.claude/skills/test-driven-development/`）
- 走 feature 分支 + PR，main 受保护，CI 在 PR 上跑
- 严禁硬编码业务数据字典（命名指数 → ETF 代码等）；原文提取 + 后端权威识别

详见 [.claude/rules/](./.claude/rules/) + [docs/adr/](./docs/adr/) + [CLAUDE.md](./CLAUDE.md) 的"绝对禁止"小节。

## License

Internal — 图灵科技
