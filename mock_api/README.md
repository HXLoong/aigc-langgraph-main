# GOATS + OTC Backend Mock API

模拟 app 直接调用的两组外部接口，供本地调试和黄金集评测使用，无需 VPN / 真实后端。这不是两种 mock 验收模式，也不核验 Java 内部下游：

1. **GOATS 外部接口**（21 个）— 模拟 GOATS 对客机器人 `/api/internal/agent/*` + `/api/uniweb/...`。
   LangGraph 实际只调用 DSL v2 fast_query 前置分支的 2 个端点（`option_rfq_instrument_parser` /
   `instruction/query`，双前缀挂载，带不带 `/api` 都可达）；其余下划线路径（如 `trs_order`）是历史示意，
   与真实 GOATS 路径（`trs/order`）不同，当前没有调用方
2. **OTC Java 后端接口**（10 个）— 模拟 yudao 后端 `/admin-api/*`，按真实 Java DTO 校验入参 + 按 type 分发业务行为

> 定位：黄金集评测的本地 mock 后端；不作为独立测试对象，也不替代真后端业务回归。业务集验收仍以真 Java 后端为准（ADR 0030 D3）。

## 让 LangGraph 应用指向 mock（.env 配置）

```bash
OTC_API_BASE_URL=http://127.0.0.1:8099
GOATS_BASE_URL=http://127.0.0.1:8099
GOATS_CLIENT_ID=mock-client-id
GOATS_CLIENT_SECRET=mock-client-secret
GOATS_EXTAPP_SALT=mock-salt
```

LLM 仍走配置的真实模型，mock 只替代外部后端。`DRY_RUN_BACKEND=true` 会拦截写类 Client 调用，不能用其回复作为黄金集业务通过证据。

本项目只有 app 核心测试与黄金集评测两类验证，见 [`docs/testing/README.md`](../docs/testing/README.md)。

## 启动

```bash
uvicorn mock_api.server:app --reload --port 8099
```

启动后访问 `http://127.0.0.1:8099/` 查看完整路由清单。

> **重要**：在 macOS 下 `localhost` 优先解析为 `::1`（IPv6），但 uvicorn 默认只 bind 127.0.0.1（IPv4），httpx 调 localhost 会拿到 503。**测试 / 客户端务必用 `127.0.0.1`**。

## 与黄金集评测的关系

mock_api 与 app 均需预先启动，Harness 固定请求 `127.0.0.1:8000`，不管理服务生命周期。mock 的固定 stub 只提供链路执行所需响应；黄金用例仍由本地评分器按 `expected` 判定，不通过 mock 自测或 mock 返回值替代业务断言。

## 后端接口清单

`/admin-api/*` 全部按真实 `*ReqVO.java` Pydantic 校验入参，按 `type` 字段分发到 7（互换）/16（期权）个意图渲染函数：

| 路径 | 方法 | 说明 | 来源 |
|---|---|---|---|
| `/admin-api/swap-order/operate` | POST | 互换操作聚合（7 个意图）| `SwapOrderOpenApiController.operate` |
| `/admin-api/swap-order/get` | GET | 互换订单详情 | `SwapOrderOpenApiController.get` |
| `/admin-api/swap-order/get-conversation-orders` | POST | 会话历史订单 | `SwapOrderOpenApiController.getConversationOrders` |
| `/admin-api/financial-orders/operate` | POST | 期权/平仓操作聚合（16 个意图）| `FinancialOrdersOpenApiController.operate` |
| `/admin-api/financial-orders/query-close-orders` | POST | 批量查询平仓订单 | `FinancialOrdersOpenApiController.queryCloseOrders` |
| `/admin-api/counterparty/info/list` | GET | 交易对手列表 | `CounterpartyInfoController.list` |
| `/admin-api/counterparty/info/instrument-inference-prompt` | GET | 推断 prompt 配置 | `CounterpartyInfoController.getInstrumentInferencePrompt` |
| `/admin-api/business/config/bot/name/list` | POST | Bot 名称（data 是 JSON 字符串）| 业务配置 |
| `/admin-api/openapi/xbot/message/set-intent` | POST | 意图审计写入（无返回）| 审计 |

## type 字段分发

### 互换 7 个意图（`SwapEnum.SwapIntentionType`）

```
place_order_request    → 下单 / 改单（靠 orderList[i].orderId 区分）
confirm_order          → 确认下单
cancel_order_request   → 撤单请求
confirm_cancel_order   → 确认撤单
confirm_modify_order   → 确认改单
query_order_status     → 订单状态查询
unknown_intent         → 未识别兜底
```

### 期权 16 个意图（`StockEnum.stockOptionIntentionType`）

```
new_inquiry                  → 询价卡（含交易对手列表）
place_order_from_quote       → 下单确认卡
request_modify_order         → 改单确认卡
confirm_order                → 确认下单
cancel_order_request / request_cancel_order → 撤单请求
confirm_cancel_order         → 确认撤单
confirm_modify_order         → 确认改单
query_order_status           → 订单状态查询
close_order_query            → 持仓详情卡（多条）
close_order_request          → 平仓申请卡
close_order_confirm          → 平仓确认下单
close_order_cancel_request   → 平仓撤单请求
close_order_cancel_confirm   → 平仓确认撤单
close_order_order_query      → 平仓订单查询
unknown_intent               → 未识别兜底
```

## 入参校验

所有 `/admin-api/*` 接口按真实 Java `@NotBlank @NotNull @Valid` 严格校验：

```bash
# 缺 messageId / rawContent → 422
curl -X POST http://127.0.0.1:8099/admin-api/swap-order/operate \
  -H "Content-Type: application/json" \
  -d '{"type":"place_order_request"}'
```

## 标的词典

`mock_api/backend/fixtures.py:SECURITIES_DICT` 包含 27 条覆盖：
- A 股 14 条（茅台、五粮液、招商银行、宁德时代、川能动力 等）
- 港股 7 条（腾讯、阿里、新濠、美图、六福、智谱 等）
- 美股 4 条（苹果、特斯拉、英伟达、腾讯音乐）
- 期货 2 条（CLN26.NYM, IF2607.CFE）

## 持仓数据

`POSITIONS` 5 条（与 `tests/datasets/biz/` 常用 `OPT-LYAFT…` `OPT-SZZSCF…` case 对齐），以 `mock_api/backend/fixtures.py` 为准，覆盖：
- 贵州茅台欧式看涨 × 1（`OPT-AAAA1`）
- 川能动力欧式看涨 × 3
- 蓝帆医疗雪球 × 1

## 错误模拟

任何接口加 `?_error=1` 强制返回 GOATS 风格 400：

```bash
curl http://127.0.0.1:8099/api/internal/agent/trs_order?_error=1
# {"errMsg":"模拟错误","errCode":{"code":400,...},"data":null}
```

## 文件结构

```
mock_api/
├── server.py              # FastAPI app + GOATS 接口（21 个）+ 挂载 backend router
├── backend/
│   ├── __init__.py        # 暴露 router
│   ├── schemas.py         # Pydantic ReqVO/RespVO + 共用枚举
│   ├── fixtures.py        # 静态测试数据（标的、持仓、交易对手、订单序列）
│   ├── swap.py            # /admin-api/swap-order/* 路由
│   ├── financial.py       # /admin-api/financial-orders/* 路由
│   ├── ticker.py          # /admin-api/integration/* + /admin-api/counterparty/* 路由
│   └── misc.py            # bot/name/list + set-intent

└── README.md              # 本文件
```

## 与 LangGraph 的对接

按上文配置将 app 指向 8099 后启动或重启，分别运行 mock_api 与 app，再执行黄金集：

```bash
python -m harness run --group intent --backend mock
python -m harness run --file tests/datasets/biz/swap_prod.jsonl --backend mock
```

业务集支持 mock 执行，但 stub 不保证满足真后端卡片期望，不能替代 Java 验收。
评测输入缺省使用 V2，显式入口字段按原值透传。接口 OpenAPI 可用 `app.openapi()` 现场生成。
