# OTC Agent · 场外衍生品 AI 指令助手

基于 **FastAPI + LangGraph + MySQL + LangFuse** 的企微场外衍生品指令解析平台，从 Dify 工作流迁移而来。

> 当前阶段：**M1 / M2 完成 → M3 工程联调 + 评估迭代进行中**（参见 [ADR 0001](./docs/adr/0001-rewrite-app-with-harness-first.md) 和 [ADR 0016](./docs/adr/0016-m3-scope-engineering-loop-not-shadow.md)）

## 当前进度

| 里程碑 | 状态 | 内容 | 退出门 |
|--------|------|------|--------|
| **M1 · 骨架** | ✅ 完成 | LangFuse 部署 + 主图骨架 + 公共节点 + Client Protocol + Harness MVP | smoke + tools + api + harness 测试 PASS |
| **M2 · 子图实现** | ✅ 完成（PR #41 已合入 main） | 20 个 LangGraph 节点：swap 6 + option 6 + option_close 7 + ticker 1；golden 扩到 350+ | 整体 PASS 率 ≥ 92.5%（实际） |
| **M3 · 工程联调闭环** | 🔄 进行中 | 真后端联调（GOATS 直连）+ DeepSeek Judge 评估 + per-turn trace 富集（Langfuse Cloud 写回）+ on-call / 监控 / 告警 / 灰度回滚脚本 | 三链路 PASS ≥ 阈值 + alert 干跑通 + 现场 smoke 通过 |
| **M4 · 金丝雀切流** | ⏸ 待启动 | 测试群 → ~30% 群组 → 全量；企微管理员改 Webhook 实现 | 100% 切流 + 7 天无重大事故 |

参见 [docs/m3-m4-roadmap.md](./docs/m3-m4-roadmap.md) 获取分阶段任务图与分工。

## 快速开始

详见 [HOW_TO_RUN.md](./HOW_TO_RUN.md)。简版：

```bash
# 1. 安装
pip install -e ".[dev]"

# 2. 启动依赖
docker compose up -d mysql
docker compose -f infra/langfuse/docker-compose.yml --env-file infra/langfuse/.env up -d

# 3. 启动应用
uvicorn app.main:app --reload   # POST /v1/workflows/run（兼容 Dify Workflow Run API）

# 4. 跑测试（841 passed + 14 skipped，2 分钟左右）
pytest tests/ -v

# 5. 跑评估
python scripts/langfuse_eval.py --local tests/fixtures/golden.jsonl --concurrency 4
#   ↑ DeepSeek V4 Judge + per-turn 富集 JSON 写到 Langfuse Cloud
python -m harness run                                    # 备用 harness CLI 入口
```

## 架构

```text
企微回调 → Java Worker → POST /v1/workflows/run（Dify-兼容）→ FastAPI → LangGraph
                                                                        ↓
                              ingest → intent_route → swap / option / option_close / ticker 子图
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
├── graphs/main_graph.py    # 主图组装 + 一级路由（route_product_condition）
├── nodes/                  # ingest / intent_route / persist / render / fallback
├── subgraphs/
│   ├── swap/               # intent / place_order / cancel / confirm / query_order / hand_to_share
│   ├── option/             # intent + 5 extract（inquiry / place_or_modify / cancel / confirm / query）
│   ├── close/              # intent / place_close / cancel_close / confirm_close / confirm_cancel / holding_query / query_status
│   └── ticker/             # ReAct Agent（tokenize / completeness / rank / infer_code）+ resolver
├── tools/                  # OptionClient / SwapClient / TickerClient + models + auth
├── llm/clients.py          # Qwen 工厂：standard / thinking / VL / qwen3.5-35b-a3b 非 thinking
├── checkpointer/factory.py # AIOMySQLSaver
├── observability/          # tracing + metrics（Prometheus 兼容 /metrics）
└── prompts/                # Dify 提示词资产（router / swap / option / option_close / ticker）

harness/                    # 评测台 CLI（python -m harness <run|diff|sync-golden|...>）
scripts/                    # langfuse_eval.py / eval_golden.py / probe_*_e2e.py / promote_*.py / canary_*.sh ...
infra/langfuse/             # LangFuse self-hosted Docker Compose（PG + ClickHouse + Redis + MinIO + Web + Worker）
docs/adr/                   # 20 个架构决定（ADR 0000-0019 + AUDIT-2026-05-13）
docs/api-contracts/         # Java 后端真实业务 API 契约
dify/                       # Dify 同步工具（保留历史 YAML 资产）
tests/                      # 841 passed + 14 skipped；行覆盖率 82%
tests/fixtures/             # golden.jsonl（350+ 条）+ golden_ticker_2026-05.jsonl
```

## 关键文档

| 文档 | 用途 |
|------|------|
| [CLAUDE.md](./CLAUDE.md) | AI 工具加载的项目 memory |
| [CONTEXT.md](./CONTEXT.md) | 领域术语 + 概念边界 |
| [HOW_TO_RUN.md](./HOW_TO_RUN.md) | 完整启动流程 |
| [PLAN.md](./PLAN.md) | 期权链路评估与提示词迭代方案 |
| [QUICKSTART_CLAUDE_CODE.md](./QUICKSTART_CLAUDE_CODE.md) | Claude Code 实操指南 |
| [docs/adr/](./docs/adr/) | 20 个架构决定（0000-0019） |
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
