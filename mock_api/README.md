# GOATS Mock API

模拟 GOATS 对客机器人全部 20 个后端接口，供本地开发和测试使用。

## 启动

```bash
.venv\Scripts\Activate.ps1
uvicorn mock_goats_api.server:app --reload --port 8099
```

## 测试

### 方式一：Python 脚本（一键覆盖全部接口）

```bash
# 1. 先启动 Mock 服务（新终端）
.venv\Scripts\Activate.ps1
uvicorn mock_goats_api.server:app --reload --port 8099

# 2. 再运行测试脚本
python mock_goats_api/test_all_endpoints.py

# 如果改了端口
python mock_goats_api/test_all_endpoints.py --port 8080
```

脚本会自动调用全部 22 个端点（20 个接口 + 1 个错误模拟），输出通过/失败统计。

### 方式二：Apifox

1. **新建项目** → 名称填 `GOATS Mock API`
2. **设置环境变量** → `base_url` = `http://localhost:8099`
3. **全局 Header 预设**（添加到环境或集合级别，避免每个接口重复填）：

```json
{
  "Content-Type": "application/json",
  "agenttype": "WECHAT",
  "agentid": "10955866372569317@tl",
  "agentsubid": "1688856778752437",
  "clientid": "TL_AGENT",
  "clientsecret": "tltest"
}
```

4. **按分类逐个新建接口**，每类一个完整示例如下：

#### 场外期权（以期权询价为例）

| 配置项 | 值 |
|---|---|
| 方法 | `POST` |
| 路径 | `/api/internal/agent/get_option_rfq` |
| Headers | 勾选全局预设 |

Body (JSON)：
```json
下·
```

> 期权其他接口（下单/撤单/平仓等）同样方式，Body 参考 `test_all_endpoints.py`。

#### 收益互换（以互换下单为例）

| 配置项 | 值 |
|---|---|
| 方法 | `POST` |
| 路径 | `/api/internal/agent/trs_order` |
| Headers | 勾选全局预设 |

Body (JSON)：
```json
{
  "transactionType": "US_STOCK",
  "orderType": "BY_QTY",
  "quantity": 200,
  "windCode": "TSLA.O",
  "price": 1,
  "priceType": "LimitOrder",
  "orderDirection": "BUY",
  "shortName": "测试短名"
}
```

#### 交易对手查询（GET + Query 参数）

| 配置项 | 值 |
|---|---|
| 方法 | `GET` |
| 路径 | `/api/internal/agent/getCtptyListByChatRoomId` |
| Headers | 勾选全局预设 |
| Query 参数 | `type` = `TRS` |

#### 投管系统（GET 无参数）

| 配置项 | 值 |
|---|---|
| 方法 | `GET` |
| 路径 | `/api/uniweb/rpa/trs/tradingHoursConfig` |
| Headers | 勾选全局预设 |

#### Dify 大模型 rerank

| 配置项 | 值 |
|---|---|
| 方法 | `POST` |
| 路径 | `/v1/workflows/run` |
| Headers | `Content-Type: application/json`（无需 agenttype 等） |

Body (JSON)：
```json
{
  "inputs": {
    "list": "[{\"windCode\":\"0200.HK\",\"insShtDesc\":\"新濠国际发展\"}]",
    "keyword": "0200.hk"
  },
  "user": "ai-trading-assistant",
  "response_mode": "blocking"
}
```

5. **模拟错误**：在任意接口的 Query 参数栏追加 `_error` = `1`，返回 400 错误

### 方式三：curl

```bash
# 健康检查
curl http://localhost:8099/

# 期权询价
curl -X POST http://localhost:8099/api/internal/agent/get_option_rfq \
  -H "Content-Type: application/json" \
  -d '{"chatType":"json","productType":"EUROPEAN_VANILLA","chatInstrument":"询价","productSubtypeList":[],"fuzzyCodeList":["688472.SH"],"tenor":[],"strike":[],"participateRate":[],"knockInPrice":[],"knockOutPrice":[],"estimateMargin":[]}'

# 模拟错误
curl -X POST "http://localhost:8099/api/internal/agent/trs_order?_error=1"
```

## 接口列表

| # | 方法 | 路径 | 说明 |
|---|---|---|---|
| 1 | POST | `/api/internal/agent/get_option_rfq` | 期权询价查询 |
| 2 | POST | `/api/internal/agent/option_order` | 场外期权下单 |
| 3 | POST | `/api/internal/agent/option_order_status` | 期权下单状态查询 [轮询] |
| 4 | POST | `/api/internal/agent/option_order_result` | 期权下单结果查询 |
| 5 | POST | `/api/internal/agent/option_cancel` | 场外期权撤单 |
| 6 | POST | `/api/internal/agent/option_cancel_result` | 场外期权撤单结果查询 [轮询] |
| 7 | POST | `/api/internal/agent/option/position` | 可平仓合约列表查询 |
| 8 | POST | `/api/internal/agent/option_close_order` | 场外期权平仓 |
| 9 | POST | `/api/internal/agent/option_close_order_query` | 期权平仓订单查询 |
| 10 | POST | `/api/internal/agent/option_close_cancel` | 场外期权平仓撤单 |
| 11 | POST | `/api/internal/agent/option_close_cancel_result` | 场外期权平仓撤单结果查询 [轮询] |
| 12 | POST | `/api/internal/agent/trs_order` | 收益互换下单 |
| 13 | POST | `/api/internal/agent/trs_order_status` | 收益互换下单状态查询 [轮询] |
| 14 | POST | `/api/internal/agent/trs_order_result` | 收益互换下单/撤单结果查询 [轮询] |
| 15 | POST | `/api/internal/agent/trs_cancel` | 收益互换撤单 |
| 16 | POST | `/api/internal/agent/trs_replace` | 收益互换改单 |
| 17 | POST | `/api/internal/agent/trs_replace_status` | 收益互换改单状态查询 [轮询] |
| 18 | GET | `/api/internal/agent/getCtptyListByChatRoomId` | 企微群绑定交易对手查询 |
| 19 | GET | `/api/uniweb/rpa/trs/tradingHoursConfig` | 互换交易时间配置查询 |
| 20 | POST | `/v1/workflows/run` | 大模型 rerank 标的列表 |

## 响应结构

所有接口统一返回：

```json
{
  "errMsg": null,
  "errCode": {"code": 200, "chs": "成功", "eng": "success"},
  "data": ...
}
```

## 模拟错误

任意接口追加 `?_error=1` 查询参数即可返回 400 错误：

```bash
curl -X POST "http://localhost:8099/api/internal/agent/trs_order?_error=1"
```

响应：

```json
{
  "errMsg": "模拟错误",
  "errCode": {"code": 400, "chs": "模拟错误", "eng": "FAIL_REQUEST"},
  "data": null
}
```

## 接口文档

完整请求/响应结构见同目录下 `api_spec.md`。
