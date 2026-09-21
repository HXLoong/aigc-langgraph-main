# GOATS 期权持仓 Mock

在仓库根目录运行（使用项目现有 FastAPI / Uvicorn 依赖）：

```bash
.venv/bin/python scripts/goats_api_mock/server.py --port 20000
```

Java 管理页面中，仅将 `GOATS_OPTION_CLOSING_OUT_CONTRACT_QUERY` 的地址配置为：

```text
http://127.0.0.1:20000/api/internal/agent/option/position
```

该地址适用于 Java 与 mock 运行在同一主机的情况。继续使用现有 runner 和 JSONL
测试流程；runner 启动会显示上述提示，mock 需另开终端运行。

`option_positions.json` 保存用户提供的完整 GOATS 响应，包括原顺序的 12 条持仓。
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
- 无条件返回 12 条，`windCode=000155.SZ` 返回 3 条，
  `contractTypeList=["EUROPEAN_VANILLA"]` 返回 3 条。

离线验证：

```bash
USE_MYSQL_CHECKPOINTER=false REQUEST_IDEMPOTENCY=false ENABLE_LANGFUSE=false \
  .venv/bin/python -m pytest tests/test_goats_api_mock.py \
  scripts/ai_test_langgraph/test_automation_runner_server.py -q
```
