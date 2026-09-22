# 节点调试接口使用指南

`POST /v1/nodes/run` 用于隔离执行一个已注册的 LangGraph 节点或复合子图，返回该目标的实际 State 更新。它适合定位意图识别、参数提取、后端调用和内部阶段问题；完整会话仍应使用 `POST /v1/workflows/run`。

当前工作区共注册 59 项：`main` 17、`option` 14、`swap` 13、`option_close` 15（标的识别已委托 Java 后端，不再有 `ticker` 命名空间）。注册名称以 [registry.py](../app/node_execution/registry.py) 为准，文末有[节点中英文对照表](#9-节点中英文对照表)。

> `/v1/nodes/run` 不执行上游节点、不恢复 checkpoint，也不继承前一次调用的 State。复合子图会按原路由执行内部链路；下单、确认、撤单、持久化等节点会保留原有副作用。连接真实后端时应先测试只读节点。

## 1. 使用真实后端启动

以下命令从仓库根目录执行，示例使用 Windows PowerShell。

首次安装：

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"
```

本指南直接读取根目录 `.env`，不传 `--env-file .env.nodes.local`。启动前确认：

- `OTC_API_BASE_URL` 指向可访问的真实业务后端；若配置为 `127.0.0.1`，本机必须有对应服务或端口转发。
- `GOATS_BASE_URL` 与 `GOATS_CLIENT_*` 指向可访问的 GOATS 测试环境。
- `QWEN_API_BASE`、`QWEN_API_KEY` 和 `QWEN_MODEL_*` 可用；这些历史变量名也用于当前 DeepSeek/Qwen 兼容网关。
- `DRY_RUN_BACKEND=false`，允许请求实际发往配置的后端。

如果 `.env` 中启用了 `USE_MYSQL_CHECKPOINTER=true`，先启动 MySQL：

```powershell
docker compose up -d mysql
docker compose ps mysql
```

如果只调试不依赖 checkpoint 或数据库的节点，可以在 `.env` 中暂时设 `USE_MYSQL_CHECKPOINTER=false`。要测试 `main/persist`，还需确认业务库已执行 [sql/schema.sql](../sql/schema.sql)。

启动应用：

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8201 --reload
```

检查应用：

```powershell
Invoke-RestMethod http://127.0.0.1:8201/health
```

`backend_mode=real` 只表示 `DRY_RUN_BACKEND=false`，不证明后端已经连通。可在启动前查看最终解析出的地址；命令不会输出密钥：

```powershell
python -c "from app.config import get_settings; s=get_settings(); print('OTC =', s.otc_api_base_url); print('GOATS =', s.goats_base_url); print('dry-run =', s.dry_run_backend)"
```

## 2. 第一次执行

打开 <http://127.0.0.1:8201/docs>，在 `POST /v1/nodes/run` 中执行一个不依赖 LLM 或业务后端的节点：

```json
{
  "product": "main",
  "node": "fallback",
  "state": {
    "error": {"node": "option_intent", "type": "ValidationError", "message": "demo"}
  }
}
```

预期 HTTP 200，主要输出为：

```json
{
  "product": "main",
  "node": "fallback",
  "output": {
    "trace": [
      {"node": "fallback", "decision": "triggered_by:option_intent"}
    ]
  }
}
```

PowerShell 调用方式：

```powershell
$body = @{
    product = 'main'
    node = 'fallback'
    state = @{ error = @{ node = 'option_intent'; type = 'ValidationError'; message = 'demo' } }
} | ConvertTo-Json -Depth 50

Invoke-RestMethod `
    -Uri 'http://127.0.0.1:8201/v1/nodes/run' `
    -Method Post `
    -ContentType 'application/json; charset=utf-8' `
    -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) `
    -TimeoutSec 240 | ConvertTo-Json -Depth 50
```

## 3. 从 Langfuse 准备 State

从 Langfuse 节点 span 复制 State 时，优先先调用 `POST /v1/nodes/prepare`：

```json
{
  "product": "option_close",
  "node": "close_intent",
  "langfuse_input": {
    "raw_text": "我要平仓",
    "quote_content": "",
    "history_messages": [],
    "message_id": "123",
    "trace": [],
    "field_records": {}
  }
}
```

处理流程：

1. `prepare` 按目标节点裁剪字段，并做安全的递归类型转换。
2. HTTP 200 时，将响应中的整个 `request` 直接提交给 `/v1/nodes/run`。
3. HTTP 422 时，根据 `missing_fields` 和 `detail` 补齐或修正 `request.state` 后再执行。

`prepare` 不执行节点，也不访问 LLM、业务后端或数据库。它只保证输入满足当前接口校验，不能保证业务调用成功；也不会从混合文本猜数字、补默认值，或把 `null` 改成空字符串。

## 4. 选择节点和准备输入

请求顶层固定为：

| 字段 | 说明 |
| --- | --- |
| `product` | 注册命名空间：`main`、`option`、`swap` 或 `option_close` |
| `node` | 注册表中的节点名，不是 Python 导入路径 |
| `state` | 目标节点本次读取的 JSON State |

`product` 只用于查找注册项，不会自动写入 `state.product_type`。接口采用严格校验：未知字段、错误类型和缺少必需上下文都会返回 422。

主要输入类型：

| 类型 | 使用范围 | 定义 |
| --- | --- | --- |
| `AgentState` | 主图、业务子图和大多数节点 | [app/graph/state.py](../app/graph/state.py) |
| `InquiryState` | `option/inquiry_*` | [extract_inquiry.py](../app/subgraphs/option/extract_inquiry.py) |
| `PlaceCloseState` | `option_close/place_close_*` | [place_close.py](../app/subgraphs/close/place_close.py) |

调用后端的节点通常要求以下上下文：

```json
{
  "conversation_id": "真实测试会话ID",
  "message_id": 2026092101,
  "room_id": "真实测试群ID",
  "user_id": "真实测试用户ID"
}
```

注意：

- JSON 数字和布尔值必须保持对应类型，不能写成字符串。
- 内部阶段只执行该阶段；例如 `inquiry_submit` 不会先运行 `inquiry_extract`，必须显式提供所需中间字段。
- 每次请求彼此独立。需要历史时显式传入 `history_messages` 或相应记忆字段。
- `input_files` 中的图片 URL 必须能被视觉模型访问；远端模型通常不能访问本机 `127.0.0.1`。Excel 文件只需应用进程可下载。
- 复合项 `main/swap`、`main/option`、`main/option_close` 会执行完整子图，可能调用 LLM、GOATS 和订单后端。

查看当前注册项：

```powershell
.venv/Scripts/python.exe -c "from app.node_execution.registry import build_registry; print('\n'.join(f'{x.product}/{x.name}' for x in build_registry()))"
```

## 5. 常用请求

### LLM 意图识别

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

重点检查 `output.intent` 和 `output.trace`，不要期待该节点返回订单后端结果或最终回复。

### 查询真实后端订单

```json
{
  "product": "option",
  "node": "option_extract_query",
  "state": {
    "conversation_id": "真实测试会话ID",
    "message_id": 2026092101,
    "room_id": "真实测试群ID",
    "user_id": "真实测试用户ID",
    "raw_text": "查询订单 Q-真实测试订单号"
  }
}
```

将占位值替换为测试环境中的真实数据。除 `output.api_code` 和 `output.api_result` 外，还应通过业务后端日志或请求记录确认 `/admin-api/financial-orders/operate` 收到了请求。

### 单独验证渲染

```json
{
  "product": "main",
  "node": "render",
  "state": {
    "product_type": "option",
    "api_code": 0,
    "api_result": "测试查询成功"
  }
}
```

这里只验证给定 State 的回复渲染，不会执行订单查询。

## 6. 判断执行结果

`output` 是目标节点返回的更新，不是合并后的完整 State；空对象、`null` 或没有 `reply_text` 可能正是节点契约。

| HTTP 状态 | 含义 |
| --- | --- |
| 200 | 节点正常返回，且 `output.error` 为空；仍需检查业务字段和后端响应 |
| 404 | `(product, node)` 未注册 |
| 422 | 请求结构、State 类型或必需上下文不合法，节点未执行 |
| 500，含 `output` | 节点返回非空 `error`，常见于安全节点或 IO 重试耗尽 |
| 500，不含 `output` | 异常穿透到 HTTP 执行边界，查看顶层 `error` |

一次成功验证至少应满足：

1. HTTP 状态与目标分支预期一致，输出中没有意外错误。
2. `intent`、参数、订单号、标的、回复等目标字段符合输入语义。
3. 预期调用后端或写库时，有对应的服务日志、请求记录或数据库记录。

`api_code=0` 也必须结合 `api_result` 判断。`option_unknown` 返回兜底文案、`persist` 返回 `{}` 都可能是正常结果；`/health` 或 HTTP 200 不能单独证明业务链路成功。

## 7. 自动化验证

节点接口、注册表、执行器和 State 准备器的专项测试：

```powershell
.venv/Scripts/python.exe -m pytest `
    tests/test_nodes_run_api.py `
    tests/test_nodes_execution.py `
    tests/test_nodes_prepare.py `
    -q
```

可选的真实 MySQL 持久化测试：

```powershell
$env:RUN_LOCAL_MYSQL_TESTS = '1'
.venv/Scripts/python.exe -m pytest tests/integration/test_nodes_persist_mysql.py -q
Remove-Item Env:RUN_LOCAL_MYSQL_TESTS
```

完整回归仍按仓库统一命令执行。2026-09-20 的一次性环境、结果和视觉模型限制已单独归档在[节点接口验收记录](testing/nodes-run-acceptance-20260920.md)，不要把该历史记录当作当前全量基线。

实现入口：[路由](../app/api/nodes.py)、[注册表](../app/node_execution/registry.py)、[准备器](../app/node_execution/prepare.py)、[校验器](../app/node_execution/validation.py)、[执行器](../app/node_execution/executor.py)。

## 8. 执行边界与真实后端安全

- 单节点执行图固定为 `START → 目标节点 → END`，不挂 checkpointer。
- 只读 IO 沿用主图的 `RetryPolicy`；写节点不会新增图级自动重试。
- `START`、`END`、条件路由、辅助函数和内部错误处理器不会注册为可调用节点。
- `main/persist` 写入的是本次 State 中显式提供的 `trace`，不会收集此前独立请求的输出；写库失败当前只记日志，必须查库确认。

本指南的启动命令直接读取 `.env`。修改 `OTC_API_BASE_URL`、`GOATS_BASE_URL` 或对应凭据后必须重启应用；State 中也要提供真实测试环境的群、用户、消息和订单标识。

保持 `DRY_RUN_BACKEND=false` 会让写请求真正发往配置目标。真实下单、确认或撤单前，应先核对 URL、账号、环境和业务授权，并优先用查询类节点确认网络、认证和接口契约。

## 9. 节点中英文对照表

以下是当前 `/v1/nodes/run` 的全部 65 个注册项。所属对应请求中的 `product`，英文名对应 `node`；业务子图入口会执行内部链路。注册名称以 [registry.py](../app/node_execution/registry.py) 为准。

| 所属（product） | 节点英文名（node） | 中文名 |
| --- | --- | --- |
| `main` | `ingest` | 入口消息整理与当轮状态初始化 |
| `main` | `quick_inquiry` | 快速询价 |
| `main` | `existing_command_query` | 存量指令查询 |
| `main` | `entry_route` | 三类业务入口选择 |
| `main` | `plan_instructions` | 多指令拆分与依赖规划 |
| `main` | `instructions` | 多指令按依赖编排执行（复合项） |
| `main` | `pre_route` | 路由前置处理 |
| `main` | `intent_route` | 一级意图路由 |
| `main` | `swap` | 互换业务子图 |
| `main` | `option` | 期权业务子图 |
| `main` | `option_close` | 期权平仓业务子图 |
| `main` | `fallback` | 异常兜底 |
| `main` | `persist_intent` | 消息意图写回 |
| `main` | `persist` | 节点轨迹持久化 |
| `main` | `render` | 回复渲染 |
| `main` | `remember_confirmed_params` | 记忆已确认参数 |
| `main` | `record_history` | 记录会话历史 |
| `option` | `option_intent` | 期权意图识别 |
| `option` | `option_extract_inquiry` | 期权询价流程（复合子图） |
| `option` | `option_extract_place` | 期权请求下单参数提取 |
| `option` | `option_extract_confirm_place` | 期权确认下单参数提取 |
| `option` | `option_extract_cancel_place` | 期权取消下单订单号提取 |
| `option` | `option_extract_cancel` | 期权请求撤单订单号提取 |
| `option` | `option_extract_confirm_cancel` | 期权确认撤单订单号提取 |
| `option` | `option_extract_query` | 期权订单查询参数提取 |
| `option` | `option_unknown` | 期权未知意图兜底 |
| `option` | `inquiry_fast_parse` | 快速询价指令解析 |
| `option` | `inquiry_fast_submit` | 快速询价提交 |
| `option` | `inquiry_extract` | 询价参数提取 |
| `option` | `inquiry_normalize` | 询价参数归一化与多值展开 |
| `option` | `inquiry_submit` | 询价请求提交 |
| `swap` | `swap_intent` | 互换意图识别 |
| `swap` | `swap_place_order` | 互换下单参数提取 |
| `swap` | `swap_recognize_fresh_counterparty` | 新交易对手识别 |
| `swap` | `swap_select_counterparty` | 交易对手选项识别 |
| `swap` | `swap_select_ticker` | 标的选项识别 |
| `swap` | `swap_apply_picks` | 交易对手与标的选择应用 |
| `swap` | `swap_place_order_submit` | 互换下单请求提交 |
| `swap` | `swap_confirm` | 互换订单确认 |
| `swap` | `swap_cancel` | 互换订单撤单 |
| `swap` | `swap_query_order` | 互换订单查询 |
| `swap` | `swap_unknown` | 互换未知意图兜底 |
| `swap` | `swap_image_order` | 图片下单参数提取 |
| `swap` | `swap_excel_order` | Excel 下单参数提取 |
| `option_close` | `close_intent` | 期权平仓意图识别 |
| `option_close` | `close_holding_query` | 期权持仓查询 |
| `option_close` | `close_place_close` | 期权平仓下单流程（复合子图） |
| `option_close` | `close_confirm_close` | 确认期权平仓 |
| `option_close` | `close_cancel_close` | 期权平仓撤单 |
| `option_close` | `close_confirm_cancel` | 确认期权平仓撤单 |
| `option_close` | `close_query_status` | 期权平仓订单状态查询 |
| `option_close` | `close_unknown` | 期权平仓未知意图兜底 |
| `option_close` | `place_close_parse` | 平仓引用与参数解析 |
| `option_close` | `place_close_fetch_orders` | 获取并整理被引用订单 |
| `option_close` | `place_close_extract` | 平仓参数提取 |
| `option_close` | `place_close_normalize` | 平仓参数归一与合并 |
| `option_close` | `place_close_validate` | 平仓参数预校验 |
| `option_close` | `place_close_submit` | 平仓请求提交 |
| `option_close` | `place_close_reject` | 平仓请求拒绝 |
