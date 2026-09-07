# Java 后端业务 API 契约（LangGraph `app/tools/` 重写依据）

> 来源：`/Users/tony/code/GitHub/aigc/api/yudao-module-integration` + `yudao-module-wechat-bot` 实测代码挖掘
> 最近一次审计：2026-05-10（亲自核对源码与 Spring 框架配置）
>
> 本文件不是 ADR，是事实清单。tools/ 重写时按此契约定义 Pydantic 模型。

## 0. 框架级路径前缀（关键）

`yudao-framework/yudao-spring-boot-starter-web/.../WebProperties.java:22`：

```java
private Api adminApi = new Api("/admin-api", "**.controller.admin.**");
```

**所有 `controller.admin.**` 包下的 Controller 自动加 `/admin-api` 前缀。** 本文档列出的所有路径是**完整路径**（含 `/admin-api`）。

## 路径分类

| 类别 | 含义 | LangGraph tools 层处置 |
|------|------|------------------------|
| **Dify 回调路径** | 当前 Dify 工具节点回调 Java 业务 API | ✅ 必须实现（LangGraph 替换 Dify 后由其调用） |
| **机器人参数透传** | Java Worker 从企微消息抽出上下文，作为 inputs 传给 Dify/LangGraph | ⚠️ 不通过 tools/ 调，由 ingest 节点解析 |

## Java → LangGraph 的会话入口（2026-09-07 修订）

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

## 1. 标的（Ticker / Instrument）

### 1.1 标的查询（核心）

- **HTTP**: `GET /admin-api/integration/securities-instrument/select` ⚠️ **GET + RequestBody，不规范但合法**
- **Controller**: `SecuritiesInstrumentController.selectSecuritiesInstrumentPage()` (`SecuritiesInstrumentController.java:100`)
- **路径**: Dify 回调
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

### 1.2 动态推断 prompt 拉取（ADR 0013）

- **HTTP**: `GET /admin-api/counterparty/info/instrument-inference-prompt`
- **Controller**: `CounterpartyInfoController.getInstrumentInferencePrompt()` (`CounterpartyInfoController.java:33`)
- **路径**: Dify 回调
- **入参**: 无
- **出参** `CommonResult<String>`: 配置字符串，对应 `configApi.getConfigValueByKey("swap_instrument_inference_prompt")`
- **认证**: `@PlatformApiAuth`

### 1.3 交易对手列表

- **HTTP**: `GET /admin-api/counterparty/info/list`
- **Controller**: `CounterpartyInfoController.list()`
- **入参** `CounterpartyInfoRespVO`: 查询字段
- **出参** `list[CounterpartyVO]`
- **认证**: `@PlatformApiAuth`

### 1.4 交易时间查询

- **路径**: Java 直接（`InstrumentApiSearchHelper.queryTradingHours()`，非 HTTP 接口）
- 配置 key: `INVEST_TRS_TRADING_HOURS_CONFIG`
- LangGraph 接管后建议作为 `TickerClient` 的一个方法，实现走配置直读或新开 endpoint（待 D4 决定）

## 2. 期权操作（FinancialOrders）

### 2.1 操作聚合接口

- **HTTP**: `POST /admin-api/financial-orders/operate`
- **Controller**: `FinancialOrdersOpenApiController.operate()` (`FinancialOrdersOpenApiController.java:38`)
- **路径**: Dify 回调
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
  - `notionalAmount: Decimal`（精度截断 2 位）

### 询价补参与提取字段（2026-09-07 修订）

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
- **路径**: Dify 回调

## 3. 互换操作（SwapOrder）

### 3.1 操作聚合接口

- **HTTP**: `POST /admin-api/swap-order/operate`
- **Controller**: `SwapOrderOpenApiController.operate()` (`SwapOrderOpenApiController.java:33`)
- **路径**: Dify 回调
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

2026-09-07 核对本地 Java 源码及 `dify/yaml/主干工作流.yml` 的“存储消息意图”节点。

- **HTTP**: `POST /admin-api/openapi/xbot/message/set-intent`
- **Controller**: `BotOpenApiMessageController.setIntent()`（`yudao-module-wechat-bot-biz`，`controller/admin/open/xbot/`）
- **请求 DTO**: `XbotSetMessageIntentReqVO`（同目录 `vo/`）；Python 对应 `app.tools.message_client.SetIntentRequest`
- **服务语义**: `StockBotMessageServiceImpl.setMessageIntent()` 按 `messageId` 找已有消息，写入会话 ID、意图和产品类型，同时维护会话记录；消息不存在时报错。
- **响应**: `CommonResult<String>`，Controller 正常返回 `CommonResult.success("ok")`。LangGraph 仅将 HTTP 2xx 且显式整数 `code == 0` 视为成功，不依赖 `data` 内容。

| JSON 字段 | 类型 | LangGraph 写入规则 |
|-----------|------|-------------------|
| `conversationId` | string | 原样使用 `state["conversation_id"]`；不解析 UUID、不增删括号或反斜杠、不重新格式化 |
| `messageId` | string | `str(state["message_id"])`，与 Dify 一致；`/operate` 的整数 `messageId` 不变 |
| `intent` | string | 当前 `state["intent"]`；缺失或为空时为 `unknown_intent` |
| `productType` | integer | `swap → 1`；`option / option_close / unknown → 0` |
| `orderIds` | array | 固定 `[]`，不从业务订单结果填充 |

Java DTO 对 `messageId`、`conversationId` 要求非空，对 `productType` 要求非 null。

### 客户端与失败处理

`MessageClient` Protocol 的 `set_intent(req)` 成功返回 `CommonResult(code=0, ...)`，失败抛异常。
真实实现 `MessageClientHttpx` 复用 `OTC_API_BASE_URL` 和 `OTC_API_SECRET`（`Authorization: Bearer ...`），
并通过现有 `get_goats_auth_headers()` 生成 GOATS HMAC-SHA256 签名头。
Java 当前 Controller 标注 `@PermitAll`；客户端仍沿用现有后端鉴权配置。
默认请求超时为 30 秒，`trust_env=False`，测试可注入 `httpx.MockTransport`。

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
{"detail": "消息会话与意图持久化失败，请稍后重试。"}
```

该响应不含正常 `answer` 或 Dify 成功响应数据。502 仅用于此消息持久化失败路径；
成功响应结构、现有会话 ID 生成格式、交易 `/operate` 调用及其他失败语义不变。
会话 ID 按本文入口规则解析：三个兼容位置均为空才生成一次纯 UUID，已有 ID 原样复用；冲突返回 422。

## 7. 其他

- 精度纪律：金额字段一律 `Decimal`，向 Goats 发送前 `truncate(2)`（对齐 `TradePrecisionUtil.truncateOrderScale()`）
- 认证：所有 `@PlatformApiAuth` 接口走平台级 token，不依赖用户登录
- LangGraph tools 层调用时机器人参数（`messageId / conversationId / userId / roomId / ...`）由 ingest 节点从 Dify Workflow Run inputs 解析后存入 AgentState，再由具体节点透传给 Java 业务 API

## 关键代码定位（含真实行号）

| 功能 | 文件 | 行号 |
|------|------|------|
| 期权操作 Controller | `FinancialOrdersOpenApiController.java` | 38 |
| 期权 ReqVO | `FinancialOrderOpenApiSaveReqVO.java` | 14-69 |
| 期权意图枚举 | `StockEnum.java` | 42-79 |
| 互换操作 Controller | `SwapOrderOpenApiController.java` | 33 |
| 互换 ReqVO | `SwapOrderOpenApiSaveReqVO.java` | 13-61 |
| 互换意图枚举 | `SwapEnum.java` | 20-43 |
| 标的查询 Controller | `SecuritiesInstrumentController.java` | 100 |
| 标的查询底层 | `InstrumentApiSearchHelper.java` | 105 |
| 推断 prompt 接口 | `CounterpartyInfoController.java` | 33 |
| 框架级 API 前缀配置 | `yudao-framework/.../WebProperties.java` | 22 |
| Goats 共用枚举 | `SwapEnum.java` | 59-509 |

## Tools 层目标 Protocol（按真实契约调整）

- **`OptionClient`** — 替代之前的 `QuoteClient` + 部分 `OrderClient` + 平仓部分；操作走 `POST /admin-api/financial-orders/operate`，type 字段驱动 16 种意图
- **`SwapClient`** — 互换全套；操作走 `POST /admin-api/swap-order/operate`，type 字段驱动 7 种意图
- **`TickerClient`** — `GET /admin-api/integration/securities-instrument/select` + `GET /admin-api/counterparty/info/instrument-inference-prompt` + `GET /admin-api/counterparty/info/list`
- **`MessageClient`** — `POST /admin-api/openapi/xbot/message/set-intent`，每轮回复前写回会话 ID 和意图（见 §6）

> **重大调整**：之前 ADR 0001 D2 拆的 4 个 Protocol（QuoteClient / OrderClient / PositionClient / TickerClient）按"业务领域"切。但真实契约层面，期权和互换是**两个聚合 endpoint**（`/financial-orders/operate` + `/swap-order/operate`），不是按"询价/下单/撤单/平仓"切。Protocol 拆分应跟随**真实 endpoint 边界**而不是逻辑分类，否则 Pydantic 模型会与 Java DTO 不一一对应。

业务查询和交易仍按 OptionClient + SwapClient + TickerClient 划分（合并 Quote/Order/Position 到 OptionClient/SwapClient）；消息元数据写回由独立的 MessageClient 承担。
