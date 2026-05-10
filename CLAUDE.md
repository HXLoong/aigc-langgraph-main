# otc-agent · 图灵科技 Project Memory

场外衍生品 AI 指令助手。**FastAPI + LangGraph + MySQL + LangFuse self-hosted**，从 Dify 工作流迁移而来。
企微群客户消息 → 意图解析 → 后端业务/交易系统。

> 当前阶段：**M1 已完成**（issues #9-#13 全 closed）→ M2 待启动（17 个 LLM 节点逐一实现）

## 关键命令

```bash
# 安装
pip install -e ".[dev]"

# 启动业务依赖
docker compose up -d mysql                                                          # MySQL（业务库 + checkpoint）
docker compose -f infra/langfuse/docker-compose.yml --env-file infra/langfuse/.env up -d  # LangFuse self-hosted

# 启动应用
uvicorn app.main:app --reload                # FastAPI（POST /v1/workflows/run，兼容 Dify）

# 测试
pytest tests/ -v                             # 全套测试（smoke / tools / api / harness）
pytest tests/test_smoke.py -v                # 仅 M1 smoke

# Harness（评测台）
python -m harness run                        # 跑 golden 全集
python -m harness run --case g042            # 单 case
python -m harness diff <run-a> <run-b>       # 比对两次 run
python -m harness sync-golden                # tests/fixtures/*.jsonl ↔ LangFuse dataset

# Dify 同步（保留资产）
export DIFY_EMAIL="..." DIFY_PASSWORD="..."
python dify/sync.py                          # 拉最新 YAML → dify/yaml/
```

## 项目结构（M1 完成后）

```
app/
├── main.py                  # FastAPI 入口（POST /v1/workflows/run）
├── config.py                # 配置加载
├── api/routes.py            # 兼容 Dify Workflow Run API
├── graph/
│   ├── state.py             # AgentState（按业务对象聚合）
│   ├── safe_node.py         # @safe_node 装饰器
│   └── main.py              # 主图组装 + 一级路由
├── nodes/                   # 顶层节点：ingest / persist / render
├── tools/
│   ├── models.py            # Java DTO 对应 Pydantic
│   ├── option_client.py     # OptionClient Protocol（POST /financial-orders/operate）
│   ├── swap_client.py       # SwapClient Protocol（POST /swap-order/operate）
│   └── ticker_client.py     # TickerClient Protocol（GET /securities-instrument/select）
├── llm/clients.py           # Qwen standard / thinking / VL（保留）
├── checkpointer/factory.py  # AIOMySQLSaver（保留）
├── observability/tracing.py # OpenTelemetry（与 LangFuse 互补）
└── prompts/                 # 23 个 Dify 提示词资产（重构期内可改写，见原则 6）

# 子图（M2 阶段重建）
app/subgraphs/               # swap / option / close / ticker（M2 P0/P1/P2 优先级）

harness/                     # 评测台（与 app/ 解耦，仅 import build_main_graph）
├── golden.py                # golden.jsonl 加载
├── runner.py                # 跑 case + dump trace 到 LangFuse
├── differ.py                # 字段级 diff（按业务对象路径）
├── reporter.py              # JSON + markdown 报告
├── langfuse_client.py       # LangFuse SDK 封装
└── cli.py                   # python -m harness <run|diff|sync-golden|...>

infra/langfuse/              # LangFuse self-hosted Docker Compose（PG + ClickHouse + Redis + MinIO + Web + Worker）
docs/adr/                    # 15 个架构决定（ADR 0000-0014）
docs/api-contracts/          # Java 后端真实业务 API 契约
mock_api/server.py           # 业务后端 mock（M3 联调前用）
tests/                       # test_smoke + test_api + test_harness + test_tools + tests/api（GOATS 连通性）
```

## 核心原则（永远有效）

1. **提示词不硬编码在代码里** —— 从 `app/prompts/**/*.md` 用 `load_prompt()` 加载
2. **LLM 输出用 `with_structured_output(PydanticModel)`** —— 绝不手工解析 JSON
3. **每个节点用 `@safe_node` 装饰** —— 异常降级到 `state['error']`，不让图崩
4. **State 字段只通过 TypedDict 约定** —— 新增字段必须先在 `app/graph/state.py` 中声明
5. **测试优先** —— 改代码前先改/加测试。商业逻辑必须有单元测试，链路必须有 E2E
6. **Dify 原始提示词在重构期内可改写** —— ADR 0001 D5：仅合并 3 个"确认 X"节点 + option 拆 1+6 节点；其他保持 1:1。重构完成（shadow PASS）后恢复"只读"纪律
7. **标的代码必须 from_goats=True** —— Ticker Agent 的绝对约束（ADR 0008）

## 绝对禁止

- **硬编码 API Key / Secret** —— 必须通过 `app.config.get_settings()`，读环境变量
- **在节点函数内抛未捕获异常** —— 用 `@safe_node` 包住
- **MySQL 版本不符合 8.0.19 ≤ v < 9.6.0 的假设** —— AIOMySQLSaver 兼容性硬约束
- **直接 `httpx.AsyncClient` 调后端** —— 走 `OptionClient` / `SwapClient` / `TickerClient` 三个 Protocol（ADR 0001 D2 修订版）
- **在 main 分支直接改业务子图** —— 走 feature branch + PR

## 代码风格

- Python 3.11+，严格类型提示
- ruff lint，行宽 100
- 异步优先：能 async 就 async
- 中文注释 OK，docstring 简洁清晰
- 不加 emoji（生产代码）

## 下一步：M2

按 ADR 0001 D9 P0/P1/P2 优先级实施 17 个 LLM 节点：

```
P0（最先做）：swap.place_order / option.intent_extract / close.place_close / ticker 子图
P1（参数 bug 关键）：swap.cancel + cancel_extract / swap.confirm 合并版 / swap.query_order / close.confirm_*
P2（边角）：swap.place_order_image / place_order_excel / image_recognize / hand_to_share / close.query_status
```

每个节点的实施模板：`@safe_node` + `with_structured_output(<NodePydanticOutput>)` + `load_prompt()` + 5-10 条 golden case。

详见：

- 领域语言：`@CONTEXT.md`
- 架构决定：`@docs/adr/`（15 个 ADR）
- Java 契约：`@docs/api-contracts/java-backend.md`
- M1 退出门验证：`@tests/test_smoke.py` + `test_api.py` + `test_harness.py` + `test_tools.py`

## Agent skills

### Issue tracker

Issues 存在 GitHub Issues（`github.com/GZTL-AI/aigc-langgraph`），通过 `gh` CLI 操作。详见 `docs/agents/issue-tracker.md`。

### Triage labels

使用默认标签词汇：`needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix`。详见 `docs/agents/triage-labels.md`。

### Domain docs

Single-context 布局：根目录 `CONTEXT.md` + `docs/adr/`。详见 `docs/agents/domain.md`。
