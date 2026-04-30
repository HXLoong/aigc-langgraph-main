# GOATS Mock API

模拟 GOATS 对客机器人全部 20 个后端接口，供本地开发和测试使用。

## 启动

```bash
uvicorn mock_goats_api.server:app --reload --port 8099
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
