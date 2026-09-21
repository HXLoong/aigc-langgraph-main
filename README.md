# OTC Agent · 场外衍生品 AI 指令助手

基于 **FastAPI + LangGraph + MySQL + LangFuse** 的企微场外衍生品指令解析平台，从 Dify 工作流迁移而来。

> 当前阶段：**M1 / M2 完成 → M3 工程联调 + 评估迭代进行中**（参见 [ADR 0001](./docs/adr/0001-rewrite-app-with-harness-first.md) 和 [ADR 0016](./docs/adr/0016-m3-scope-engineering-loop-not-shadow.md)）

## 当前进度

| 里程碑 | 状态 | 内容 | 退出门 |
|--------|------|------|--------|
| **M1 · 骨架** | ✅ 完成 | LangFuse 部署 + 主图骨架 + 公共节点 + Client Protocol + Harness MVP | smoke + tools + api + harness 测试 PASS |
| **M2 · 子图实现** | ✅ 完成（PR #41 已合入 main） | 20 个 LangGraph 节点：swap 6 + option 6 + option_close 7 + ticker 1；golden 扩到 350+ | mock_api baseline PASS ≥ 92.5%；真 LLM baseline 84.6%（`docs/archive/m2/m2-real-llm-final-report.md`）|
| **M3.1 · Mock 跑通** | ✅ 完成 | LangGraph 全链路 → mock_api 8099 → 业务流端到端 | harness anchor 全集 PASS ≥ 85% |
| **M3.2 · 真后端联调** | ✅ 完成 | D2.1–D2.6（三 client 切真后端 + 字段对齐 + ticker GOATS 联调 + 不可达降级 + InferCode 动态片段 + 健康检查）；Dx.1/Dx.2 swap/close 真 write 接入 | HTTP 5xx = 0 / 4xx = 0 |
| **M3.3 · 真后端 Golden 回归** | 🔄 进行中 | E3.1 B 桶真后端 PASS（小样本完成）+ E3.2 桶分别评估 + E3.3 D 桶（依赖 PM）+ E3.4 错例聚类只修 P0/P1 + E3.5 现场 smoke + E3.6 业务方 sign-off | PASS ≥ M3.1 mock baseline，无链路回归 |
| **M4 · 金丝雀切流** | ⏸ 工具链就绪，待启动 | 测试群 → ~30% 群组 → 全量；shadow 双跑作 M4 第二意见（ADR 0016）| 100% 切流 + 7 天无重大事故 |

**M4 准备就绪的工具链**（可直接复用）：

- `scripts/deploy-customer.sh` · 客户现场一键部署 + smoke 自检（C1.13）
- `scripts/rollback_canary.sh` · F4 灰度应急回切（PR #98）
- `scripts/drill_smoke.sh` · 演练 smoke（PR #100）
- `scripts/shadow_compare.py` · LangGraph vs Dify 字段级 diff（PR #90 / #112，含 `DRY_RUN_BACKEND` 模式）
- `scripts/canary_status.py` / `scripts/metrics_snapshot.py` · 灰度状态 + F4 全指标快照（PR #92 / #94）
- `scripts/promote_langfuse_prompt.py` · LangFuse Prompt 晋升（F4.6 / PR #95）
- `scripts/run_alerts.py` · 阈值告警干跑（5xx / cascade / P95 延迟 / LLM 失败率）
- Grafana 灰度观测面板 JSON 模板（`infra/`，F4.2-F4.5 / PR #97）
- `docs/on-call-runbook.md` · on-call 应急回切剧本（F4.0 / PR #99）

参见 [docs/m3-m4-roadmap.md](./docs/m3-m4-roadmap.md) 获取分阶段任务图与分工，[ADR 0016](./docs/adr/0016-m3-scope-engineering-loop-not-shadow.md) 获取 M3 范围重定义，[ADR 0017](./docs/adr/0017-m4-canary-quantitative-exit-gate.md) 获取 M4 量化退出门。

## 二期持续优化（全量上线后）

来自客户内部汇报方案（2026-05-11）的三件套，**不在 T+3~4 全量上线范围内**，全量上线后启动：

- **Issue #35** · 评估→优化→更新→再评估自动闭环（错例聚类 / A/B 自动评估 / 自动 PR 生成）
- **Issue #36** · 智能体异常干预 + 沉淀记忆机制（agentic memory，跨会话经验记忆）
- **Issue #37** · 回流集自动化打通（D 桶 · 生产真实流量 → golden，需脱敏 + 业务方人工标注）

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
# 统一验收去掉 --case，明确只跑388条 categories；不默认并入 unified。
```

## 架构

标的名称/代码由 LangGraph 按原文提取，Java 业务接口调用标的识别、分词和排序工具。
本地不再运行 ticker 子图；职责和兼容约定见 [后端标的边界](docs/backend-instrument-boundary.md)。

```text
企微回调 → Java Worker → POST /v1/workflows/run（Dify-兼容）→ FastAPI → LangGraph
                                                                        ↓
                              ingest → intent_route → swap / option / option_close 子图
                                                                        ↓
                                          persist (node_trace) → render → outputs
                                                                        ↓
                                LangFuse（trace + dataset + eval + annotation；
                                          self-hosted 或 Cloud 二选一）
                                                                        ↓
              Java Backend（option / swap / ticker；契约见 docs/api-contracts/）
```

详见 [ADR 0001](./docs/adr/0001-rewrite-app-with-harness-first.md)（推倒重写决定）+ [ADR 0014](./docs/adr/0014-langfuse-as-harness-backend.md)（LangFuse 后台）+ [ADR 0016](./docs/adr/0016-m3-scope-engineering-loop-not-shadow.md)（M3 范围重定义）。

## 项目结构

```text
app/                        # LangGraph 应用层
├── main.py                 # FastAPI 入口 + lifespan + HTTPMetricsMiddleware + /metrics
├── api/                    # routes.py（POST /v1/workflows/run）+ health.py（/health, /ready）
├── graph/                  # state + safe_node + cascade fallback
├── nodes/                  # ingest / pre_route / intent_route（+route_rules）/ fast_query / persist / render / fallback
├── subgraphs/
│   ├── swap/               # intent / place_order / select_counterparty / select_ticker / confirm / cancel / query_order / multimodal
│   ├── option/             # intent + 7 extract（inquiry / place / confirm_place / cancel_place / confirm_cancel / cancel / query）+ sanitize
│   ├── close/              # intent / place_close / cancel_close / confirm_close / confirm_cancel / holding_query / query_status
│   └── ticker/             # resolver 确定性管线（候选格式化 → 3 路 LLM → merge_and_validate → GOATS+rank）
├── tools/                  # OptionClient / SwapClient / TickerClient + models + auth
├── llm/clients.py          # LLM 统一工厂：全量 DeepSeek-V4-pro（ADR 0020；函数名沿用 get_qwen_*）
├── checkpointer/factory.py # AIOMySQLSaver
├── observability/          # tracing + metrics（Prometheus 兼容 /metrics）
└── prompts/                # 提示词资产（git 唯一真源；router / swap / option / option_close / ticker）

harness/                    # 评测台 CLI（python -m harness <doctor|run>，经 HTTP 调本地 /v1/workflows/run）
scripts/                    # langfuse_eval.py / probe_*.py / promote_*.py / canary_*.sh ...
infra/langfuse/             # LangFuse self-hosted Docker Compose（PG + ClickHouse + Redis + MinIO + Web + Worker）
docs/adr/                   # 架构决定 ADR 0000-0024（共 25 篇）+ README 索引
docs/api-contracts/         # Java 后端真实业务 API 契约
tests/                      # 1864 passed + 15 skipped
tests/fixtures/             # golden.jsonl（350+ 条）+ golden_ticker_2026-05.jsonl
```

## 关键文档

| 文档 | 用途 |
|------|------|
| [节点执行接口](docs/nodes-run.md) | `/v1/nodes/run`：65 个节点目录、State 契约、本地启动与真实后端切换 |
| [CLAUDE.md](./CLAUDE.md) | AI 工具加载的项目 memory |
| [CONTEXT.md](./CONTEXT.md) | 领域术语 + 概念边界 |
| [HOW_TO_RUN.md](./HOW_TO_RUN.md) | 完整启动流程 |
| [PLAN.md](./PLAN.md) | 期权链路评估与提示词迭代方案 |
| [QUICKSTART_CLAUDE_CODE.md](./QUICKSTART_CLAUDE_CODE.md) | Claude Code 实操指南 |
| [docs/adr/](./docs/adr/) | 架构决定 ADR 0000-0021（共 22 篇），入口见 [索引](./docs/adr/README.md) |
| [docs/m3-m4-roadmap.md](./docs/m3-m4-roadmap.md) | M3/M4 端到端任务图（2026-05-11） |
| [docs/on-call-runbook.md](./docs/on-call-runbook.md) | 上线 on-call SOP |
| [docs/api-contracts/java-backend.md](./docs/api-contracts/java-backend.md) | Java 后端真实契约 |
| [infra/langfuse/README.md](./infra/langfuse/README.md) | LangFuse self-hosted 启动 |

## 核心约定

- Python 3.11+，严格类型提示
- ruff lint（行宽 100）
- pytest + `asyncio_mode = "auto"`，提交前跑 `pytest tests/ -v`
- 任何 bug fix / 新功能走 TDD（先写失败测试，再改代码；详见 `.claude/skills/test-driven-development/`）
- 走 feature 分支 + PR，main 受保护
- 严禁硬编码业务数据字典（命名指数 → ETF 代码等）；走 LLM 推断 + 后端权威源校验

详见 [.claude/rules/](./.claude/rules/) + [docs/adr/](./docs/adr/) + [CLAUDE.md](./CLAUDE.md) 的"绝对禁止"小节。

## License

Internal — 图灵科技
