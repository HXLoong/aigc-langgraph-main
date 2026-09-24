# ADR 0026 · 请求级幂等、不确定回执与运维对账（金融写路径正确性契约）

- 状态：已采纳（追认，落地 commit `67f74c3` / `8249510`）
- 日期：2026-09-18
- 关系：D2 模型重试规则由 [ADR 0031](./0031-single-model-request-per-message.md) 修订；细化 [ADR 0024](./0024-langgraph-native-rearchitecture.md) D4；补充 [ADR 0021](./0021-text-confirm-replaces-interrupt.md) 确认链路的回执语义；错误分类进入 [ADR 0019](./0019-incident-severity-thresholds.md) 告警
- 作者：图灵科技 + Tony

## 背景

写类业务动作（下单 / 改单 / 撤单 / 确认 / 平仓）经 Java `operate` 接口落库，重复提交即重复下单。三个外部事实决定了契约形状：

1. **Java 侧 90 秒超时后会重投同一条企微消息**（`inputs.retry_origin = XBOT_GET_DIFY_FAIL`），且后端对重复业务请求返回 `code=900`。
2. **HTTP 超时后无法得知 `operate` 是否已执行**：请求可能已到达并落库，也可能未到达。
3. **Java 访问日志默认不记录 `operate` 端点的 `response_body`**：事后既不能靠订单行、也不能靠日志缺失证明"已执行 / 未执行"。

CLAUDE.md P0 纪律"业务代码不能掩盖后端真实响应"约束所有回执处理。

## 决策

### D1 · 消息级幂等：以企微 `message_id` 占位、回放完整响应，不确定写入永不重跑

- 幂等键 = 企微 `message_id`，与 `langgraph_message_log.uk_message_id` 对齐（`app/storage/idempotency.py`）；无 `message_id` 的请求不做幂等。
- 状态机 `in_progress → done | uncertain`：首次占位 → 跑图 → 回填完整 HTTP 响应（`reply_text` / `response` / `http_status`）。
- 重投处理：`done` → 原样回放（`outputs.replayed=true`、`idempotency_status`）；`in_progress` → 固定文案"该消息正在处理中，请勿重复提交"；占位超过 `processing_timeout_seconds`（默认 120s）未完成 → 视为 `uncertain`，回复"执行结果待核对，请勿重复提交"，**不重新执行**；上次以错误结束 → HTTP 502。
- 同一 `message_id` 出现在不同用户 / 群 → `IdempotencyConflictError`，拒绝回放。
- 幂等存储不可用时**阻止执行**（不退化为无幂等运行）；`REQUEST_IDEMPOTENCY` 默认关、客户模板开。

### D2 · 请求预算与超时快照

| 预算 | 默认 | 约束 |
|---|---|---|
| 整体请求 `request_timeout_seconds` | 60s | 最大 80s，必须早于 Java 90s |
| LLM 单次 `llm_timeout_seconds` | 20s | SDK 与图层均不重试 LLM；全链路最多一次请求（[ADR 0031](./0031-single-model-request-per-message.md)，代码待重构） |
| 业务工具 `backend_timeout_seconds` | 5s | GOATS / operate / set-intent 各自可配 |
| 响应落库预留 `response_reserve_seconds` | 5s | 图预算 = 请求预算 − 预留 |

超预算 → HTTP 504 `code=workflow_timeout`、`idempotency_status=uncertain`，完整 504 快照写入幂等表供同一消息回放；错误分类 E5，trace 记 `workflow_deadline`。异步墙钟取消可穿透 `@safe_node`。

### D3 · 回执契约：无法验证的回执是"不确定"，不推断成功或失败

`app/tools/receipts.py`：

- `receipt_guard`：只包住 dispatch / 解码阶段；此阶段的 `httpx.HTTPError` / `ValueError` 升为 `BackendUnreachableError(unverifiable_receipt:*)`，标记为不确定写入。dispatch 前的 DTO 错误不算不确定写入。
- `receipt_update`：`code` 非整数、或 `code=0` 但 `data` 为空 → `EmptyBackendResultError`，**不伪造成功回执**；原始 `api_code` / `api_result` 原样保留供审计。
- `receipt_text`：`code=500` 统一用户文案"交易指令服务暂不可用"（业务方确认的展示规则）；非零且无 `msg` → "未知错误"；有效成功卡片完全由 Java 生成，LangGraph 不改写。

### D4 · 系统重投通知静默

`app/api/notifications.py`：仅当 `retry_origin=XBOT_GET_DIFY_FAIL`、非快速询价、且回放响应的 `api_code=900`（后端"重复提交"码）时，`answer` 改为 `IGNORE_REQUEST_NOT_REPLY_USER` 并在 `metadata` 标记 `notification_suppressed=true`；普通业务拒绝与原始结果照常返回。

### D5 · 运维对账：只读 Java 回执，显式应用，不做交易写

`app/storage/reconciliation.py`：

- 只读取 Java 访问日志中 `/swap-order/operate` 与 `/financial-orders/operate` 的记录（`SELECT` only），按 `message_id` 精确关联，**禁止**旧的"末 18 位归一化"匹配。
- 结论枚举：`response_found` / `unknown` / `changed` / `already_done` / `in_progress` / `missing`；缺少回执 = `unknown`，订单行存在或日志缺失都不构成证明。
- 只有状态仍为 `uncertain` 且记录未变更时，运维显式 `apply` 才把找到的回执写回幂等记录；对账过程零交易写入。

### D6 · 错误分类 E1–E5（`app/graph/state.py::ErrorInfo`）

| 代码 | 语义 | 典型异常 |
|---|---|---|
| E1 | 模型服务不可用 / 限流 / 超时 | `APITimeoutError` / `RateLimitError` / `InternalServerError` |
| E2 | 模型输出不可信（证据 / 结构校验失败） | `EvidenceError` / `ValidationError` / `OutputParserException` |
| E3 | 其它节点异常（默认） | — |
| E4 | 后端不可达 / 回执不可验证 / 消息写回失败 | `BackendUnreachableError` / `EmptyBackendResultError` / `SetIntentError` |
| E5 | 请求预算耗尽 | `WorkflowTimeout` |

HTTP 输出只暴露分类、节点与异常类型，不返回内部详情与堆栈；harness 与告警按分类聚合。

### D7 · 消息写回是回放的前提

每轮回复前 `persist_intent` 调 Java `set-intent` 写回会话 ID 与意图；最终失败返回 502、不产生正常 `answer`。`DRY_RUN_BACKEND` 只拦截交易副作用，消息元数据写回不受影响。

## 备选方案

- **图内 durability 提交前落盘 + 自动恢复**：恢复后仍不知道 `operate` 是否已执行，自动重放等于自动重复下单。否决。
- **后端幂等 token**：需 Java 改契约（Java 源码不修改是本期硬约束）。否决，留作后续议题。
- **超时后自动重试写请求**：与 ADR 0024 D3"写类节点不重试"矛盾。否决。
- **占位 + 完整回放 + 不确定态人工对账（已选）**。

## 后果

- 正面：重投不重复下单；不确定态对用户可见且不可被重复触发；超时有统一快照；错误分类进 harness 与告警。
- 负面：`uncertain` 记录需要运维介入才能闭环；对账依赖 Java 开启 `response_body` 记录，否则多数结果停在 `unknown`；幂等表成为 `/v1/workflows/run` 的硬依赖。
- 未决：跨部署版本的响应回放兼容性；`processing_timeout` 120s 与请求预算 80s 的关系是否收紧；对账操作面（CLI / UI）；D4 的 `api_code=900` 语义需与 Java 契约文档钉死。

## 关联

- [ADR 0024](./0024-langgraph-native-rearchitecture.md) D4 · 持久化契约（本 ADR 记录其留白的裁决）
- [ADR 0021](./0021-text-confirm-replaces-interrupt.md) · 文本二阶段确认
- [ADR 0019](./0019-incident-severity-thresholds.md) · 告警阈值
- `docs/api-contracts/java-backend.md` §6 · set-intent 契约 / 超时与 502 / 504 语义
