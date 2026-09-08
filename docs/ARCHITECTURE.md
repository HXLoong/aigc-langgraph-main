# 架构

> 2026-08 DSL v2 迁移后版本。单页导览在先，细节在后；新人阅读路径：
> `CLAUDE.md` → 本页 → `CONTEXT.md`（领域语言） → `docs/adr/README.md`（决策索引）。

## 单页导览

```
企微群消息
    ↓ POST /v1/workflows/run（Dify 兼容协议，start 节点 14 入参）
FastAPI 接入层 (app/main.py + app/api/routes.py)
    ↓ thread_id = conversation_id · recursion_limit=50 · 预加载 checkpoint 历史
LangGraph 主图 (app/graph/main.py，11 节点)
    │
    ├─ ingest                消息规整 + 上下文装配
    ├─ ①前置分流 ──→ quick_inquiry          快速询价（GOATS rfq）
    │            └→ existing_command_query  存量兼容（静默哨兵）
    ├─ pre_route             对手预查 + 引用候选标的解析
    ├─ ②intent_route         两层路由：规则层(route_rules) → LLM 兜底 → 多轮粘性
    │     │
    │     ├─→ swap 子图          互换：意图/下单/选对手/选标的/确认二次校验/
    │     │                       撤单/查单/图片+Excel 多模态（8 意图链）
    │     ├─→ option 子图        期权：1 意图 + 7 提取节点 + 清洗 + 后端
    │     ├─→ option_close 子图  平仓：5 步引用解析链 + 7 意图分支
    │     │        └─ 三个子图按需调用 ticker 确定性管线
    │     │           （格式化 → 3 路并行 LLM → 枚举校验 → GOATS 校验+rank，
    │     │             from_goats=True 硬约束，ADR 0008）
    │     └─→ fallback           任一节点 error → cascade 守卫 → 友好降级
    │
    ├─ persist               意图审计落库
    └─ render                回复文本生成（+ default_reply 兜底）
    ↓
4 个 Protocol 客户端 (app/tools/)：option / swap / ticker / goats_agent
    ↓
Java 后端业务 API → 交易系统

侧翼：MySQL(checkpoint 库 + 业务库) · LangFuse(trace/提示词/评估) ·
      Prometheus /metrics · harness 评测台(golden 三桶 + Judge)
```

节点总数 39：主图 11 + 三业务子图 28。全部节点遵循同一模板：
`@safe_node` + `load_prompt()` + `with_structured_output(PydanticModel)`。

## 分层

### 1. 接入层（app/api/、app/main.py）
- FastAPI lifespan：启动时初始化 AIOMySQLSaver（应用级单例）+ build 主图
- `POST /v1/workflows/run`：兼容 Dify 工作流协议，接入 start 节点 14 个入参
  （fast_query / at_bot / existing_command / 对手 JSON 等，旧字段兼容）
- `GET /health`、`GET /ready`：探活；`GET /metrics`：Prometheus 指标
- `_build_run_config()`：统一注入 thread_id 与 `recursion_limit=50`

### 2. 图编排层（app/graph/）
- `main.py`：`build_main_graph()` 组装主图 + 嵌入 3 个业务子图
- `state.py`：`AgentState` TypedDict（按业务对象聚合；`trace` /
  `history_messages` 用 `Annotated[list, add]` reducer，其余覆盖型）
- `safe_node.py`：节点级异常捕获 → `state['error']`
- `cascade.py`：error 后的图级降级路由（三层防御：节点 → 图 → 应用 fallback）

### 3. 节点层（app/nodes/）
`ingest` / `fast_query`（快速询价 + 存量兼容前置分流）/ `pre_route`（对手 +
候选标的提取）/ `route_rules` + `intent_route`（DSL v2 两层路由 + 多轮粘性）/
`persist` / `render` / `fallback`

### 4. 子图层（app/subgraphs/）
每个业务域一个目录：`graph.py`（组装）+ `models.py`（Pydantic schema）+ 节点文件。

| 子图 | 节点构成 |
|---|---|
| swap | intent / place_order(+submit) / select_counterparty / select_ticker / confirm（三提示词 + 二次校验）/ cancel / query_order / multimodal（图片 + Excel）；撤单/查单/三确认 5 节点为确定性订单号提取（无 LLM） |
| option | intent + 7 个 extract（inquiry / place / confirm_place / cancel_place / confirm_cancel / cancel / query）+ sanitize + backend |
| close | intent / place_close（5 步引用解析链）/ cancel_close / confirm_close / confirm_cancel / holding_query / query_status |
| ticker | 确定性管线：候选格式化 → 3 路并行 LLM（infer / 拆分 / judge_type）→ 交易所枚举校验 → GOATS 校验 + rank（ReAct 已退役，见 ADR 0008 迁移记录） |

### 5. 工具层（app/tools/、app/llm/）
- 4 个 Protocol 客户端：`OptionClient` / `SwapClient` / `TickerClient` /
  `GoatsAgentClient`（md5-16 签名），类型契约与 Java DTO 1:1（`models.py`）
- 禁止绕过 Protocol 直接 `httpx` 调后端（ADR 0001 D2）
- `llm/clients.py`：LLM 统一工厂，全量 DeepSeek-V4-pro（ADR 0020，
  thinking 关闭 + structured output 走 function_calling 适配）

### 6. 资源层
- `app/prompts/`：42 个 Dify 迁移提示词（.md，约 850K 字符；swap 瘦身 v2
  灰度共存中）；来源优先级 LangFuse → 本地文件（ADR 0014）
- `app/state.py`：`make_initial_state()` + `WechatInput`（历史入口，非 shim）
- `app/config.py`：pydantic-settings，所有密钥走环境变量

## State 流转

```
客户消息 → wechat_input（不可变）
        → history_messages（checkpoint 预加载）
        → counterparty_list / quote_candidates（pre_route 填充）
        → product_type（intent_route 决定；双 unknown 时继承上轮粘性）
        → intent（子图 intent 节点填充）
        → tickers（ticker 管线填充，必须 from_goats=True）
        → place_params / order_ids（子图 extract 填充）
        → api_code / api_result（backend 节点填充，如实透传）
        → reply_text（render 生成）
        → trace[]（每节点追加；LLM 输出写入时截断 500 字符防膨胀）
```

## 存储

```
checkpoint 库（AIOMySQLSaver 管理，MySQL 8.0.19 ≤ v < 9.6.0）
├── checkpoints / checkpoint_blobs / checkpoint_writes / checkpoint_migrations
└── TTL 运维：scripts/cleanup_checkpoints.py（默认 dry-run，见 on-call runbook）

业务库（自管）
├── message_log / node_trace / shadow_compare / user_feedback
```

分库理由：checkpoint 写入频率高（每 superstep 一次），业务库是审计用途，
可独立扩容。

## 可观测性

- LangFuse self-hosted（`infra/langfuse/`，ADR 0014）：节点 span、LLM I/O、
  提示词版本、eval 富集 JSON（排查 SOP 见 CLAUDE.md"排查与修复流程"）
- Prometheus `/metrics`：HTTP 计数 + P95 延迟 + 5xx + LLM 成本
- 业务审计：`node_trace` 表；Grafana 灰度面板模板见 `docs/deploy/`

## 评估闭环（全仓最大资产）

```
golden 三桶（B 业务种子 / C 对抗改写 / D 客户真实输入,350+ 条）
    → scripts/langfuse_eval.py（DeepSeek Judge + per-turn 富集）
    → 按桶退出门（B ≥90% / C ≥80%）
    → harness（run / diff / sync-golden，仅 import build_main_graph）
```

## 设计决策（现行）

- **为什么 LangGraph**：typed state + reducer、节点纯函数可测、子图嵌套清晰
- **为什么提示词放 .md**：生产资产不进代码逻辑；LangFuse 可热更；
  版本共存灰度（v1/v2，ADR 0003）
- **为什么 ticker 用确定性管线而非 ReAct**：标的识别实为固定三步
  （推断 → 校验 → 排序），Agent 循环带来不可控延迟与幻觉面；
  DSL v2 已给出确定性蓝图（ADR 0008 修订）
- **为什么写类接口零自动重试**：后端 5 秒幂等锁 + dedup，自动重试会把
  网络抖动放大为用户可见混乱；失败走 cascade 如实降级（体检 2.1 节）
- **为什么 thread_id = conversation_id**：企微同会话天然共享状态，
  checkpointer 按 thread 隔离自然匹配
- **为什么单进程部署**：客户离线私有化最简形态：1 进程 + MySQL
  （+ 可选 LangFuse）

更多决策沿革见 `docs/adr/`（ADR 0000–0021），健康度基线见
`docs/archive/reports/architecture-maturity-review-2026-08.md`。
