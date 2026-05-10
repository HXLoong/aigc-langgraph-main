# OTC Agent · 场外衍生品 AI 指令助手

基于 **FastAPI + LangGraph + MySQL + LangFuse self-hosted** 的企微场外衍生品指令解析平台，从 Dify 工作流迁移而来。

> 当前阶段：**M1 已完成 → M2 待启动**（[ADR 0001 D8](./docs/adr/0001-rewrite-app-with-harness-first.md) 路线图）

## 当前进度

| 里程碑 | 状态 | 内容 | 退出门 |
|--------|------|------|--------|
| **M1 · 骨架** | ✅ 完成 | LangFuse 部署 + 主图骨架 + 公共节点 + 3 个 Client Protocol + Harness MVP | smoke + tools + api + harness 测试 PASS |
| **M2 · 子图实现** | ⏸ 待做 | 17 个 LLM 节点逐一实现 + golden 扩到 200+ | golden 200+ 全 PASS |
| **M3 · Shadow 双跑** | ⏸ 待做 | LangGraph vs Dify diff 率达标 | 主要意图 < 5%，下单/平仓 < 1% |
| **M4 · 金丝雀切换** | ⏸ 待做 | 5% → 25% → 50% → 100% | 100% + 7 天无重大事故 |

## 快速开始

详见 [HOW_TO_RUN.md](./HOW_TO_RUN.md)。简版：

```bash
# 1. 安装
pip install -e ".[dev]"

# 2. 启动依赖
docker compose up -d mysql
docker compose -f infra/langfuse/docker-compose.yml --env-file infra/langfuse/.env up -d

# 3. 启动应用
uvicorn app.main:app --reload

# 4. 跑测试
pytest tests/ -v

# 5. 跑 harness（M2 后才有 golden 全集，目前是 stub）
python -m harness run
```

## 架构

```text
企微回调 → Java Worker → POST /v1/workflows/run（Dify-兼容）→ FastAPI → LangGraph
                                                                        ↓
                                              ingest → route → swap/option/close 子图
                                                                        ↓
                                          persist (node_trace) → render → outputs
                                                                        ↓
                                LangFuse self-hosted（trace + dataset + eval + annotation）
                                                                        ↓
              Java Backend（option/swap/ticker endpoints，详见 docs/api-contracts/）
```

详见 [ADR 0001](./docs/adr/0001-rewrite-app-with-harness-first.md)（推倒重写决定）+ [ADR 0014](./docs/adr/0014-langfuse-as-harness-backend.md)（LangFuse 后台）。

## 项目结构

```text
app/                # LangGraph 应用层
├── main.py           # FastAPI 入口
├── api/routes.py     # POST /v1/workflows/run
├── graph/            # state + safe_node + main 主图
├── nodes/            # ingest / persist / render
├── tools/            # 3 个 Protocol：OptionClient / SwapClient / TickerClient
├── llm/clients.py    # Qwen standard / thinking / VL
├── checkpointer/     # AIOMySQLSaver
└── prompts/          # 23 个 Dify 提示词资产

harness/            # 评测台（独立于 app/）
infra/langfuse/     # LangFuse self-hosted Docker Compose
docs/adr/           # 15 个架构决定
docs/api-contracts/ # Java 后端契约清单
dify/               # Dify 同步工具（保留资产）
mock_api/           # 业务后端 mock（M3 联调前用）
tests/              # 单元 + smoke + GOATS 连通性
```

## 关键文档

| 文档 | 用途 |
|------|------|
| [CLAUDE.md](./CLAUDE.md) | AI 工具加载的项目 memory |
| [CONTEXT.md](./CONTEXT.md) | 领域术语 + 概念边界 |
| [HOW_TO_RUN.md](./HOW_TO_RUN.md) | 完整启动流程 |
| [docs/adr/](./docs/adr/) | 15 个架构决定（0000-0014） |
| [docs/api-contracts/java-backend.md](./docs/api-contracts/java-backend.md) | Java 后端真实契约 |
| [infra/langfuse/README.md](./infra/langfuse/README.md) | LangFuse self-hosted 启动 |

## 核心约定

- Python 3.11+，严格类型提示
- ruff lint（行宽 100）
- pytest + asyncio_mode = auto
- 提交前跑 `pytest tests/ -v`
- 走 feature 分支 + PR，main 受保护

详见 [.claude/rules/](./.claude/rules/) + [docs/adr/](./docs/adr/)。

## License

Internal — 图灵科技
