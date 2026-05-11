# otc-agent · 图灵科技 Project Memory

场外衍生品 AI 指令助手。**FastAPI + LangGraph + MySQL + LangFuse self-hosted**，从 Dify 工作流迁移而来。
企微群客户消息 → 意图解析 → 后端业务/交易系统。

> 当前阶段：**M1 已完成**（issues #9-#13 全 closed）→ M2 待启动（24 个 LangGraph 节点逐一实现：swap 10 + option 6 + option_close 7 + ticker 1）

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
docs/adr/                    # 16 个架构决定（ADR 0000-0015）
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
6. **Dify 原始提示词在重构期内可改写** —— ADR 0001 D5：仅合并 3 个"确认 X"节点 + option 拆 1 intent + 5 extract（不含 close）；其他保持 1:1。重构完成（shadow PASS）后恢复"只读"纪律
7. **标的代码必须 from_goats=True** —— Ticker Agent 的绝对约束（ADR 0008）
8. **节点失败必须 cascade 防御** —— 任一节点写入 `state['error']` 后，下游 conditional 路由必须检查并跳到 fallback render，禁止 cascade 失败。具体：主图 `_route_by_product` 与每子图首节点后的 conditional 都加 `if state.get('error'): return 'fallback'`。fallback 节点输出友好回复（"我没完全理解你的意思，能换种说法重新告诉我吗"）+ trace 记录原 fail 节点名。LLM 解析失败由 `with_structured_output` 自带 1 次重试 + `@safe_node` 兜底捕获 ValidationError 写入 error；不走 HITL（HITL 仅用于 ADR 0006 的业务参数二次确认场景）

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

按 ADR 0001 D9 P0/P1/P2 优先级实施 **24 个 LangGraph 节点**（23 常规 LLM 节点 + 1 个 ticker ReAct 子图）：

> 节点分布（grill-with-docs 2026-05-10 修订）：swap 10 + option 6（1 intent + 5 extract）+ option_close 7 + ticker 1 = 24

```
P0（最先做）：swap.place_order / option.intent_extract / close.place_close / ticker 子图
P1（参数 bug 关键）：swap.cancel + cancel_extract / swap.confirm 合并版 / swap.query_order / close.confirm_*
P2（边角）：swap.place_order_image / place_order_excel / image_recognize / hand_to_share / close.query_status
```

每个节点的实施模板：`@safe_node` + `with_structured_output(<NodePydanticOutput>)` + `load_prompt()` + 5-10 条 golden case。

### M2 PR 颗粒度（grill-with-docs 2026-05-10）

**工作单元 = 节点为单位**，一节点一 PR。两条约束：

1. **同子图首个 PR 含骨架** —— 该子图第一个被实施的节点 PR 必须同时建立 `app/subgraphs/<name>/graph.py` + `models.py` 骨架；后续节点 PR 只挂自己的 `<node>.py` + 在 graph.py 加边
2. **golden 同枝合入** —— 节点 PR 的"绿"标准 = 该节点至少 5 条 golden 全 PASS（PASS 率，不是行覆盖率）。禁止"先合代码、稍后补 case"

理由：M1 已建好 graph 骨架 + safe_node + tools 层 + harness CLI；M2 真正工作量在节点函数 + Pydantic + 提示词 + golden，正好对应一节点一 PR 的天然单元。shadow 双跑（M3）的"节点级 diff"机制天然要求节点级 PR 颗粒度，可一一定位回归来源。

### M2 golden case 来源策略（grill-with-docs 2026-05-10）

**B + C 组合，A 暂搁**：

| 来源 | 配比 | 执行约定 |
|---|---|---|
| **B · 业务方手写种子** | P0 ≥ 50 条（每节点 6-8 条）；M2 全程 ≥ 130 条 | 用 `golden.jsonl` schema 填模板；只标 `product_type` + `intent`，不标参数细节（参数 expected 跑出 actual 后业务方再 review）|
| **C · LLM 对抗式生成**（基于种子 paraphrase + 边界 case）| P0 ≥ 30 条；M2 全程 ≥ 70 条 | 工具放 `harness/case_generator/`，用 thinking 模型；生成的 case **必须** 经业务方 review pass 才合入 |
| ~~A · 历史企微日志抽样~~ | 暂搁 | 留给 M3 shadow 阶段——线上真实输入 + Dify 输出会自然累积成 case 集 |

**退出门按 case 来源分桶**（避免 LLM 生成 case 拉低真门槛）：
- B 桶 PASS 率必须 ≥ 90%
- C 桶 PASS 率 ≥ 80%（容忍 LLM 生成的同质化抖动）
- harness reporter 输出按桶分别统计

详见：

- 领域语言：`@CONTEXT.md`
- 架构决定：`@docs/adr/`（16 个 ADR）
- Java 契约：`@docs/api-contracts/java-backend.md`
- M1 退出门验证：`@tests/test_smoke.py` + `test_api.py` + `test_harness.py` + `test_tools.py`

## Agent skills

### Issue tracker

Issues 存在 GitHub Issues（`github.com/GZTL-AI/aigc-langgraph`），通过 `gh` CLI 操作。详见 `docs/agents/issue-tracker.md`。

### Triage labels

使用默认标签词汇：`needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix`。详见 `docs/agents/triage-labels.md`。

### Domain docs

Single-context 布局：根目录 `CONTEXT.md` + `docs/adr/`。详见 `docs/agents/domain.md`。
