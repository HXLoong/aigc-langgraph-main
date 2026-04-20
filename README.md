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
| 阶段 4 · 灰度切换 | 🧰 已提供工具 | `shadow_compare.py` + `eval_golden.py` |

**测试状态**：**49 tests passed**
- 8 路由规则测试
- 22 + 3 模型与子图路由测试
- 5 端到端集成测试（含真实 Excel 解析、checkpoint 持久化）
- **11 提示词加载器 + 历史消息加载测试（新增）**

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
docker compose exec mysql mysql -uroot -prootpassword < sql/schema.sql
```

### 3. 安装 Python 依赖并启动应用

```bash
pip install -e ".[dev]"
pytest tests/ -v     # 应该看到 30+ 测试通过
uvicorn app.main:app --reload --port 8000
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
app/
├── main.py                      # FastAPI 入口 + lifespan
├── config.py                    # pydantic-settings
├── state.py                     # AgentState + 枚举
├── api/
│   ├── routes.py                # /v1/message, /v1/message/confirm
│   └── schemas.py
├── checkpointer/
│   └── factory.py               # AIOMySQLSaver 生命周期
├── graphs/
│   └── main_graph.py            # 主图组装（接受任何 BaseCheckpointSaver）
├── subgraphs/
│   ├── ticker.py                # 标的识别 ReAct Agent
│   ├── ticker_tools.py          # 7 个标的工具（含 goats 验证）
│   ├── swap.py                  # 互换子图（8 节点，含 VL 图片 + Excel）
│   ├── swap_models.py           # 互换 Pydantic 模型
│   ├── option.py                # 期权子图（含快速询价旁路 + 参数限制）
│   ├── option_models.py         # 期权 Pydantic 模型
│   ├── close.py                 # 平仓子图（5 种意图）
│   └── close_models.py          # 平仓 Pydantic 模型
├── nodes/
│   ├── common.py                # @safe_node 装饰器
│   ├── ingest.py
│   ├── route.py                 # 规则路由
│   ├── persist.py
│   └── render.py
├── tools/
│   └── otc_backend.py           # 统一后端 HTTP 客户端（带 tenacity 重试）
├── llm/
│   └── clients.py               # Qwen standard / thinking / VL
└── observability/
    └── tracing.py

tests/
├── test_route.py                # 8 个路由测试
├── test_models.py               # 22 个 Pydantic 模型测试
├── test_e2e.py                  # 5 个端到端集成测试（含 Excel 解析 + checkpoint）
└── fixtures/
    └── golden.jsonl             # 10 条 golden case（用作回归基线）

scripts/
├── export_dify_prompts.py       # 从 Dify YAML 批量导出 19 个 LLM 提示词
├── eval_golden.py               # 在 golden set 上评估端到端准确率
└── shadow_compare.py            # LangGraph vs Dify 双跑对比（灰度切换期用）

sql/
├── init.sql                     # 建两个独立库
└── schema.sql                   # 4 张业务表（流水/trace/shadow/反馈）
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
pytest -v                              # 全部
pytest tests/test_e2e.py -v            # 端到端（Mock LLM + Mock 后端）
pytest tests/test_route.py --cov=app.nodes.route
```

### 从 Dify 导出提示词
```bash
python scripts/export_dify_prompts.py path/to/dify-yamls/ output/prompts/
```

### 在 golden set 上评估
```bash
python scripts/eval_golden.py tests/fixtures/golden.jsonl \
    --endpoint http://localhost:8000/v1/message
```

### Shadow 双跑（灰度切换期）
```bash
python scripts/shadow_compare.py \
    --langgraph http://langgraph:8000/v1/message \
    --dify http://dify:5000/v1/workflows/run \
    --sample tests/fixtures/golden.jsonl
```

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

1. **提示词调优**：运行 `export_dify_prompts.py` 把 19 个 Dify 提示词导出，逐个迁移到 `app/subgraphs/*.py`，跑 `eval_golden.py` 对比
2. **扩充 golden set 至 200+ 条**：从生产日志脱敏抽取
3. **接入 goats 真实签名**：`ticker_tools.py:search_goats` 目前是签名示意代码
4. **企微确认卡片集成**：把 `interrupt_before` 与确认卡片按钮联动
5. **Shadow 双跑验证差异率** → 5% 金丝雀 → 50% → 100%

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

