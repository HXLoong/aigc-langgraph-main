# ADR 0026 · 调用端幂等职责与单次调用回执契约

- 状态：已采纳（职责规范，代码待调整）
- 日期：2026-09-24
- 关系：修订 [ADR 0024](./0024-langgraph-native-rearchitecture.md) D4 的幂等职责；单次调用模型额度见 [ADR 0031](./0031-single-model-request-per-message.md)；补充 [ADR 0021](./0021-text-confirm-replaces-interrupt.md) 确认链路的回执语义；错误分类进入 [ADR 0019](./0019-incident-severity-thresholds.md) 告警
- 作者：图灵科技 + Tony

## 背景

LangGraph 是调用端使用的指令处理工具：接收本次输入，完成识别、校验和后端调用，再返回本次结果。调用端掌握消息投递与重试，Java 业务端掌握订单与交易执行；消息防重和交易幂等应分别由这两层负责。

调用端可能在超时或服务故障后重新调用同一条消息。如果 LangGraph 按消息 ID 永久封存失败响应，调用端的恢复性重试就无法继续处理。另一方面，HTTP 超时不能证明交易未执行；是否重投以及如何避免重复交易，必须由调用端与 Java 业务端协同决定。

CLAUDE.md P0 纪律"业务代码不能掩盖后端真实响应"约束所有回执处理。

## 决策

### D1 · 每次合法调用独立执行，消息幂等归调用端

- 调用端负责消息防重、并发调度、重试次数与重复通知；Java 业务端负责交易执行幂等和权威结果。
- LangGraph 接受每次合法调用，不按 `message_id` 占位、拦截、缓存回放或锁定失败请求，也不维护消息级 `in_progress / done / uncertain` 状态机。相同消息 ID 的再次调用重新执行本次处理链，仍须通过既有输入、身份和确认校验。
- `message_id` 原样用于业务传递与审计关联；每次调用保留独立 trace。消息 ID 相同不代表共享模型额度，计数规则见 ADR 0031。
- 会话 checkpointer、历史上下文和节点审计继续承担原有职责，不作为消息防重或交易结果恢复机制。

### D2 · 单次调用预算与超时响应

| 预算 | 默认 | 约束 |
|---|---|---|
| 整体请求 `request_timeout_seconds` | 60s | 最大 80s，必须早于 Java 90s |
| LLM 单次 `llm_timeout_seconds` | 20s | 每次工具调用全链路最多一次模型请求，SDK 与图层均不重试（ADR 0031，代码待重构） |
| 业务工具 `backend_timeout_seconds` | 5s | GOATS / operate / set-intent 各自可配 |
| 调用收尾预留 `response_reserve_seconds` | 5s | 图预算从本次剩余预算中扣除预留；用于响应与审计收尾 |

超预算返回 HTTP 504、`code=workflow_timeout`；错误分类 E5，trace 记 `workflow_deadline`。异步墙钟取消可穿透 `@safe_node`。超时只说明本次调用未取得完整结果，不证明交易成功或失败，也不产生用于拦截下一次调用的幂等快照。调用端决定是否重新调用；LangGraph 不主动重跑整图或交易写节点。

### D3 · 回执契约：无法验证的回执是"不确定"，不推断成功或失败

`app/tools/receipts.py`：

- `receipt_guard`：只包住 dispatch / 解码阶段；此阶段的 `httpx.HTTPError` / `ValueError` 升为 `BackendUnreachableError(unverifiable_receipt:*)`，表示本次写入回执不可验证。dispatch 前的 DTO 错误不算不确定写入。
- `receipt_update`：`code` 非整数、或 `code=0` 但 `data` 为空 → `EmptyBackendResultError`，**不伪造成功回执**；原始 `api_code` / `api_result` 原样保留供审计。
- `receipt_text`：`code=500` 统一用户文案"交易指令服务暂不可用"（业务方确认的展示规则）；非零且无 `msg` → "未知错误"；有效成功卡片完全由 Java 生成，LangGraph 不改写。

不确定回执是对本次执行结果的描述，不是消息锁或重试裁决。LangGraph 保留错误与审计证据供调用端核查，不能用本地抽取结果伪造交易卡片。

### D4 · 重复通知由调用端处理

LangGraph 按 D3 返回本次真实回执，不根据 `retry_origin` / `retry_attempt` 把 `api_code=900` 的回复改为 `IGNORE_REQUEST_NOT_REPLY_USER`，也不因系统重投生成 `notification_suppressed`。调用端决定是否向用户发送通知；此条不改变其它既有业务静默条件。

### D5 · 执行结果核查与对账归调用端及 Java 业务端

- 调用端及 Java 业务端负责关联原请求、核实交易结果、恢复通知和组织运维对账。具体实现与验收属于外部系统职责，本 ADR 不声称这些能力已经完备。
- LangGraph 提供调用 trace、原始消息标识和可取得的后端回执，不读取 Java 访问日志来重建可回放响应，也不承担幂等记录的对账应用。
- 核查应按完整消息标识与身份关联证据；缺少回执、日志缺失或仅有订单行，都不足以推断本次调用已执行或未执行。

### D6 · 错误分类 E1–E5（`app/graph/state.py::ErrorInfo`）

| 代码 | 语义 | 典型异常 |
|---|---|---|
| E1 | 模型服务不可用 / 限流 / 超时 | `APITimeoutError` / `RateLimitError` / `InternalServerError` |
| E2 | 模型输出不可信（证据 / 结构校验失败） | `EvidenceError` / `ValidationError` / `OutputParserException` |
| E3 | 其它节点异常（默认） | — |
| E4 | 后端不可达 / 回执不可验证 / 消息写回失败 | `BackendUnreachableError` / `EmptyBackendResultError` / `SetIntentError` |
| E5 | 请求预算耗尽 | `WorkflowTimeout` |

HTTP 错误字段只暴露分类、节点与异常类型，不返回内部详情与堆栈；harness 与告警按分类聚合。

### D7 · 消息写回属于本次调用的回复契约

普通业务链路回复前，`persist_intent` 按现有接线调用 Java `set-intent` 写回会话 ID 与意图；最终失败返回 502、不产生正常 `answer`。消息写回失败不证明此前交易失败，也不形成后续调用的幂等门禁。`DRY_RUN_BACKEND` 只拦截交易副作用，消息元数据写回不受影响；入口与开发环境的既有写回范围保持不变。

## 备选方案

- **LangGraph 消息占位、响应回放与对账**：工具持有调用端的重试裁决，失败快照会阻断恢复性调用，且引入额外数据库依赖。否决。
- **LangGraph 在超时后自动恢复或重试交易写入**：工具无法判断 Java 是否已经执行，不承担此调度职责。否决。
- **调用端管理消息生命周期，Java 保障交易幂等，LangGraph 返回本次结果（已选）**：职责与各方掌握的事实一致。

## 后果

- LangGraph 不再因历史请求状态阻断调用端重试，也不承诺跨调用只执行一次或回放同一响应；模型重解析可能产生不同结果，调用端负责总重试预算，Java 负责避免重复交易。
- 交易幂等需要外部系统提供相应保证，短期防重锁不等于完整的执行结果恢复能力；本次规范修订不修改 Java 源码、配置或接口契约。
- 当前代码仍保留请求占位、响应快照、重投静默与对账；规范已采纳，清理及验收待办见 [工作计划](../work-plan.md)。本轮不改变运行行为或历史数据库记录。

## 关联

- [ADR 0024](./0024-langgraph-native-rearchitecture.md) D4 · 持久化与调用职责
- [ADR 0021](./0021-text-confirm-replaces-interrupt.md) · 单次指令处理与 Java 业务流程
- [ADR 0019](./0019-incident-severity-thresholds.md) · 告警阈值
- `docs/api-contracts/java-backend.md` §6 · set-intent 契约 / 超时与 502 / 504 语义
