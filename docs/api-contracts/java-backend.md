# Java 后端业务 API 契约

> 来源：Java 后端 `yudao-module-integration` 与 `yudao-module-wechat-bot` 源码核对。
> 本文件是事实清单：`app/tools/` 的 Pydantic 模型按此契约定义；Java 契约变更时同步修改本文。

## 0. 框架级路径前缀（关键）

`yudao-framework/yudao-spring-boot-starter-web/.../WebProperties.java:22`：

```java
private Api adminApi = new Api("/admin-api", "**.controller.admin.**");
```

**所有 `controller.admin.**` 包下的 Controller 自动加 `/admin-api` 前缀。** 本文档列出的所有路径是**完整路径**（含 `/admin-api`）。

## 路径分类

| 类别 | 含义 | LangGraph 侧处置 |
|------|------|------------------|
| **业务 API** | Java 业务接口（操作、查询、会话写回） | 经 `app/tools/` 的 Protocol 客户端调用 |
| **机器人参数透传** | Java Worker 从企微消息抽出上下文，作为 inputs 传给 LangGraph | 不经 tools/ 调用，由入口与 ingest 节点解析 |

## Java → LangGraph 的会话入口

`POST /v1/workflows/run` 接收 Java 实际发送的顶层 `conversation_id`，并兼容
`inputs.conversationId`、`inputs.conversation_id`。响应顶层为 `conversationId`、`answer`，
同时保留 Dify `data.outputs`。

| 请求情况 | 行为 |
|----------|------|
| 任一位置提供非空字符串 ID | 原样复用，不重新生成、不包装、不裁剪首尾空格、不解析 UUID或转换格式 |
| 多个位置提供相同非空 ID | 复用该值，按原文逐字符比较 |
| 多个位置提供不同非空 ID | HTTP **422**；不生成 ID，不执行主图、业务请求或 `/set-intent` |
| 三个位置都未传或为空（`null`、`""`、纯空白字符串） | 仅生成一次纯 UUID v4，例如 `703840e9-e176-4337-979c-6b175f5591c2` |
| 提供非字符串 ID | HTTP **422**，不将数值、布尔或对象转成字符串 |

顶层 `user` 是稳定用户标识，不作为会话 ID。解析后的值同时用于
`state.conversation_id`、checkpoint `configurable.thread_id`、Java 业务请求
`conversationId`、`/set-intent` 和响应 `conversationId`。
`workflow_run_id`、`task_id`、`trace_id` 是独立的调用标识，不参与会话续接。

第二轮示例（`conversation_id` 必须是首轮响应或 Java 已有的原值）：

```json
{
  "conversation_id": "java-original-session-id",
  "inputs": {
    "raw_content": "1M",
    "quote_content": "-----场外期权询价详情-----\nQ-20260907-000001\n期限待补充",
    "message_id": 2,
    "room_id": "room-1"
  },
  "response_mode": "blocking",
  "user": "stable-user"
}
```

启用 checkpoint 时，同一会话恢复历史；主图在 `render` 后通过 `record_history`
追加当轮用户原话与最终回复。业务子图只读取历史，其完整 state 输出不向父图重复追加旧历史。

当轮消息编号、群、操作者、附件及对手参考列表必须由当前请求提供，
缺失时显式清空，不从 checkpoint 继承。缺少有效消息编号时不提交交易，也不调用
`/set-intent` 更新上一条消息；顶层 `user` 补充用户身份的规则保持不变。

## 确认指令的参数职责

[ADR 0021](../adr/0021-text-confirm-replaces-interrupt.md) 明确：LangGraph 识别本次动作、订单号及适用的显式增量参数，Java 从数据库读取已有订单、合并参数、校验并执行。普通确认不要求 LangGraph 从历史或引用卡片补齐完整订单；引用用于确定本次操作对象与范围。是否有多轮上下文不改变这项职责。LangGraph 不强制二阶段处理，也不把普通动作自动变成确认；现有确认 type 仅用于用户本次明确输入的动作，后续业务流程由 Java 决定。

互换、期权仍使用既有 `type` 与 `orderList`，平仓使用 `closeOrderReqVO` 内对应的订单号列表；机器人上下文继续按原契约透传。纯确认的订单业务字段只需携带订单号，允许补参的意图按现有契约传递本次明确提供的字段。接口路径、DTO、缺省字段序列化与确认口令均保持现状，不新增接口或补参准入。

当前 Python 期权确认下单仍会结合引用与历史拼装完整 `orderList`，尚未完成上述参数收敛；具体待办见 [工作计划](../work-plan.md#12-确认指令职责收敛规范已采纳代码待调整)。本文的职责说明不代表现有出站参数已完成调整。

## 1. 标的（Ticker / Instrument）

LangGraph 业务链只在既有订单字段传递标的原始表达或用户对引用候选的明确选择。Java 业务接口
按业务需要调用对应的标的识别工作流并处理结果，LangGraph 不参与识别工作流的调用或编排。
以下标的查询接口仅保留为后端内部参考契约，不作为 LangGraph 提交前识别或拒绝依据；
识别工作流的内部调用关系由后端维护。职责见 [标的识别后端边界](../architecture/backend-instrument-boundary.md)。
HTTP `outputs.tickers` 保留为空列表的兼容字段，验收检查实际后端回复。

### 1.1 标的查询（后端内部参考）

- **HTTP**: `GET /admin-api/integration/securities-instrument/select` ⚠️ **GET + RequestBody，不规范但合法**
- **Controller**: `SecuritiesInstrumentController.selectSecuritiesInstrumentPage()` (`SecuritiesInstrumentController.java:100`)
- **调用边界**: 仅后端内部参考；LangGraph 业务链、测试、验收脚本和探针均不得调用，不据此推定识别工作流的具体调用方式
- **入参** `SecuritiesInstrumentOpenApiReqVO`:
  - `keywordItems: list[KeywordItem]` — 关键词列表，每项 `{keyword: str, isFull: bool}`
  - 可能含 `transactionTypeList: list[str]` 过滤
- **出参** `list[SecuritiesInstrumentOpenApiRespVO]`:
  - `windCode: str` — 标的代码（如 `"600989.SH"`）
  - `insShtDesc: str` — 标的简称
  - `insLngDesc: str` — 标的全称
  - `relevanceScore: int` — 匹配分数（低分优先）
  - `transactionTypeLists: list[str]`
- **底层逻辑**: `InstrumentApiSearchHelper.searchAndScore()` (`InstrumentApiSearchHelper.java:105`)
- **认证**: `@PlatformApiAuth`（开放接口）

### 1.2 交易对手列表

- **HTTP**: `GET /admin-api/counterparty/info/list`
- **Controller**: `CounterpartyInfoController.list()`
- **入参** `CounterpartyInfoRespVO`: 查询字段
- **出参** `list[CounterpartyVO]`
- **认证**: `@PlatformApiAuth`

## 2. 期权操作（FinancialOrders）

Python 出站只做现有 DTO 的类型装配，模型按字段契约提取值并保留原文来源。LangGraph 不再把期限换算为月份，不补时间日期，不重算金额、比例或业务默认值（ADR 0027）。Java 负责业务值校验；不兼容字段须明确核对，不能隐藏换算。

期权请求下单与确认下单按订单绑定各自参数；序号按引用标签、"第N笔"按引用顺序。
请求撤单存在明确范围时只选择指定订单，范围无法解析时停止提交；引用多单的裸"撤单"
继续默认全选。最终确认须满足本次明确动作和订单选择；单号可来自本次原文或用户引用，不从历史重建订单。

### 2.1 操作聚合接口

- **HTTP**: `POST /admin-api/financial-orders/operate`
- **Controller**: `FinancialOrdersOpenApiController.operate()` (`FinancialOrdersOpenApiController.java:38`)
- **调用方**: LangGraph（经 Protocol 客户端）
- **核心入参** `FinancialOrderOpenApiSaveReqVO`:

```python
class FinancialOrderOpenApiSaveReqVO:
    operate: str | None      # 注释为"操作"，不强制
    type: str                # 注释为"意图"，对应 stockOptionIntentionType（必填）
    orderList: list[FinancialOrderOpenApiBaseSaveReqVO]
    closeOrderReqVO: CloseOrderReqVO | None
    optionRfq: GoatsOptionRfqReqVO | None     # 询价/雪球参数
    
    # 机器人上下文（必填）
    conversationId: str       # dify 会话 id
    messageId: int            # 消息 id
    messageContent: str       # 消息内容（含引用）
    rawContent: str           # 原始消息内容
    quoteContent: str | None  # 引用消息内容
    quoteAppinfo: str | None  # 引用元数据（弃用）
    userId: str               # 客户唯一 ID
    roomId: str               # 群 ID
    guid: str | None          # 机器人设备 id
```

- **type 字段枚举**（`StockEnum.stockOptionIntentionType`，16 值）：

| type 值 | 含义 |
|---------|------|
| `new_inquiry` | 新询价 / 询价参数补充或修正（例如期限） |
| `place_order_from_quote` | 基于报价下单 / 请求下单 / 建仓参数补充 |
| `confirm_order` | 确认下单 |
| `cancel_order_request` | 取消下单请求（订单直接作废） |
| `request_cancel_order` | 请求撤单 |
| `confirm_cancel_order` | 确认撤单 |
| `request_modify_order` | 请求改单 |
| `confirm_modify_order` | 确认改单 |
| `query_order_status` | 查询订单状态 |
| `close_order_query` | 平仓查询 |
| `close_order_request` | 平仓请求下单 |
| `close_order_confirm` | 平仓确认下单 |
| `close_order_cancel_request` | 平仓请求撤单 |
| `close_order_cancel_confirm` | 平仓确认撤单 |
| `close_order_order_query` | 平仓订单查询 |
| `unknown_intent` | 无法识别 |

- **`orderList` 元素** `FinancialOrderOpenApiBaseSaveReqVO` 字段（部分）：
  - `placeOrderWindCode: str`
  - `placeOrderPrice: Decimal`
  - `placeOrderQuantity: int`
  - `placeOrderOrderType: Literal["BY_QTY", "BY_AMOUNT"]`
  - `placeOrderOrderDirection: GoatsOrderDirection`
  - `placeOrderPriceType: GoatsPriceType`
  - `notionalAmount: Decimal`（Java 处理精度，LangGraph 不截断）

### 询价补参与提取字段

- `OptionInquiryItem.orderId: str | None`：补参携带原 `Q-...` 询价单号，首次询价无原单号时为空。
- `OptionOrderItem.tenor: str | None`：建仓/改单提取也保留本轮给出的期限，避免 Java 纠正意图时期限已被丢弃。
- `orderId` 与 `tenor` 在同一 `orderList` 元素中传递。提取模型中未提供字段为 `null`，HTTP 客户端排除 `None`，由 Java 合并原单缺省参数。
- 引用询价卡片补充 `1M` 归 `new_inquiry`；建仓参数补充、确认和撤单分别按用户动作及业务阶段判断。卡片的“询价详情”“如需下单”等固定文字不能强制转入下单分支。

引用原询价单 `Q-20260907-000001` 回复 `1M` 时，Java 收到的业务部分为：

```json
{
  "type": "new_inquiry",
  "orderList": [{"orderId": "Q-20260907-000001", "tenor": "1M"}]
}
```

同一请求仍包含上述机器人上下文（含相同 `conversationId` 和原 `quoteContent`）。
Java 生成的卡片原样返回为 `answer` 和 `data.outputs.reply_text`，不由本地重建或补写卡片。

### 2.2 平仓订单查询

- **HTTP**: `POST /admin-api/financial-orders/query-close-orders`
- **Controller**: `FinancialOrdersOpenApiController.queryCloseOrders()` (`:49`)
- **调用方**: LangGraph（经 Protocol 客户端）

## 3. 互换操作（SwapOrder）

### 3.1 操作聚合接口

- **HTTP**: `POST /admin-api/swap-order/operate`
- **Controller**: `SwapOrderOpenApiController.operate()` (`SwapOrderOpenApiController.java:33`)
- **调用方**: LangGraph（经 Protocol 客户端）
- **核心入参** `SwapOrderOpenApiSaveReqVO`:

```python
class SwapOrderOpenApiSaveReqVO:
    type: str                 # 必填，对应 SwapIntentionType（注意：互换没有 operate 字段！）
    orderList: list[SwapOrderOpenApiBaseSaveReqVO]
    
    # 机器人上下文（同期权）
    conversationId: str
    messageId: int
    messageContent: str
    rawContent: str
    quoteContent: str | None
    userId: str
    roomId: str
    guid: str | None
```

- **type 字段枚举**（`SwapEnum.SwapIntentionType`，7 值）：

| type 值 | 含义 |
|---------|------|
| `place_order_request` | 请求下单/改单（**注意：下单和改单共用此 type**） |
| `confirm_order` | 确认下单 |
| `cancel_order_request` | 请求撤单 |
| `confirm_cancel_order` | 确认撤单 |
| `confirm_modify_order` | 确认改单（独立的） |
| `query_order_status` | 查询订单状态 |
| `unknown_intent` | 无法识别 |

> **重要差异**：互换的"下单 vs 改单"靠 `orderList` 内容区分（含 `orderId` 即改单），不靠 `type` 字段。LangGraph 子图设计要照此处理。

- **出参**：`CommonResult<String>`。`code == 0` 时以 `data` 作为最终回复；
  `code != 0` 时以 `msg` 作为最终回复。Java 返回的互换卡片或拒绝消息原样写入
  `answer` 和 `data.outputs.reply_text`，`render` 不根据本地结构化参数重建、补写或
  改写业务内容。后端结果为空时只返回系统失败提示，不生成本地成功回执。

- **`orderList` 元素** `SwapOrderOpenApiBaseSaveReqVO` 字段：
  - `placeOrderWindCode: str`
  - `placeOrderTransactionType: GoatsTransactionType`（A_SHARE / HK_STOCK / US_STOCK / ...）
  - `placeOrderQuantity: int` — 委托数量（股）
  - `placeOrderQuantityHand: int` — 委托数量（手）
  - `placeOrderOrderDirection: GoatsOrderDirection`（BUY / SELL / SHORT_OPEN / SHORT_CLOSE）
  - `placeOrderPriceType: GoatsPriceType`（LIMIT_ORDER / MARKET_ORDER）
  - `placeOrderPrice: Decimal`
  - `placeOrderAlgorithmType: GoatsAlgoType`（POV / TWAP / VWAP / ICEBERG / SNIPER）
  - `placeOrderStartTime: datetime`
  - `placeOrderEndTime: datetime`

### 3.2 互换订单详情

- **HTTP**: `GET /admin-api/swap-order/get?orderId=`
- **Controller**: `SwapOrderOpenApiController.get()` (`:45`)

### 3.3 会话订单列表

- **HTTP**: `POST /admin-api/swap-order/get-conversation-orders`
- **Controller**: `SwapOrderOpenApiController.getConversationOrders()` (`:54`)

## 4. 持仓 / 平仓（Goats 配置驱动）

本节说明 Java 内部的 GOATS 集成，不是 LangGraph 新增的直接出站调用；LangGraph 仍经现有期权业务接口提交，出站路径以文末清单为准。

| 功能 | 配置 key | 说明 |
|------|----------|------|
| 平仓合约列表 | `GOATS_OPTION_CLOSING_OUT_CONTRACT_QUERY` | Goats 直调 |
| 平仓下单 | `GOATS_OPTION_CLOSING_OUT_PLACE_AN_ORDER` | Goats 直调 |
| 平仓订单查询 | `GOATS_OPTION_CLOSING_OUT_ORDER_QUERY` | Goats 直调 |

注：本组接口的 endpoint URL 由 `IntegrationEnum` 配置驱动，不直接在 Controller 注解里写死。

## 5. 关键 Goats 枚举（共用）

| 枚举 | 关键值 | 来源 |
|------|--------|------|
| `GoatsOrderDirection` | `BUY / SELL / SHORT_OPEN / SHORT_CLOSE` | `SwapEnum.java:148` |
| `GoatsPriceType` | `LIMIT_ORDER / MARKET_ORDER` | `:182` |
| `GoatsAlgoType` | `POV / TWAP / VWAP / ICEBERG / SNIPER` | `:213` |
| `GoatsTransactionType` | `A_SHARE / HK_STOCK / US_STOCK / SZ_HK_CONNECT / SH_HK_CONNECT / CHN_FUTURE / CROSS_FUTURE` | `:59` |
| `GoatsOrderStatus` | `DRAFT / NEW / PARTIALLY_FILLED / FILLED / CANCELED / REJECTED / ...` | `:287` |
| `Exchange` | `SSE / SZSE / HKEX / NYS / NAS / LME / CME / ...` | `:419` |
| `GoatsCurrency` | `CNY / CNH / HKD / USD / EUR / GBP / JPY / NZD / AUD` | `:381` |

## 6. 消息会话与意图持久化（set-intent）

以下字段依据 Java 源码中的"存储消息意图"逻辑核对。

- **HTTP**: `POST /admin-api/openapi/xbot/message/set-intent`
- **Controller**: `BotOpenApiMessageController.setIntent()`（`yudao-module-wechat-bot-biz`，`controller/admin/open/xbot/`）
- **请求 DTO**: `XbotSetMessageIntentReqVO`（同目录 `vo/`）；Python 对应 `app.tools.message_client.SetIntentRequest`
- **服务语义**: `StockBotMessageServiceImpl.setMessageIntent()` 按 `messageId` 找已有消息，写入会话 ID、意图和产品类型，同时维护会话记录；消息不存在时报错。
- **响应**: `CommonResult<String>`，Controller 正常返回 `CommonResult.success("ok")`。LangGraph 仅将 HTTP 2xx 且显式整数 `code == 0` 视为成功，不依赖 `data` 内容。

| JSON 字段 | 类型 | LangGraph 写入规则 |
|-----------|------|-------------------|
| `conversationId` | string | 原样使用 `state["conversation_id"]`；不解析 UUID、不增删括号或反斜杠、不重新格式化 |
| `messageId` | string | `str(state["message_id"])`；`/operate` 的整数 `messageId` 不变 |
| `intent` | string | 当前 `state["intent"]`；缺失或为空时为 `unknown_intent` |
| `productType` | integer | `swap → 1`；`option / option_close / unknown → 0` |
| `orderIds` | array | 固定 `[]`，不从业务订单结果填充 |

Java DTO 对 `messageId`、`conversationId` 要求非空，对 `productType` 要求非 null。

### 客户端与失败处理

`MessageClient` Protocol 的 `set_intent(req)` 成功返回 `CommonResult(code=0, ...)`，失败抛异常。
真实实现 `MessageClientHttpx` 复用 `OTC_API_BASE_URL` 和 `OTC_API_SECRET`（`Authorization: Bearer ...`），
并通过现有 `get_goats_auth_headers()` 生成 GOATS HMAC-SHA256 签名头。
Java 当前 Controller 标注 `@PermitAll`；客户端仍沿用现有后端鉴权配置。
默认请求超时取 `backend_timeout_seconds`（5 秒），`trust_env=False`，测试可注入 `httpx.MockTransport`。

- 仅超时、连接失败及 HTTP 5xx：间隔 100ms 重试一次，总计最多两次请求，重试发送同一请求体并重新生成签名。
- HTTP 4xx（包括 429）、重定向、其他传输错误、业务非零码和无效响应：立即失败，不重试。
- 缺失 `code`、字符串 `"0"`、布尔 `false` 均不视为成功；错误不透传后端正文或请求鉴权信息。
- `DRY_RUN_BACKEND` 只拦截交易副作用；消息元数据属于回复链路必需写入，不受该开关影响。

### 主图与 HTTP 入口

每轮流程为：`业务子图或 fallback → persist_intent → persist(node_trace) → render → record_history`。
`persist_intent` 等待 Java 确认；失败经 `safe_node` 写入 `error` 和失败 trace，后续 `persist` 仍执行，
其 MySQL 故障不阻断主流程的既有行为不变。

`build_main_graph(checkpointer=None, message_client_factory=None)` 默认不写外部消息表；
单测与直接调用主图的 harness 可保持此默认值，也可显式注入 `MessageClient` 工厂。
FastAPI lifespan 显式注入 `MessageClientHttpx`，保证真实 HTTP 入口每轮执行写回。

`POST /v1/workflows/run` 在 `/set-intent` 最终失败后返回 **HTTP 502**：

```json
{"code": "internal_server_error", "message": "消息会话与意图持久化失败，请稍后重试。", "status": 502}
```

该响应不含正常 `answer` 或 Dify 成功响应数据。图执行失败且无可返回回复时也返回 502。
当前全链路超过请求预算返回 504，`code=workflow_timeout`，响应带 `idempotency_status=uncertain`。
启用请求幂等时，图内超时路径尝试保存 504 快照；最外层超时或快照写库失败可能只留下占位，
不能保证完整响应已经保存。已有快照（含失败）优先回放；无快照的占位返回处理中或待核对提示，
同一消息不重新执行。默认 LLM/工具/请求预算为 20/5/60 秒，当前预留 5 秒收尾（包括快照写入）；
请求预算最大 80 秒，早于 Java 的 90 秒。

[ADR 0026](../adr/0026-request-idempotency-uncertain-receipts-reconciliation.md) 已采纳调用端管理消息防重、
重投和重复通知的职责规范；LangGraph 应每次合法调用独立处理，Java 负责交易执行幂等。
当前代码仍有上述占位和回放，以及 `retry_origin=XBOT_GET_DIFY_FAIL`、非快速询价且 `api_code=900`
时的静默回复投影；新调用与回放都会应用该投影。代码清理与 wire 字段调整见 [工作计划](../work-plan.md)，
本轮规范修订不改变现行 HTTP 响应、Java 配置或 DTO。

入口仍为 `/v1/workflows/run`，支持顶层 `query` 和 `files`，原有 inputs 原文优先；附件冲突为 422。
正常响应保留 `workflow_run_id/task_id/conversationId/answer/data`，同时返回
`id/message_id/event/mode/metadata/conversation_id/created_at`；两个会话字段取同一值。
`data.outputs.trace` 保留字符串形式，新增 `trace_entries` 供逐节点分析；失败时 outputs.error
仅提供 E1–E5 分类、节点和异常类型，不返回内部错误详情或堆栈。
会话 ID 按本文入口规则解析：三个兼容位置均为空才生成一次纯 UUID，已有 ID 原样复用；冲突返回 422。

## 7. 其他

- Java 侧金额精度以其 DTO 与 `TradePrecisionUtil.truncateOrderScale()` 为准。LangGraph 按 ADR 0027 的目标不自行计算或截断业务数值；请求前清洗核对 Java 字段类型及自定义反序列化兼容，仅省略不可接收值，不重算业务值。
- 认证：所有 `@PlatformApiAuth` 接口走平台级 token，不依赖用户登录
- LangGraph tools 层调用时机器人参数（`messageId / conversationId / userId / roomId / ...`）由入口从 Workflow Run inputs 解析后存入 AgentState，再由具体节点透传给 Java 业务 API

## LangGraph 出站后端 API 清单

以下为截至 2026-09-24 应用客户端及后端健康检查的完整固定业务路径，真源为 `app/tools/*_client.py` 与 `app/observability/health_probes.py`。URL 使用配置的服务基址；本表不包括模型、Langfuse、附件下载或 Java 内部调用。独立运维脚本的 GOATS 专项探针另见 `scripts/probe_goats/README.md`，不代表业务图新增出站路径。

| HTTP 方法与路径 | 客户端 / 调用方 | 用途 |
|---|---|---|
| `POST /admin-api/financial-orders/operate` | `OptionClient` | 期权 / 平仓动作，按现有 type 与 DTO |
| `POST /admin-api/financial-orders/query-close-orders` | `OptionClient` | 平仓订单查询 |
| `POST /admin-api/swap-order/operate` | `SwapClient` | 互换动作 |
| `GET /admin-api/swap-order/get?orderId=...` | `SwapClient` | 互换订单详情 |
| `POST /admin-api/swap-order/get-conversation-orders` | `SwapClient` | 会话订单列表 |
| `POST /admin-api/openapi/xbot/message/set-intent` | `MessageClient` | 消息会话 ID 与意图写回 |
| `GET /admin-api/counterparty/info/list` | `TickerClient` | 本地授权对手查询（需要 type、roomId、userId）；就绪探针只检查 TCP，交易子图不使用 TickerClient |
| `POST /api/internal/agent/option_rfq_instrument_parser` | `GoatsAgentClient` | 快速询价入口解析 |
| `POST /api/internal/agent/instruction/query` | `GoatsAgentClient` | 存量指令兼容查询 |

`app/tools/ticker_client.py` 保留，但证券查询接口 `GET /admin-api/integration/securities-instrument/select` 不属于允许的出站路径：本地业务、测试、验收与探针一律不调用。后端内部参考契约的保留不授予本地调用权限。

Protocol 按 Java 真实 endpoint 边界拆分（期权、互换各一个聚合操作接口），Pydantic 模型与 Java DTO 一一对应（ADR 0001 D2）。


## 请求前类型清洗

普通期权、互换和平仓经各产品 `clean_request` 节点后提交 Java。`notionalAmount` 与 `placeOrderNotional` 对应 BigDecimal；互换数量、可见数量、总量对应 Long；平仓 `closeOrderNotionalDelta` 对应内容为数字的 String。带单位的 `100万` 省略字段，纯数字字符串允许无损装配；0、false、负数保留，数值范围与业务默认值由 Java 决定。不会把省略字段补成 0 或从旧卡片补回。

原始参数与字段证据保留；`backend_request` 是 DTO 实际序列化请求，`cleaning_records` 记录省略/转换原因。HTTP outputs 的业务参数信封投影实际出站值，Harness 沿用现有字段断言。

Dify 兼容只在清洗入口处理参数字符串 JSON 失败：期权 `type=null / operate=null / orderList=[]`，互换 `type=null / orderList=[]`，平仓保留外部 type 并发送 `closeOrderReqVO={} / operate="" / orderList=[] / optionRfq={}`。这些请求继续发送，HTTP 异常按 Dify 显示“交易指令服务暂不可用”，原始状态与响应留节点审计。不补 unknown_intent，也不重试模型或交易。
