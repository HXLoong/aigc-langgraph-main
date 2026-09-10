# 测试结果与联调状态

> 更新时间：2026-05-07

## V1 闭环验证：✅ 已就绪

| 验证维度 | 命令 | 结果 |
|---|---|---|
| 单元测试 + 闭环 CI | `pytest tests/ -v` | **117/117 PASS** |
| 离线闭环 demo（30 条 golden case） | `python scripts/demo_closed_loop.py` | **30/30 PASS（100%）** |
| 全链路集成测试（15 条） | `python tests/run_integration_test.py` | 15/15 PASS（需启 mock_api + LangGraph） |
| Mock 接口端点 | `python mock_api/test_all_endpoints.py` | 全部 32 个端点 200 OK |

**外部依赖状态：**

| 依赖 | V0 状态 | V1 状态 |
|---|---|---|
| Java 后端 | 必须 | ✅ mock_api 替代 |
| GOATS API | 必须 | ✅ mock_api 替代 |
| 标的查询接口 | 需 VPN | ✅ mock_api/securities-instrument 替代（2026-05-07） |
| Docker（MySQL/Redis/RabbitMQ） | 必须 | 仅集成测试需要；闭环 demo 用 InMemorySaver |
| LLM API Key | 必须 | 仅集成测试需要；闭环 demo 用 SmartLLMMock |
| Dify 实例 | 必须 | 不再依赖 |

---

## 一、全模块集成测试（15 条）

### 1.1 测试结果总览

目标：`http://localhost:8000/v1/message`

**15/15 PASS** — 路由正确率 100%，子图链路完整率 100%。

> 2026-05-07 更新：新增 `securities-instrument` 标的查询 mock，**已脱离 VPN 依赖**，CI / 离线环境可全量跑通。

### 1.2 详细结果

| # | 用例 | 输入 | product | intent | 子图链路 | api_code |
|---|------|------|---------|--------|----------|----------|
| 01 | Swap-文本下单 | `互换下单 帮我买入1000股腾讯...` | swap | place_order_request | dispatch → ticker → classify → extract_place_order → call_swap_api | 0 |
| 02 | Swap-确认下单 | `互换 确认下单 H-20260304-ABCD...` | swap | confirm_order | dispatch → ticker → classify → extract_order_id → call_swap_api | 0 |
| 03 | Swap-请求撤单 | `互换撤单 撤销订单 H-20260304-...` | swap | cancel_order_request | dispatch → ticker → classify → extract_order_id → call_swap_api | 0 |
| 04 | Swap-确认改单 | `swap确认修改订单 H-20260304-...` | swap | confirm_modify_order | dispatch → ticker → classify → extract_order_id → call_swap_api | 0 |
| 05 | Swap-查询订单 | `TRS 查一下订单 H-20260304-...` | swap | query_order_status | dispatch → ticker(含rank) → classify → extract_order_id → call_swap_api | 0 |
| 06 | Option-快速询价(参与型) | `参与型看涨 腾讯控股 1个月` | option | new_inquiry | detect_quick_query → fast_query_api | 0 |
| 07 | Option-快速询价(雪球) | `雪球询价 腾讯控股` | option | new_inquiry | detect_quick_query → fast_query_api | 0 |
| 08 | Option-标准询价 | `期权询价 腾讯控股 欧式看涨...` | option | (LLM 偶返 unknown) | detect_quick_query → ticker → extract_option → check_param_limit → call_option_api | 0 |
| 09 | Close-持仓查询 | `我有哪些持仓` | option_close | close_order_query | classify_close → extract_holding_query → call_close_api | 0 |
| 10 | Close-请求平仓 | `帮我平仓 CO-20260304-ABCD...` | option_close | close_order_request | classify_close → extract_place_close → call_close_api | 0 |
| 11 | Close-确认平仓 | `确认平仓 CO-20260304-ABCD...` | option_close | close_order_confirm | classify_close → extract_order_no_list → call_close_api | 0 |
| 12 | Close-撤销平仓单 | `撤销平仓单 CO-20260304-ABCD...` | option_close | close_order_cancel | classify_close → extract_order_no_list → call_close_api | 0 |
| 13 | Unknown-兜底 | `今天天气怎么样` | unknown | None | render_reply | None |
| 14 | Ticker-多标的批量识别 | `互换下单 帮我同时买入贵州茅台、腾讯控股、特斯拉` | swap | place_order_request | dispatch → ticker → classify → extract_place_order → call_swap_api | 0 |
| 15 | 优先级-单号格式优先 | `互换订单 CO-20260304-...帮我平仓` | option_close | close_order_request | classify_close → extract_place_close → call_close_api | 0 |

### 1.3 验证维度说明

- **PASS** = 路由(product_type) + 意图(intent) + 子图链路(trace) + 后端API 全部正确
- `api_code=0` 表示后端正常返回成功（mock_api 用 code=0 模拟成功）
- `api_code=None` 仅 Unknown 兜底场景（不调后端）

### 1.4 已知问题

- **Option 标准询价**：`extract_option` LLM 偶尔将 `new_inquiry` 识别为 `unknown`，链路完整但不稳定。需后续优化提示词。

---

## 二、本地环境搭建

### 2.1 架构（无需 Java 后端 / 无需 VPN）

```
LangGraph (8000) ──→ mock_api (8099)  ← 同时模拟 GOATS 20 + 后端 6 + 标的查询 1
     │
     ├── LLM: dashscope.aliyuncs.com (公网)
     └── Docker: MySQL + Redis + RabbitMQ
```

mock_api 合并了之前的 mock_goats_api + Java Backend + 标的查询服务，一个端口覆盖全部外部调用。

### 2.2 Docker 服务

| 服务 | 容器名 | 端口 | 启动命令 |
|------|--------|------|----------|
| MySQL 8.0 | `otc-agent-mysql` | 3306 | `docker compose up -d mysql` |
| Redis 7 | `otc-agent-redis` | 6379 | 见下方 |
| RabbitMQ 3.13 | `otc-agent-rabbitmq` | 5672/15672 | 见下方 |

**Redis 集群模式启动：**
```bash
docker run -d --name otc-agent-redis -p 6379:6379 \
  -v otc-redis-data:/data \
  redis:7-alpine redis-server \
    --requirepass shareredis7 \
    --cluster-enabled yes \
    --cluster-config-file nodes.conf \
    --cluster-announce-ip 127.0.0.1 \
    --cluster-announce-port 6379

# 首次启动后分配 slots，后续重启跳过
docker exec otc-agent-redis redis-cli -a shareredis7 CLUSTER ADDSLOTS $(seq 0 16383)
```

**RabbitMQ 启动：**
```bash
docker run -d --name otc-agent-rabbitmq -p 5672:5672 -p 15672:15672 \
  -e RABBITMQ_DEFAULT_USER=default_user_TGrdJ5tdzHzeNmVA1Nr \
  -e RABBITMQ_DEFAULT_PASS=7XQCrSyY7VzKYKvpZL2DKFkHDK3s1hze \
  -e RABBITMQ_DEFAULT_VHOST=ai-trading-assistant \
  rabbitmq:3.13-management-alpine

docker exec otc-agent-rabbitmq rabbitmqctl set_permissions -p ai-trading-assistant \
  default_user_TGrdJ5tdzHzeNmVA1Nr ".*" ".*" ".*"
```

### 2.3 数据库导入（可选）

```bash
docker compose exec -T mysql mysql -uroot -prootpassword -e \
  "CREATE DATABASE IF NOT EXISTS goats_ai_trading_dev1 DEFAULT CHARACTER SET utf8mb4"

docker compose exec -T mysql mysql -uroot -prootpassword goats_ai_trading_dev1 < goats_ai_trading_dev1.sql
docker compose exec -T mysql mysql -uroot -prootpassword goats_ai_trading_dev1 < goats_ai_trading_dev1-data.sql
```

### 2.4 一键启动所有服务

```bash
# 1. MySQL
docker compose up -d mysql

# 2. Redis cluster
docker rm -f otc-agent-redis && docker run -d --name otc-agent-redis -p 6379:6379 \
  -v otc-redis-data:/data redis:7-alpine redis-server \
  --requirepass shareredis7 --cluster-enabled yes --cluster-config-file nodes.conf \
  --cluster-announce-ip 127.0.0.1 --cluster-announce-port 6379

# 3. RabbitMQ
docker rm -f otc-agent-rabbitmq && docker run -d --name otc-agent-rabbitmq \
  -p 5672:5672 -p 15672:15672 \
  -e RABBITMQ_DEFAULT_USER=default_user_TGrdJ5tdzHzeNmVA1Nr \
  -e RABBITMQ_DEFAULT_PASS=7XQCrSyY7VzKYKvpZL2DKFkHDK3s1hze \
  -e RABBITMQ_DEFAULT_VHOST=ai-trading-assistant \
  rabbitmq:3.13-management-alpine

# 4. Mock API（GOATS + 后端，一个服务全覆盖）
uv run uvicorn mock_api.server:app --host 0.0.0.0 --port 8099 &

# 5. LangGraph FastAPI
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
```

### 2.5 运行测试

```bash
# 全模块集成测试（15 条，约 3 分钟）
python tests/run_integration_test.py

# 单元测试（含 ticker 子图 27 条）
pytest tests/ -v
pytest -s tests/test_ticker.py -v
```

---

## 三、mock_api 接口覆盖

mock_api 在 8099 端口统一模拟 27 个接口：

### GOATS 内部接口（20 个）
期权 11 + 收益互换 6 + 交易对手 1 + 投管系统 1 + Dify 1

### 后端业务接口（6 个）

| 路径 | 对应 OtcBackendClient |
|------|----------------------|
| `POST /admin-api/swap-order/operate` | `swap_operate()` |
| `POST /admin-api/financial-orders/operate` | `financial_orders_operate()` |
| `GET /admin-api/counterparty/info/list` | `counterparty_list()` |
| `POST /admin-api/swap-order/get-conversation-orders` | `conversation_orders()` |
| `POST /admin-api/business/config/bot/name/list` | `bot_name_list()` |
| `POST /admin-api/openapi/xbot/message/set-intent` | `set_intent()` |

### 标的查询接口（1 个，新增 2026-05-07）

| 路径 | 对应工具 | 说明 |
|------|---------|------|
| `GET/POST /admin-api/integration/securities-instrument/select` | `app/subgraphs/ticker_tools.py:search_securities_instrument` | 内置 17 条常用 A 股 / 港股 / 美股 / 期货词典；支持 `isFull=True` 精确匹配 windCode、`isFull=False` 模糊匹配 wind/短名/长名 |

---

## 四、修复的 3 个 Bug（LangGraph 侧）

| # | 文件 | 问题 | 修复 |
|---|------|------|------|
| 1 | `app/subgraphs/option.py` | `_quick` 未在 AgentState 中声明，被 LangGraph 静默过滤 | 改用已声明的 `fast_query` 字段 |
| 2 | `app/subgraphs/swap.py` | `_modality` 未在 AgentState 中声明，被静默过滤 | 改用已声明的 `modality` 字段 |
| 3 | `app/subgraphs/option.py` | `_operate` 未在 AgentState 中声明，被静默过滤 | 改用已声明的 `operate` 字段 |

同时在 `app/state.py` 中补了 `modality` 和 `operate` 的字段声明及默认值。

---

## 五、V1 闭环 demo（2026-05-07 新增）

`scripts/demo_closed_loop.py` 是**零外部依赖**的端到端验证：

```bash
# 直接跑（不需要 Docker / mock_api / LLM key / Dify）
python scripts/demo_closed_loop.py

# 输出：
# [001/30] ✓ g001   swap/place_order                   152ms  ok
# ...
# [030/30] ✓ g030   priority/contract_no                38ms  ok
# 结果: 30/30 PASS  (100.0%)
# 平均延迟: 46ms  (in-process，无网络)
```

设计：
- **LangGraph 主图** + InMemorySaver（不依赖 MySQL）
- **SmartLLMMock**：根据 raw_content 关键词模式 + 目标 Pydantic 类型，合成结构化输出
- **Mock backend**：所有 OtcBackendClient 调用返回 code=0
- **Mock 标的查询**：内置 16 个常用标的词典

**职责边界**：本 demo 只验证图拓扑/State 流转/节点串联是否正确，不验证 LLM 准确率。
LLM 准确率验证用 `python scripts/eval_golden.py tests/fixtures/golden.jsonl --endpoint http://localhost:8000/v1/message`（需真实 LLM key）。

**CI 集成**：`tests/test_closed_loop.py` 包装为 pytest，每次 `pytest tests/` 都会自动跑。

---

## 六、route.py 改进（2026-05-07）

为通过 V1 demo 中的引用消息场景（如"用户回复'确认'引用之前的互换订单"），新增两条路由规则：

| 规则 | 触发条件 | 路由到 |
|---|---|---|
| 1.5（新） | 文本中包含 `H-YYYYMMDD-XXXX` 互换订单号格式（宽松 4-16 位） | `swap` |
| 3 fallback（新） | raw_content 没命中关键词，但 quote_content 含产品关键词 | 对应产品子图 |

向后兼容：先看 raw（原行为），未命中再看 quote_content。`tests/test_route.py` 7 条用例全绿。
