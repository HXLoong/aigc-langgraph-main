# 按名称执行 LangGraph 节点

`POST /v1/nodes/run` 开放 65 个现役节点，命名空间为 `main`、`option`、`swap`、`option_close`、`ticker`。注册表是 `app/node_execution/registry.py`；接口随现有 `app.main:app` 启动。

## 请求与响应

```json
{
  "product": "option",
  "node": "option_intent",
  "state": {
    "raw_text": "期权询价 腾讯控股 1个月",
    "quote_content": "",
    "history_messages": []
  }
}
```

响应包含 `product`、`node`、`output`。`output` 是目标节点实际返回的更新，可能为空对象；不会自动执行 render、persist 或上游节点。节点返回与输入相同的值仍保留，Pydantic 对象按现有别名序列化，`Overwrite` 展开为承载值，清空用的 `null` 保留。

| 状态 | 条件 | 响应 |
| --- | --- | --- |
| 200 | 节点正常返回，且输出无非空 `error` | 完整 `output`；后端业务拒绝也按节点原有输出透传 |
| 404 | 节点未注册或命名空间不匹配 | `product`、`node`、`detail` |
| 422 | 请求类型、State 类型、未知字段或必需上下文错误 | `detail` 指出错误字段；节点未执行 |
| 500 | 节点返回非空 `error`，包括普通 IO 重试耗尽 | 完整 `output`，含原有错误与 trace |
| 500 | 节点抛出未转换异常 | `product`、`node`、独立 `error: {type, message}`；没有 `output` |

`product` 仅用于查目录，不会写入 `state.product_type`。`START`、`END`、条件路由、辅助函数与内部错误处理器不能按名称调用。目录中的复合子图可以执行，保持其现有输出 schema；执行器不收集或额外拼接内部阶段结果。

## State 与执行语义

输入沿用现有 `AgentState`、`InquiryState`、`PlaceCloseState`、`TickerState`、`OrgItemInput`。入口派生严格校验，拒绝字符串数字、字符串布尔值、未知 State/模型字段。`history_messages`、`tickers`、`trace`、`error` 转成现有模型的兼容实例。原契约中的 `dict[str, Any]` 保留开放字典语义，业务参数继续由节点原有模型校验。

省略的可选字段保持省略，不补业务上下文。节点目录列明额外必需字段；其余字段仍有原来的可选值和默认行为。空输入不等于有效业务请求，例如提供 `input_files: []` 可以通过字段校验，但图片节点会按原逻辑返回错误。

每个注册项预编译成 `START → 目标节点 → END`，无 checkpointer。只读取外层 `astream(stream_mode="updates")`，包括目标 IO 节点原有耗尽处理器的更新。编译图和校验元数据可复用，请求 State 不缓存。相同 `conversation_id` 也不会恢复会话；输入的历史消息只在本次调用可见。复合子图的输出由其原有输出契约决定，执行器不会用输入输出差值删字段。

重试分类与现役图一致：普通 IO 使用 `add_io_node` 的 RetryPolicy 和耗尽处理；ticker 的四个私有 IO 使用 `with_error_handler=False`，耗尽后由接口报告异常；写节点及复合子图外层无新增重试。客户端内部既有重试保持不变。ticker 本来吞异常返回空结果的路径仍返回空结果，不补业务 trace。

## 本地启动

保留现有 `.env`。复制独立覆盖示例并按本机修改 MySQL 端口、账号：

```powershell
Copy-Item infra/nodes-run.env.example .env.nodes.local
# 当前工作机的 MySQL 映射端口是 3530；示例默认采用 compose 的 3306。
.venv/Scripts/python.exe -m uvicorn mock_api.server:app --host 127.0.0.1 --port 8099
```

另开终端运行应用：

```powershell
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010 --env-file .env.nodes.local
```

覆盖示例把全部业务 HTTP 指向本地 mock，补齐 OTC、GOATS、标的查询凭据及 GOATS agent 标识，并设置 `DRY_RUN_BACKEND=false`。LLM 的 `QWEN_API_BASE`、`QWEN_API_KEY`、`QWEN_MODEL_STANDARD/THINKING/COMPLEX/VL` 继续来自现有 `.env`；也可写入本地覆盖文件。图片成功验收需要所配置网关支持视觉模型。所有这些客户端共用已有配置，无节点级 mock 开关。

`ENVIRONMENT=staging` 使 `persist_intent` 使用与主工作流相同的 `MessageClientHttpx` 工厂，确实向 HTTP mock 写回；`development` 会保持既有跳过行为。业务库和 checkpoint 都配到本地 MySQL；开启 checkpoint 只影响原工作流，节点接口始终无 checkpoint。库初始化沿用 `sql/init.sql` 与 `sql/schema.sql`。

环境变量优先于 dotenv 文件，启动前应清除终端内遗留的后端地址变量。如本机禁止绑定 `8099`，可改用 `18099`，同时替换覆盖文件中三个 URL 的端口并重启两个服务。本次实际验收使用 `18099`。

单次调用（PowerShell）：

```powershell
$body = @{
    product = 'option'
    node = 'option_intent'
    state = @{raw_text = '期权询价 腾讯控股 1个月'; history_messages = @()}
} | ConvertTo-Json -Depth 12
Invoke-RestMethod http://127.0.0.1:8010/v1/nodes/run -Method Post -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body))
```

业务节点的机器人上下文示例：

```json
{
  "product": "option",
  "node": "option_extract_query",
  "state": {
    "conversation_id": "local-node-demo",
    "message_id": 2026092001,
    "room_id": "mock-room",
    "user_id": "mock-user",
    "raw_text": "查询订单 Q-20260920-000001"
  }
}
```

ticker 单条解析：

```json
{
  "product": "ticker",
  "node": "resolve_org_item",
  "state": {
    "index": 0,
    "org_str": "腾讯控股",
    "keywords": [{"keyword": "腾讯控股", "isFull": false}],
    "predicted_family": "EQUITY"
  }
}
```

该节点仅解析这一条，返回 `winners`；输入类型为 `OrgItemInput`，图承载类型为包含该输入和 `winners` 的 `OrgItemState`，不会自动 fan-out 或 assemble。`assemble` 可独立接收 `winners`，沿用按 `index` 排序、按 windCode 去重的行为。

## 持久化验收

显式调用 `persist` 会把输入 trace 写入业务库 `node_trace`；写库失败沿用只记日志的策略，因此 HTTP 200 不能证明写入成功。下列测试实际执行接口、查询唯一 trace_id 对应的数据库记录，并只清理自己插入的验收行：

```powershell
$env:RUN_NODE_MYSQL_TEST='1'
.venv/Scripts/python.exe -m pytest tests/integration/test_nodes_persist_mysql.py -q
Remove-Item Env:RUN_NODE_MYSQL_TEST
```

`persist_intent` 写配置的 Message 后端，不写本地 node_trace。`record_history` 和 `remember_confirmed_params` 只返回更新，不自动保存会话。节点接口不插入幂等、persist 或 render。

## 切回真实业务后端

网络恢复后，在本地覆盖文件中替换以下变量，停止并重启应用，使缓存配置和预编译图重新加载：

| 客户端 | 地址配置 | 凭据配置 |
| --- | --- | --- |
| Option / Swap / Ticker / Message | `OTC_API_BASE_URL`：后端主机根地址，客户端追加 `/admin-api/...` | `OTC_API_SECRET`，以及既有 GOATS 签名配置 |
| GOATS agent / 快速询价 parser | `GOATS_BASE_URL`：GOATS 主机根地址，客户端规范化 `/api` 前缀 | `GOATS_CLIENT_ID`、`GOATS_CLIENT_SECRET`、`GOATS_EXTAPP_SALT`、`GOATS_OPT_AGENT_ID`、`GOATS_OPT_AGENT_SUB_ID` |
| 保留的独立标的查询配置 | `SECURITIES_INSTRUMENT_URL`：完整查询 URL；现役 ticker 走上面的 TickerClient | `SECURITIES_INSTRUMENT_KEY` |

真实地址和凭据使用业务方提供的值；保持 `DRY_RUN_BACKEND=false` 才会发出真实写请求。不需要修改节点代码。本地 mock 验证只证明调用链和响应契约，不等于真实后端业务验收。

## 自动化验证

```powershell
.venv/Scripts/python.exe -m pytest tests/test_nodes_run_api.py tests/test_nodes_execution.py -q
.venv/Scripts/python.exe -m pytest tests/ -q
.venv/Scripts/python.exe -m ruff check app/ tests/
.venv/Scripts/python.exe -m mypy app/
.venv/Scripts/python.exe -X utf8 scripts/sync_agents_md.py --check
```

新测试位于默认收集目录，LLM 在模型边界 mock，业务客户端通过真实 HTTP transport 接入 `mock_api`。没有改动 `scripts/ai_test_langgraph/`。

## 节点目录

表中 `B` 表示 `conversation_id`、`room_id`、`user_id` 必须为非空字符串，`message_id` 必须为正整数；`M` 表示启用 Message 客户端时必须提供 `conversation_id` 与 `message_id`。`—` 表示无额外必需字段，仍遵守对应 State 的字段类型。

失败策略：`IO` 为原有可重试 IO，耗尽返回 error；`私有 IO` 耗尽抛异常；`安全节点` 沿用 safe_node，无图级重试；`复合` 仅内部节点使用原有策略；`原函数` 保持既有异常/空结果行为。下表的写操作均由显式调用触发。

| 命名空间 | 节点 | 输入类型 | 必需上下文 | 内部调用 | 持久化/副作用 | 失败策略 |
| --- | --- | --- | --- | --- | --- | --- |
| main | `ingest` | AgentState | — | 清空本轮输出 | 无 | 安全节点 |
| main | `quick_inquiry` | AgentState | B | GOATS parser → Option operate | 后端询价建单 | 安全节点 |
| main | `existing_command_query` | AgentState | — | GOATS instruction/query | 无 | IO |
| main | `pre_route` | AgentState | — | 解析对手及候选 JSON | 无 | 安全节点 |
| main | `intent_route` | AgentState | — | 规则 / 路由 LLM | 无 | IO |
| main | `swap` | AgentState | B | 完整 swap 子图 | 按分支调用后端 | 复合 |
| main | `option` | AgentState | B | 完整 option 子图 | 按分支调用后端 | 复合 |
| main | `option_close` | AgentState | B | 完整 close 子图 | 按分支调用后端 | 复合 |
| main | `fallback` | AgentState | — | 原有友好降级 | 无 | 安全节点 |
| main | `persist_intent` | AgentState | M（启用时） | Message set-intent；development 跳过 | 后端消息写回 | 安全节点 |
| main | `persist` | AgentState | — | 写 node_trace | 本地 MySQL；失败仅日志 | 安全节点 |
| main | `render` | AgentState | — | 原有回复渲染 | 无 | 安全节点 |
| main | `remember_confirmed_params` | AgentState | — | 提取已确认订单记忆 | 仅状态更新 | 安全节点 |
| main | `record_history` | AgentState | — | 组装本轮消息 | 仅状态更新 | 安全节点 |
| option | `option_intent` | AgentState | — | 规则 / 意图 LLM | 无 | IO |
| option | `option_extract_inquiry` | AgentState | B | 询价子图：GOATS / LLM / ticker / Option | 后端询价建单 | 复合 |
| option | `option_extract_place` | AgentState | B | 确定性参数提取 → Option | 后端下单 | 安全节点 |
| option | `option_extract_confirm_place` | AgentState | B | 确定性订单引用 → Option | 后端确认 | 安全节点 |
| option | `option_extract_cancel_place` | AgentState | B | 确定性订单引用 → Option | 后端撤单 | 安全节点 |
| option | `option_extract_cancel` | AgentState | B | 确定性订单引用 → Option | 后端撤单申请 | 安全节点 |
| option | `option_extract_confirm_cancel` | AgentState | B | 确定性订单引用 → Option | 后端撤单确认 | 安全节点 |
| option | `option_extract_query` | AgentState | B | 确定性订单引用 → Option | 查询 | IO |
| option | `option_unknown` | AgentState | — | 记录 unknown 意图 | 无 | 安全节点 |
| option | `inquiry_fast_parse` | InquiryState | — | GOATS rfq parser | 无 | IO |
| option | `inquiry_fast_submit` | InquiryState | B | Option operate | 后端询价建单 | 安全节点 |
| option | `inquiry_precheck` | InquiryState | — | 代码检测 / ticker | 无 | IO |
| option | `inquiry_reject` | InquiryState | — | 原有无效标的回复 | 无 | 安全节点 |
| option | `inquiry_extract` | InquiryState | — | 询价 LLM + 确定性归一化 | 无 | IO |
| option | `inquiry_resolve` | InquiryState | — | ticker 子图 + 订单绑定 | 无 | IO |
| option | `inquiry_submit` | InquiryState | B | Option operate | 后端询价建单 | 安全节点 |
| swap | `swap_intent` | AgentState | — | 规则 / 意图 LLM | 无 | IO |
| swap | `swap_place_order` | AgentState | — | 提取 LLM + ticker | 无 | IO |
| swap | `swap_recognize_fresh_counterparty` | AgentState | — | 对手 LLM + 候选校验 | 无 | 安全节点 |
| swap | `swap_select_counterparty` | AgentState | — | 对手选择 LLM | 无 | IO |
| swap | `swap_select_ticker` | AgentState | — | 标的选择 LLM | 无 | IO |
| swap | `swap_apply_picks` | AgentState | — | 按选择指针更新订单 | 无 | 安全节点 |
| swap | `swap_place_order_submit` | AgentState | B | Swap operate | 后端下单 | 安全节点 |
| swap | `swap_confirm` | AgentState | B | 二次校验 + Swap | 后端确认 | 安全节点 |
| swap | `swap_cancel` | AgentState | B | Swap operate | 后端撤单 | 安全节点 |
| swap | `swap_query_order` | AgentState | B | Swap operate | 查询 | IO |
| swap | `swap_unknown` | AgentState | — | 记录 unknown 意图 | 无 | 安全节点 |
| swap | `swap_image_order` | AgentState | input_files | 视觉 OCR → 参数 LLM | 无；不提交 | IO |
| swap | `swap_excel_order` | AgentState | input_files | 下载 Excel → openpyxl → 参数 LLM | 无；不提交 | IO |
| option_close | `close_intent` | AgentState | — | 意图 LLM | 无 | IO |
| option_close | `close_holding_query` | AgentState | B | 持仓参数 LLM → Option | 查询 | IO |
| option_close | `close_place_close` | AgentState | B | 平仓复合子图 | 后端平仓申请 | 复合 |
| option_close | `close_confirm_close` | AgentState | B | 确定性订单引用 → Option | 后端平仓确认 | 安全节点 |
| option_close | `close_cancel_close` | AgentState | B | 确定性订单引用 → Option | 后端撤单 | 安全节点 |
| option_close | `close_confirm_cancel` | AgentState | B | 确定性订单引用 → Option | 后端撤单确认 | 安全节点 |
| option_close | `close_query_status` | AgentState | B | 确定性订单引用 → Option | 查询 | IO |
| option_close | `close_unknown` | AgentState | — | 记录 unknown 意图 | 无 | 安全节点 |
| option_close | `place_close_parse` | PlaceCloseState | — | 引用解析 | 无 | 安全节点 |
| option_close | `place_close_fetch_orders` | PlaceCloseState | pc_parsed | Option query-close-orders | 查询；原有失败降为空列表 | IO |
| option_close | `place_close_extract` | PlaceCloseState | pc_parsed | 平仓参数 LLM | 无 | IO |
| option_close | `place_close_normalize` | PlaceCloseState | pc_parsed | 合并 + 参数归一化 | 无 | 安全节点 |
| option_close | `place_close_validate` | PlaceCloseState | — | 业务参数校验 | 无 | 安全节点 |
| option_close | `place_close_submit` | PlaceCloseState | B | Option operate | 后端平仓申请 | 安全节点 |
| option_close | `place_close_reject` | PlaceCloseState | — | 原有参数拒绝回复 | 无 | 安全节点 |
| ticker | `extract_candidates` | TickerState | raw_text | tokenize + 格式化 | 无 | 原函数 |
| ticker | `infer_codes` | TickerState | candidates | 批量代码推断 LLM；git 提示词 | 无 | 私有 IO |
| ticker | `split_keywords` | TickerState | candidates | 批量关键词 LLM | 无 | 私有 IO |
| ticker | `judge_type` | TickerState | candidates | 批量类型 LLM | 无 | 私有 IO |
| ticker | `merge_candidates` | TickerState | raw_text | 候选合并 + GOATS 完整代码校验 | 无 | 原函数 |
| ticker | `resolve_org_item` | OrgItemInput | index, org_str, keywords, predicted_family | 单条 GOATS 查询；多命中时 rank LLM | 无 | 私有 IO |
| ticker | `assemble` | TickerState | — | 按 index 排序、windCode 去重 | 无 | 原函数 |
