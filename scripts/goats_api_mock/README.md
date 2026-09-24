# GOATS Mock（期权持仓、开仓、平仓、撤单及互换）

在仓库根目录运行（使用项目现有 FastAPI / Uvicorn 依赖）：

```bash
python scripts/goats_api_mock/server.py --port 20000
```

启动和停止提示使用中文，并统一标注“GOATS 期权 Mock 服务”；启动日志会显示数据文件、
持仓条数、实际监听地址及 Ctrl+C 停止提示。加载失败时保留错误原因和异常堆栈。

Java 管理页面中，将以下 5 个接口配置为本地 mock：

| Java 配置项 | 方法 | 地址 |
| --- | --- | --- |
| `GOATS_OPTION_CLOSING_OUT_CONTRACT_QUERY` | POST | `http://127.0.0.1:20000/api/internal/agent/option/position` |
| `GOATS_OPTION_CLOSING_OUT_PLACE_AN_ORDER` | POST | `http://127.0.0.1:20000/api/internal/agent/option/order/close` |
| `GOATS_OPTION_CLOSING_OUT_ORDER_QUERY` | POST | `http://127.0.0.1:20000/api/internal/agent/option/order/close/query` |
| `GOATS_OPTION_CLOSING_OUT_ORDER_CANCEL` | POST | `http://127.0.0.1:20000/api/internal/agent/option/order/close/withdraw` |
| `GOATS_OPTION_CLOSING_OUT_ORDER_CANCEL_QUERY` | GET | `http://127.0.0.1:20000/api/internal/agent/option/order/close/withdrawResult` |

开仓完整流程另外需要以下 5 个接口（Java 运行版本须支持接口配置使用完整 URL）：

| Java 配置项 | 方法 | 地址 |
| --- | --- | --- |
| `GOATS_AGENT_OPTION_ORDER` | POST | `http://127.0.0.1:20000/api/internal/agent/option/order` |
| `GOATS_AGENT_ORDER_STATUS` | GET | `http://127.0.0.1:20000/api/internal/agent/option/order/status` |
| `GOATS_AGENT_ORDER_QUERY` | POST | `http://127.0.0.1:20000/api/internal/agent/option/order/query` |
| `GOATS_AGENT_CANCEL_ORDER` | POST | `http://127.0.0.1:20000/api/internal/agent/option/order/withdraw` |
| `GOATS_AGENT_CANCEL_ORDER_RESULT` | GET | `http://127.0.0.1:20000/api/internal/agent/option/order/withdrawResult` |

该地址适用于 Java 与 mock 运行在同一主机的情况。继续使用现有 runner 和 JSONL
测试流程；runner 启动会显示上述提示，mock 需另开终端运行。

### 兼容直接拼接基础地址的 Java 调用

部分 Java 调用仍直接拼接 `goats.api.base-url + request_url`。此时基础地址非空、接口
配置又是完整 URL，会产生重复拼接，开仓或互换请求无法到达 Mock。无需修改 Java：
在本地启动覆盖中将 `goats.api.base-url` 设为空字符串，并将 GOATS 系统各接口配置为
完整 URL。模拟的交易、持仓和状态接口指向本机；继续使用真实测试对手/询价时，相应
读取接口指向原测试服务。不能只把部分接口改为完整 URL、同时保留非空基础地址。

本地测试建议使用独立数据库和 Redis database，避免混入旧的真实订单与接口缓存。
切换配置后需清理该专用 Redis database 的接口缓存，并重启本地 Java。报告分别记录
Java 和 GOATS 的模式：真实 Java + Mock GOATS 通过，不等于真实 GOATS 已受理交易。

## 互换模拟接口

| Java 配置项 | 方法 | 地址 |
| --- | --- | --- |
| `GOATS_AGENT_SWAP_ORDER` | POST | `http://127.0.0.1:20000/api/internal/agent/trs/order` |
| `GOATS_AGENT_SWAP_ORDER_STATUS` | POST | `http://127.0.0.1:20000/api/internal/agent/trs/order/status` |
| `GOATS_AGENT_SWAP_ORDER_QUERY` | POST | `http://127.0.0.1:20000/api/internal/agent/trs/order/query` |
| `GOATS_AGENT_SWAP_ORDER_WITHDRAW` | POST | `http://127.0.0.1:20000/api/internal/agent/trs/order/withdraw` |

提交支持 Java 的数量/名义金额、标的原文、品种、方向和价格字段，返回 Integer 范围内的
模拟 `keyOrderId` 与 `result=true, async=true`。状态查询接收 `[{"keyOrderId": ...}]`，
返回审核完成及同一模拟订单标识。结果查询接受空 body（当前 Java 的调用方式）或
`keyOrderIdList`，仅返回当前群/用户的模拟记录。

撤单接收 `{"orderList": [...]}`，状态从 `NEW` 变为 `CANCELED`；重复撤单返回同一结果。
未知或跨群/用户的编号被拒绝，缺 `agentsubid` 的群级撤单同样被拒绝，混合无效编号的批次
不会部分撤单。成交数量始终为 0；撤单后 `withdrawQty` 取原委托数量，金额单没有委托股数，
`withdrawQty` 与 `quantity` 同为 `null`（Mock 不把金额换算为股数），金额口径的剩余/撤单量
须在真实 GOATS 上核对。不模拟真实成交、权限、额度、交易时段或改单。需要本地 `swapOrderJob` 正常轮询，才能
验证 Java 的状态落库与终态查询，不能只凭 Mock 接口返回成功判定闭环通过。

`option_positions.json` 基于用户提供的完整 GOATS 响应，原 12 条持仓保持原顺序，
末尾追加一条供平仓数据集使用的测试合约 `OPT-AAAA1`，当前共 13 条。
该合约复制川能动力欧式期权字段，使用独立测试标识 `9000000001`，不代表 GOATS 真实合约。
`OPT-SZZSCF20260001` 的剩余本金、质押本金及可平仓本金调整为 100 万，适配
`case-032` 的全平预期；初始本金仍保留为 1000 万。

Java 展示时按合约编号排序：第一笔为 `OPT-AAAA1`，第二笔为 `OPT-LYAFT20260001`，
第三笔为 `OPT-SZZSCF20260001`，对应平仓集中的合约和序号引用。
服务在启动时加载文件，修改后需重启；文件缺失、JSON 损坏或持仓查询字段格式错误
会明确报错并停止启动。所有测试身份共用这份数据，查询不修改持仓。

调用需要请求头 `agentid`（群标识），`agentsubid`（用户标识）可选：

```bash
curl http://127.0.0.1:20000/api/internal/agent/option/position \
  -H 'Content-Type: application/json' \
  -H 'agentid: test-room@tl' \
  -d '{"filter":{"windCode":"000155.SZ","allowCloseOut":"true"},"pageNum":1,"pageSize":0}'
```

响应保持 `errMsg / errCode / data.queryResults` 结构，记录的全部字段原样保留。

- `filter` 支持 `windCode`、`insFamilyList`、`contractTypeList`、`contractSubTypeList`、
  `allowCloseOut`。前四项按原始代码或枚举值精确匹配，列表内任一项匹配即可，各条件取交集。
- 缺省、`null`、空列表、空标的代码不限制查询；`allowCloseOut=true` 或 `"true"`
  仅返回可平仓记录，`false` / `"false"` / 空值不限制。
- Java 当前传入 `pageNum=1, pageSize=0`，返回全部匹配项。`total` 是匹配总数，
  响应 `pageSize` 是本次返回的记录数，无匹配时两者均为 0。正数 `pageSize` 按页返回。
- 无条件返回 13 条，`windCode=000155.SZ` 返回 4 条，
  `contractTypeList=["EUROPEAN_VANILLA"]` 返回 4 条。

## 模拟交易

开仓下单返回字符串申请编号；`status?orderId=...` 返回审核完成和 Java Integer 范围内的
`keyStockOrderId`。订单查询使用 `trdGoatsOptionOrder / trdGoatsOptionStructure` 结构，
初始状态为 `TOTRADE_PENDING`。撤单受理后为 `PENDING_CANCEL`，查询撤单结果时返回
`completed=true, withdrawResult=SUCCESS`，并变更为 `CANCELLED`（开仓契约为两个 L）。
开仓 mock 仅保留请求中的询价编号，不校验真实 RFQ，也不生成实际成交。

平仓请求使用 Java 当前的 `contractCode / notionalDelta / algoType / price / povRatio /
algoStartTime / algoEndTime`，成功返回数值 `keyStockOrderId`。查询支持 `filter.tradeDate`、
`contractCode`、`keyStockOrderId` 及分页，条目按 Java `GoatsCloseOrderItemDTO` 提供。

新订单为 `OTC_VERIFYING`，成交名义本金为 0；撤单后为 `CANCELED`。撤单传
`keyStockOrderId`，返回 `stockOrderCode`；重复撤单返回同一回执。
`GET .../withdrawResult?stockOrderCode=...` 返回 `completed=true, withdrawResult=SUCCESS`。
不存在的合约/订单/回执、超过可平本金等返回 GOATS 失败包装，不伪造成功。

订单在内存中按群标识隔离，提供 `agentsubid` 时再按用户过滤；不传用户标识可查询本群
模拟订单。撤单是写操作，期权开仓、平仓与互换都要求群和用户与下单时一致，缺
`agentsubid` 的撤单一律拒绝。重启服务清空模拟订单，固定持仓不变。为便于独立用例重复回归，每个平仓请求
创建独立模拟订单，不扣减持仓，不模拟成交、额度、交易时段或真实 GOATS 的活跃单限制。
这套服务仅验证本地调用及状态流转，模拟回执不代表真实交易已受理。

新增 `case-029-lifecycle`、`case-034-lifecycle` 分别覆盖开仓/平仓：准备订单、最终确认、
申请撤单、确认撤单、查询本次订单的“已撤单”终态。平仓用市价，避免依赖 TWAP 时间窗口；
原 `case-034` 的 14:30–14:50 用例保持不变。
Java 的 `optionOrderJob`、`optionCloseOrderJob`、`optionCloseCancelOrderJob` 必须在测试环境
正常运行，否则 mock 成功回执不会自动更新 Java 本地订单状态，不能判定整条链路通过。

用例在异步审核/撤单后的下一轮配置 `wait_before_seconds: 65`（适配每分钟轮询），
它与命令行轮次间隔取较大值；慢环境可以调整到更长时间，上限 300 秒。
`{{previous_order_id}}` 从上一轮真实回复中提取唯一 Q-/CO- 订单号用于查询，缺失或多个
订单号会明确失败，不回退到历史订单。两个测试入口均支持这些字段。

```bash
python -m scripts.local_eval --base-url http://127.0.0.1:8201 \
  --data tests/fixtures/categories --case case-029-lifecycle --case case-034-lifecycle \
  --concurrency 1 --turn-interval 10 --out tmp/option-lifecycle
```

离线验证：

```bash
USE_MYSQL_CHECKPOINTER=false REQUEST_IDEMPOTENCY=false ENABLE_LANGFUSE=false \
  .venv/bin/python -m pytest tests/scripts/test_goats_api_mock.py \
  tests/scripts/test_goats_api_mock_trading.py tests/scripts/test_goats_api_mock_swap.py \
  tests/test_goats_api_mock_open.py tests/test_option_lifecycle_cases.py -q
```
