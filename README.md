# OTC Agent - 场外衍生品 AI 指令助手

基于 **FastAPI + LangGraph + MySQL** 的企微场外衍生品指令解析平台，从 Dify 工作流迁移而来。

## 当前进度

| 阶段 | 状态 | 内容 |
|---|---|---|
| 阶段 1 · 骨架 | ✅ 完成 | FastAPI + AIOMySQLSaver + 主图 + 路由 + API |
| 阶段 2 · 标的识别 | ✅ 完成 | ReAct Agent + 7 个标的工具 + 真实 Dify 提示词 |
| 阶段 3 · 业务子图 | ✅ 完成 | 互换 / 期权 / 平仓 + 图片 OCR + Excel 解析 |
| 阶段 3.5 · 提示词整合 | ✅ 完成 | **23 个真实 Dify 提示词已整合，可开箱即用** |
| 阶段 3.6 · 历史加载 | ✅ 完成 | 基于 checkpoint 的多轮对话历史自动重建 |
| 阶段 3.7 · 闭环验证 | ✅ 完成（2026-05） | **零依赖闭环 demo 30/30 PASS**、mock_api 替代 VPN 标的查询 |
| 阶段 4 · 灰度切换 | 🧰 已提供工具 | `shadow_compare.py`（重构）+ `eval_golden.py` + 30 条 golden |

**测试状态**：**117/117 tests passed**
- 路由规则、模型与子图路由测试
- 端到端集成测试（含真实 Excel 解析、checkpoint 持久化）
- 提示词加载器 + 历史消息加载测试
- **闭环 demo 30/30 PASS**：`python scripts/demo_closed_loop.py`（in-process，零外部依赖）
- **GOATS 20 个接口连通性测试**（`tests/api/`，需真实后端）

> 详细的近期变更与下一步计划见 [`docs/CHANGELOG_2026-05.md`](docs/CHANGELOG_2026-05.md)。

## 提示词整合

**23 个真实 Dify 提示词已从 5 个 YAML 中提取并整合到 `app/prompts/`**：

```
app/prompts/
├── swap/
│   ├── intent.md            (20K 字符，互换意图识别)
│   ├── place_order.md       (133K 字符，下单参数提取)
│   ├── confirm_order.md     (确认下单)
│   ├── cancel_order.md      (撤单)
│   ├── confirm_cancel.md    (确认撤单)
│   ├── confirm_modify.md    (确认改单)
│   ├── query_order.md       (查询订单)
│   ├── image_extract.md     (图片参数提取，109K)
│   ├── image_ocr.md         (图片 OCR 模板匹配)
│   └── excel_extract.md     (Excel 参数提取)
├── option_close/
│   ├── intent.md            (14K)
│   ├── place_close.md       (45K)
│   ├── holding_query.md     (持仓查询)
│   ├── confirm_close.md     (确认平仓)
│   ├── cancel_close.md      (撤单)
│   ├── confirm_cancel.md    (确认撤单)
│   └── query_status.md      (订单查询)
└── ticker/
    ├── tokenize.md          (17K，分词规则)
    ├── completeness.md      (完整性判断)
    ├── rank.md              (相关性排序)
    └── infer_code.md        (大模型推断)
```

通过 `app.prompts.load_prompt(category, name)` 统一加载，LRU 缓存加速重复访问。

## 历史消息加载

多轮对话支持已实现：`/v1/message` 处理器在调用图之前会从 checkpoint 自动读取最近 10 轮对话，注入到 `state["history_messages"]`，再由 `classify_intent` / `extract_order_id` 等 LLM 节点使用。

核心函数在 `app/nodes/history.py`：
- `load_history_from_checkpoint(graph, thread_id, max_turns)` - 从 checkpoint 反向回溯
- `format_history_for_prompt(messages, max_chars)` - 拼装为 LLM 友好的 `history_query_str`

## 架构

```
企微回调 → FastAPI → [预加载历史] → LangGraph StateGraph（Checkpoint: AIOMySQLSaver）
                                          │
                                          ├─ ingest (并行拉取 bot/orders/cp)
                                          ├─ route_product (规则路由)
                                          │
                                          ├─ option_subgraph
                                          │    ├─ detect_quick_query (雪球/参与型旁路)
                                          │    ├─ ticker_identify (ReAct Agent + Dify prompt)
                                          │    ├─ extract_option
                                          │    ├─ check_param_limit (纯 Python)
                                          │    └─ call_option_api
                                          │
                                          ├─ swap_subgraph
                                          │    ├─ dispatch_modality
                                          │    ├─ parse_image (VL OCR)
                                          │    ├─ parse_excel (openpyxl)
                                          │    ├─ ticker_identify
                                          │    ├─ classify_intent (Dify 真实 20K prompt)
                                          │    ├─ extract_place_order (Dify 真实 133K prompt)
                                          │    ├─ extract_order_id (按意图动态加载 5 个 prompt)
                                          │    └─ call_swap_api
                                          │
                                          ├─ close_subgraph
                                          │    ├─ classify_close_intent (Dify 真实 14K prompt)
                                          │    ├─ extract_holding_query / place_close / order_no_list
                                          │    └─ call_close_api
                                          │
                                          ├─ persist_intent (后端存档)
                                          └─ render_reply
                                          ↓
                                      后端业务 / 交易系统
```

## 快速启动

### 1. 克隆并配置环境变量

```bash
git clone <repo>
cd otc-agent
cp .env.example .env
# 编辑 .env 填入实际的 API Key 和数据库地址
```

### 2. 用 Docker Compose 启动依赖

```bash
docker compose up -d mysql
# 等待 MySQL 健康
# docker compose exec mysql mysql -uroot -prootpassword < sql/schema.sql
docker compose exec -T mysql mysql -uroot -prootpassword < sql/schema.sql

```

### 3. 安装 Python 依赖并启动应用

```bash
pip install -e ".[dev]"
pytest tests/ -v     # 应该看到 30+ 测试通过

conda activate otc-agent
python -m uvicorn app.main:app --reload --port 8000

python .\scripts\smoke_test.py

```

首次启动会看到日志：
```
INFO: 正在初始化 MySQL Checkpointer...
INFO: MySQL Checkpointer 初始化完成
INFO: 标的识别 Agent 已构建（7 个工具）
INFO: 主图编译完成
INFO: 应用就绪
```

### 4. 发送测试消息

```bash
# 互换下单
curl -X POST http://localhost:8000/v1/message \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "test-1",
    "message_id": "m1",
    "room_id": "r1",
    "user_id": "u1",
    "guid": "g1",
    "raw_content": "做一笔招商银行 600036.SH 的 TRS，买 1000 手，市价"
  }'

# 期权平仓
curl -X POST http://localhost:8000/v1/message \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "test-2",
    "message_id": "m2",
    "room_id": "r1",
    "user_id": "u1",
    "guid": "g2",
    "raw_content": "请平 CO-20260304-4FE9C941 全部"
  }'
```

## 目录结构

```
.
├── app/
│   ├── main.py                  # FastAPI 入口，负责 lifespan（checkpointer 初始化）
│   ├── config.py
│   ├── state.py                 # AgentState + 全部枚举，新字段必须在这里声明
│   ├── api/
│   │   ├── routes.py            # /v1/message、/v1/message/confirm、/v1/conversations/{id}/state
│   │   └── schemas.py
│   ├── checkpointer/
│   │   └── factory.py           # AIOMySQLSaver 的创建与关闭，应用级单例
│   ├── graphs/
│   │   └── main_graph.py        # 主图，把各子图拼在一起
│   ├── subgraphs/               # 三条业务线各一对文件（逻辑 + 模型）
│   │   ├── swap.py / swap_models.py
│   │   ├── option.py / option_models.py
│   │   ├── close.py / close_models.py
│   │   ├── ticker.py            # 标的识别，用 create_react_agent 实现
│   │   └── ticker_tools.py      # 7 个工具，最终都要过 goats 验证
│   ├── nodes/
│   │   ├── common.py            # @safe_node 装饰器
│   │   ├── ingest.py
│   │   ├── route.py
│   │   ├── history.py
│   │   ├── persist.py
│   │   └── render.py
│   ├── prompts/                 # 23 个从 Dify 导出的提示词，只读，不要手改
│   │   ├── swap/
│   │   ├── option_close/
│   │   └── ticker/
│   ├── tools/
│   │   └── otc_backend.py       # 后端 HTTP 客户端，所有子图统一走这里
│   ├── llm/
│   │   └── clients.py
│   └── observability/
│       └── tracing.py
│
├── tests/
│   ├── test_route.py
│   ├── test_models.py
│   ├── test_prompts_and_history.py
│   ├── test_e2e.py
│   ├── test_closed_loop.py            # CI 入口：调用 scripts/demo_closed_loop.py
│   ├── test_ticker.py / test_option.py
│   ├── run_integration_test.py        # 全链路集成（需 mock_api + LangGraph）
│   ├── api/                           # GOATS 20 个接口连通性测试（独立运行）
│   │   ├── _utils.py / run_all.py / README.md
│   │   └── test_01_*.py ... test_20_*.py
│   └── fixtures/
│       └── golden.jsonl               # 30 条端到端用例
│
├── scripts/
│   ├── export_dify_prompts.py   # 从 Dify YAML 重新导出提示词时用
│   ├── eval_golden.py
│   ├── demo_closed_loop.py      # 零外部依赖闭环 demo（30/30 PASS）
│   └── shadow_compare.py        # 重构后的 LangGraph vs Dify 双跑工具
│
├── mock_api/
│   ├── server.py                # 32 个端点：GOATS 20 + 后端 6 + 标的查询 1 + 其他
│   └── test_all_endpoints.py
│
├── dify/
│   ├── sync.py                  # 从内网 Dify 平台拉最新工作流 YAML
│   ├── README.md
│   └── yaml/                    # 5 个 Dify 工作流的导出文件（只读资产）
│
├── sql/
│   ├── init.sql
│   └── schema.sql
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DEVELOPMENT.md
│   ├── DIFY_MIGRATION.md
│   ├── SHADOW_COMPARE_GUIDE.md
│   ├── TEST_AND_CONNECTIVITY_STATUS.md
│   ├── CHANGELOG_2026-05.md     # 最近变更与下一步计划
│   └── TROUBLESHOOTING.md
│
├── docker-compose.yml
└── pyproject.toml
```

## 关键技术约束

### MySQL 版本
- **必须**：`8.0.19 ≤ version < 9.6.0`
- 原因：`langgraph-checkpoint-mysql` 依赖 8.0.19+ 的特性；9.6.0 废弃了生成列中的 MD5 函数

### 数据库分库
- `otc_agent_checkpoint`：LangGraph checkpoint（表由 `AIOMySQLSaver.setup()` 自动建）
- `otc_agent_business`：业务审计（`sql/schema.sql`）
- 分库目的：两者读写模式差异巨大，便于单独扩容

### URI 格式区分
- Checkpoint 用：`mysql://user:pass@host:3306/db`（AIOMySQLSaver 走内部 aiomysql）
- 业务库用：`mysql+aiomysql://user:pass@host:3306/db`（SQLAlchemy）

### LangGraph 版本兼容
- 代码支持 LangGraph 0.6+ 和 1.0+
- `create_react_agent` 在 1.0+ 迁移到 `langchain.agents.create_agent`，`ticker.py` 已做兼容导入

## 开发工作流

### 运行测试
```bash
pytest -v                              # 全部（目标 117+ 通过）
pytest tests/test_e2e.py -v            # 端到端（Mock LLM + Mock 后端）
pytest tests/test_route.py --cov=app.nodes.route

# 零外部依赖闭环 demo（in-process，无需 Docker / LLM key / VPN）
python scripts/demo_closed_loop.py     # 期望：30/30 PASS

# GOATS 后端 20 个接口连通性测试（需真实后端）
python tests/api/run_all.py
```

### 从 Dify 同步提示词
```bash
# 1) 拉最新 Dify YAML 到本地（需内网/VPN，登录凭据通过 env 注入）
export DIFY_EMAIL="..." DIFY_PASSWORD="..."
python dify/sync.py                    # 输出到 dify/yaml/

# 2) 把 YAML 中的 LLM 节点提示词导出为 .md
python scripts/export_dify_prompts.py dify/yaml/ /tmp/new-prompts/

# 3) diff 后选择性合入到 app/prompts/，并跑 golden 回归
diff -r app/prompts/ /tmp/new-prompts/ | head -50
python scripts/eval_golden.py tests/fixtures/golden.jsonl
```

### 在 golden set 上评估
```bash
python scripts/eval_golden.py tests/fixtures/golden.jsonl \
    --endpoint http://localhost:8000/v1/message
```

### Shadow 双跑（灰度切换期）
```bash
# 本地 dev：明细写 JSON 文件
python scripts/shadow_compare.py \
    --langgraph http://localhost:8000/v1/message \
    --dify https://dify.example.com/v1/workflows/run \
    --dify-api-key app-xxxxxxxxxxxx \
    --sample tests/fixtures/golden.jsonl \
    --output /tmp/shadow_diff.json

# 生产灰度：写到 MySQL otc_agent_business.shadow_compare 表
python scripts/shadow_compare.py \
    --langgraph https://lg-canary.internal/v1/message \
    --dify https://dify-prod.internal/v1/workflows/run \
    --dify-api-key $DIFY_API_KEY \
    --sample sample_real_traffic.jsonl \
    --mysql-host mysql-prod.internal \
    --mysql-db otc_agent_business \
    --mysql-user otc_agent --mysql-password "$MYSQL_PASSWORD"
```

详见 `docs/SHADOW_COMPARE_GUIDE.md`。

### 调试：查看某个会话的当前状态
```bash
curl http://localhost:8000/v1/conversations/test-conv-1/state
```

## 端点清单

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/health` | 健康检查 |
| POST | `/v1/message` | 企微消息回调 |
| POST | `/v1/message/confirm` | 确认卡片按钮回调（恢复被 interrupt 的图） |
| GET  | `/v1/conversations/{id}/state` | 调试：查看 State 快照 |

## 下一步工作（阶段 4 灰度切换）

> 本节是摘要。完整时间线、commit 列表、改动指标见 [`docs/CHANGELOG_2026-05.md`](docs/CHANGELOG_2026-05.md)。

**P0 · 灰度切换准备（本周内）**

1. **Shadow 双跑接入生产采样流量** —— 跑满 24 小时，差异率目标 < 3%；写入 `otc_agent_business.shadow_compare`，详见 `docs/SHADOW_COMPARE_GUIDE.md`
2. **修 Option 标准询价 LLM 不稳定** —— `extract_option` 偶将 `new_inquiry` 识别为 `unknown`，扩 golden 后按 `_v2.md` A/B 调
3. **接入 goats 真实签名** —— `ticker_tools.py:search_goats` 目前是签名示意代码，联调内网鉴权后保留 `MOCK_GOATS=true` 回退

**P1 · 提示词与 Dify 同步流水线（下周）**

4. **从最新 Dify YAML 同步提示词** —— `dify/sync.py` → `export_dify_prompts.py` → diff → 选择性合入 → `eval_golden.py` 回归
5. **扩充 golden set 至 200+ 条** —— 从生产日志脱敏抽取，覆盖图片/Excel、多标的、参与型/雪球询价、引用上下文回复

**P2 · 工程基建（持续）**

6. **企微确认卡片集成** —— 把 `interrupt_before` 与确认卡片按钮联动
7. **CI 接入** —— GitHub Actions 跑 `pytest` + `demo_closed_loop.py` + `ruff check`，PR 卡口差异率 < 5%
8. **观测** —— 生产开 LangSmith 或自建 OpenTelemetry，`trace` 字段写到 `node_trace` 表

## 常见问题

**Q: AIOMySQLSaver.setup() 报错 "Access denied"？**
A: 检查 `otc_agent` 用户是否对 `otc_agent_checkpoint` 库有 CREATE/ALTER 权限。

**Q: 本地 MySQL 是 9.6+，怎么办？**
A: 降级到 8.0.x 或 9.5.x；测试环境可用 InMemorySaver（见 `tests/test_e2e.py`）。

**Q: 如何切换回 Dify？**
A: 设 `USE_LANGGRAPH=false` + `LANGGRAPH_TRAFFIC_RATIO=0`，FastAPI 层实现 fallback。

**Q: 为什么图片/Excel 解析后的结果要拼到 raw_content？**
A: 让下游所有节点（意图识别、参数提取）共用同一个 `raw_content` 字段，无需判断模态。这是 Dify 原设计的合理之处，我们保留了。

## 许可

内部项目。

