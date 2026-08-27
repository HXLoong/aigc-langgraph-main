# 架构

## 系统概览

```
企微群消息
    ↓ (Webhook)
FastAPI 接入层 (app/main.py + app/api/routes.py)
    ↓ 预加载历史（load_history_from_checkpoint）
LangGraph 主图 (app/graphs/main_graph.py)
    ↓
  ├─ ingest        加载 bot_names / 会话订单 / 交易对手
  ├─ route_product 规则路由（正则 + 关键词）
  │     │
  │     ├─→ option_subgraph      期权询价/下单/改单/撤单/确认
  │     ├─→ swap_subgraph        互换（6 种意图 + 多模态）
  │     ├─→ close_subgraph       期权平仓（5 种意图）
  │     └─→ unknown → render
  │
  ├─ persist_intent 调用后端 set-intent 审计
  └─ render_reply   生成回复文本
    ↓
后端业务 API（/admin-api/*）
    ↓
交易系统
```

## 分层

### 1. 接入层（app/api/、app/main.py）
- FastAPI lifespan：启动时初始化 AIOMySQLSaver + build 主图
- `/v1/message`：企微消息回调，thread_id = conversation_id
- `/v1/message/confirm`：确认卡片按钮回调，恢复 interrupted 的图

### 2. 图编排层（app/graphs/）
- `main_graph.py`：组装顶层节点 + 嵌入 3 个业务子图
- `app/nodes/intent_route.py`（四层路由，ADR 0015）+ `app/graph/main.py` 的 `_route_after_intent()`：决定走哪个子图

### 3. 子图层（app/subgraphs/）
- 每个产品一个子图 + 一个 models 文件（Pydantic schema）
- `ticker.py` + `ticker_tools.py`：跨子图共享的标的识别 ReAct Agent

### 4. 节点层（app/nodes/）
- `common.py`：@safe_node 装饰器
- `ingest.py`：会话上下文加载（并行 HTTP）
- `route.py`：产品类型规则路由
- `persist.py`：后端审计
- `render.py`：回复生成
- `history.py`：从 checkpoint 重建对话历史

### 5. 工具层（app/tools/、app/llm/）
- `otc_backend.py`：统一 HTTP 客户端（tenacity 重试）
- `llm/clients.py`：Qwen standard/thinking/VL 三个型号

### 6. 资源层
- `app/prompts/`：23 个从 Dify 迁移来的真实提示词（.md）
- `app/state.py`：AgentState TypedDict + 所有枚举
- `app/config.py`：pydantic-settings

## State 流转

```
客户消息 → wechat_input (不可变)
        → history_messages (从 checkpoint 预加载)
        → bot_name_list / counterparty_list / conversation_orders (ingest 加载)
        → product_type (route_product 决定)
        → resolved_tickers (ticker agent 填充)
        → intent (classify_*_intent 填充)
        → order_list / order_ids (extract_* 填充)
        → api_code / api_result (call_*_api 填充)
        → reply_text (render_reply 生成)
        → trace[] (每个节点追加一条)
```

## 存储

### MySQL 双库

```
otc_agent_checkpoint    (由 AIOMySQLSaver 管理)
├── checkpoints         LangGraph 主表
├── checkpoint_blobs    二进制数据
├── checkpoint_writes   增量写入
└── checkpoint_migrations

otc_agent_business      (业务自管，sql/schema.sql)
├── message_log         消息处理流水
├── node_trace          节点追踪
├── shadow_compare      双跑对比（灰度期用）
└── user_feedback       用户反馈
```

### 为什么分库
- checkpoint 写入频率极高（每个 superstep 一次），业务库是审计用
- 未来可独立扩容 checkpoint 库

## 可观测性

- LangFuse：通过 `ENABLE_LANGFUSE=true` 启用（ADR 0014），每个节点一个 span
- OpenTelemetry：`app/observability/tracing.py`，FastAPI 埋点
- 应用日志：structlog JSON 格式，生产环境写 ES
- 业务审计：`node_trace` 表

## 设计决策

### 为什么用 LangGraph 不用 Dify
- State 机制更强（TypedDict + reducer vs variable aggregator）
- 测试友好（每个节点是纯函数）
- 原生 Human-in-the-loop（interrupt_before）
- 子图嵌套清晰

### 为什么提示词放 .md 文件
- 提示词是生产资产，不该进代码 git blame
- LRU 缓存加载，不影响性能
- 支持 Dify 同步（用 export_dify_prompts.py）

### 为什么标的识别用 ReAct Agent 而非流程图
- 标的识别是组合工具调用问题（非线性）
- Agent 能根据中间结果动态决定下一步
- Dify 原 24 节点工作流收敛为 7 个工具 + 1 个循环

### 为什么 thread_id = conversation_id
- 企微同会话的消息天然需要共享状态
- LangGraph checkpointer 按 thread_id 隔离，自然匹配
- 跨客户/跨群的 state 完全隔离
