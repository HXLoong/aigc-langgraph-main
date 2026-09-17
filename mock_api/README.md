# GOATS + OTC Backend Mock API

模拟两套接口供本地开发与集成测试，无需 VPN / 真实后端：

1. **GOATS 外部接口**（22 个）— 模拟 GOATS 对客机器人 `/api/internal/agent/*` + `/api/uniweb/...` + `/v1/workflows/run`；
   含 DSL v2 fast_query 前置分支的 2 个新端点（`option_rfq_instrument_parser` / `instruction/query`，
   双前缀挂载，带不带 `/api` 都可达）
2. **OTC Java 后端接口**（10 个）— 模拟 yudao 后端 `/admin-api/*`，按真实 Java DTO 校验入参 + 按 type 分发业务行为

> 2026-08-29 恢复说明：本模块曾于 M3.2（commit `4ac9f0b`）随"切真后端"删除，现按需恢复为
> **本地开发工具**（44 条集成测试直接通过，Client 契约无漂移 + 补齐 DSL v2 新端点）。
> 它不参与 CI 的真后端 golden 回归；E3.x 退出门仍以真后端为准。

## 让 LangGraph 应用指向 mock（.env 配置）

```bash
OTC_API_BASE_URL=http://127.0.0.1:8099
GOATS_BASE_URL=http://127.0.0.1:8099
GOATS_CLIENT_ID=mock-client-id
GOATS_CLIENT_SECRET=mock-client-secret
GOATS_EXTAPP_SALT=mock-salt
SECURITIES_INSTRUMENT_URL=http://127.0.0.1:8099/admin-api/integration/securities-instrument/select
```

LLM 仍走真实 DeepSeek（mock 只替后端）；不想产生任何真实副作用时叠加 `DRY_RUN_BACKEND=true`。

完整测试分层（mock → golden 评估 → 真后端切换）见 [`docs/testing/README.md`](../docs/testing/README.md)。

## 启动

```bash
uvicorn mock_api.server:app --reload --port 8099
```

启动后访问 `http://127.0.0.1:8099/` 查看完整路由清单。

> **重要**：在 macOS 下 `localhost` 优先解析为 `::1`（IPv6），但 uvicorn 默认只 bind 127.0.0.1（IPv4），httpx 调 localhost 会拿到 503。**测试 / 客户端务必用 `127.0.0.1`**。

## 测试方式

### 方式一：pytest（推荐，无需启动 server）

```bash
pytest mock_api/test_backend_api.py -v
```

45 条用例，覆盖 10 个后端接口的全部 type 分发分支 + 入参校验，使用 `httpx.ASGITransport` 内存调用，零网络开销。

### 方式二：脚本（需要 server 在跑）

```bash
# 终端 1
uvicorn mock_api.server:app --port 8099

# 终端 2
python mock_api/test_all_endpoints.py            # 默认 127.0.0.1:8099
python mock_api/test_all_endpoints.py --port 8080 --host 192.168.1.100
```

24 条 GOATS 端到端用例，含错误模拟（`?_error=1`）。

## 后端接口清单

`/admin-api/*` 全部按真实 `*ReqVO.java` Pydantic 校验入参，按 `type` 字段分发到 7（互换）/16（期权）个意图渲染函数：

| 路径 | 方法 | 说明 | 来源 |
|---|---|---|---|
| `/admin-api/swap-order/operate` | POST | 互换操作聚合（7 个意图）| `SwapOrderOpenApiController.operate` |
| `/admin-api/swap-order/get` | GET | 互换订单详情 | `SwapOrderOpenApiController.get` |
| `/admin-api/swap-order/get-conversation-orders` | POST | 会话历史订单 | `SwapOrderOpenApiController.getConversationOrders` |
| `/admin-api/financial-orders/operate` | POST | 期权/平仓操作聚合（16 个意图）| `FinancialOrdersOpenApiController.operate` |
| `/admin-api/financial-orders/query-close-orders` | POST | 批量查询平仓订单 | `FinancialOrdersOpenApiController.queryCloseOrders` |
| `/admin-api/integration/securities-instrument/select` | GET / POST | 标的查询（关键词匹配 + relevanceScore）| `SecuritiesInstrumentController.selectSecuritiesInstrumentPage` |
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

`POSITIONS` 4 条（与 `tests/fixtures/categories/` 常用 `OPT-LYAFT…` `OPT-SZZSCF…` case 对齐），覆盖：
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
├── server.py              # FastAPI app + GOATS 接口（20 个）+ 挂载 backend router
├── backend/
│   ├── __init__.py        # 暴露 router
│   ├── schemas.py         # Pydantic ReqVO/RespVO + 共用枚举
│   ├── fixtures.py        # 静态测试数据（标的、持仓、交易对手、订单序列）
│   ├── swap.py            # /admin-api/swap-order/* 路由
│   ├── financial.py       # /admin-api/financial-orders/* 路由
│   ├── ticker.py          # /admin-api/integration/* + /admin-api/counterparty/* 路由
│   └── misc.py            # bot/name/list + set-intent
├── test_backend_api.py    # pytest 后端 mock 完整测试（45 条，ASGITransport）
├── test_all_endpoints.py  # 端到端脚本（24 条 GOATS 接口，需启 server）
├── api_spec.md            # 接口完整字段说明
├── openapi.json           # OpenAPI 3.0 schema
└── README.md              # 本文件
```

## 与 LangGraph 的对接

`app/tools/swap_client.py` / `option_client.py` / `ticker_client.py` 默认 `base_url=http://localhost:8099`，启动 mock 后即可端到端跑：

```bash
uvicorn mock_api.server:app --port 8099 &
python -m harness run                  # 跑 golden set 验证
```
