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
| `new_inquiry` | 新询价 / 新询单 |
| `place_order_from_quote` | 基于报价下单 / 请求下单 / 纠正参数 |
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

## 6. 其他

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

> **重大调整**：之前 ADR 0001 D2 拆的 4 个 Protocol（QuoteClient / OrderClient / PositionClient / TickerClient）按"业务领域"切。但真实契约层面，期权和互换是**两个聚合 endpoint**（`/financial-orders/operate` + `/swap-order/operate`），不是按"询价/下单/撤单/平仓"切。Protocol 拆分应跟随**真实 endpoint 边界**而不是逻辑分类，否则 Pydantic 模型会与 Java DTO 不一一对应。

按 OptionClient + SwapClient + TickerClient 三个 Protocol 划分（合并 Quote/Order/Position 到 OptionClient/SwapClient），与真实 Java 端边界完全对齐，更易维护。
