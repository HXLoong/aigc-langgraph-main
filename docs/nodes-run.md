# LangGraph 单节点测试上手指南

`POST /v1/nodes/run` 接收 `product + node + state`，通过 LangGraph 执行指定节点，返回该节点实际输出。适合调试参数提取、后端调用、内部阶段和已注册的复合子图。

第一次使用，按下面的顺序操作：

1. [准备配置并启动服务](#1-准备配置并启动服务)。
2. [在 Swagger 或 PowerShell 发出第一次请求](#2-发出第一次请求)。
3. [选择节点并准备 State](#3-选择节点并准备-state)，参考[常用请求示例](#4-常用请求示例)。
4. [检查输出、后端调用和持久化结果](#5-如何判断测试通过)。

当前开放 65 个注册项：`main` 14、`option` 16、`swap` 13、`option_close` 15、`ticker` 7，完整列表见[节点目录](#9-节点目录)。名称以 [registry.py](../app/node_execution/registry.py) 为准。

| 要测试的范围 | 调用方式 | 执行内容 |
| --- | --- | --- |
| 一个节点 | 如 `option/option_intent` | 仅目标节点及其自身调用的逻辑 |
| 一个内部阶段 | 如 `option/inquiry_extract` | 仅该阶段；所需中间数据由请求提供 |
| 已注册的复合子图 | 如 `main/option` | 按该子图原有路由执行内部节点 |
| 完整会话工作流 | `POST /v1/workflows/run` | 沿用工作流接口自己的请求契约，见 [README](../README.md) |

单节点接口不会自动执行上游节点、恢复历史 checkpoint 或补充业务上下文。调用写节点会触发其原有写操作；本指南先将业务 HTTP 配到本地 mock。

## 1. 准备配置并启动服务

以下命令从仓库根目录执行，兼容 Windows PowerShell 5.1。复制代码块内容即可，不要复制终端提示符 `PS ...>`、`>>` 或 Markdown 的代码围栏。

### 1.1 安装依赖并准备 MySQL

需要 Python 3.11+ 和本地 MySQL（兼容范围 `8.0.19 ≤ version < 9.6.0`）。首次安装可执行；已有 `.venv` 时跳过创建步骤：

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"
```

已有本地 MySQL 可直接复用；使用仓库 Compose 时启动：

```powershell
docker compose up -d mysql
docker compose ps mysql
```

在数据库客户端确认以下两项：

- [sql/init.sql](../sql/init.sql) 中的业务库、checkpoint 库和账号授权已建立。Compose 首次创建空数据卷时自动执行该脚本。
- 对业务库执行 [sql/schema.sql](../sql/schema.sql)，确认存在 `node_trace` 及其 `trace_id` 列。Compose 的初始化挂载不包含这份表结构脚本；已有旧表时按文件中的存量迁移说明补齐字段，`CREATE TABLE IF NOT EXISTS` 不会修改旧表。

已有数据卷不会重新执行初始化脚本。MySQL 地址、端口和账号以本机为准：仓库 Compose 默认映射 `3306`，此前验收机器使用 `3530`，不要照搬其他人的端口。

### 1.2 创建独立覆盖配置

保留原 `.env`，首次创建 `.env.nodes.local`：

```powershell
if (-not (Test-Path .env.nodes.local)) {
    Copy-Item infra/nodes-run.env.example .env.nodes.local
}
```

编辑 `.env.nodes.local`。示例文件默认 mock 端口为 `8099`，本指南统一使用 `18099`，将这三个地址一起修改：

```dotenv
OTC_API_BASE_URL=http://127.0.0.1:18099
GOATS_BASE_URL=http://127.0.0.1:18099
SECURITIES_INSTRUMENT_URL=http://127.0.0.1:18099/admin-api/integration/securities-instrument/select
```

然后核对以下配置；完整键名和 mock 凭据见 [infra/nodes-run.env.example](../infra/nodes-run.env.example)：

| 配置 | 本地测试要求 |
| --- | --- |
| `BUSINESS_MYSQL_URI` | 指向本地业务库，格式 `mysql+aiomysql://账号:密码@主机:端口/otc_agent_business` |
| `CHECKPOINT_MYSQL_URI` | 指向本地 checkpoint 库，格式 `mysql://账号:密码@主机:端口/otc_agent_checkpoint` |
| `QWEN_API_BASE`、`QWEN_API_KEY` | 可用的真实 LLM 网关及凭据；沿用 `.env`，也可在覆盖文件中填写 |
| `QWEN_MODEL_STANDARD`、`QWEN_MODEL_THINKING`、`QWEN_MODEL_COMPLEX` | 网关实际支持的文本模型名；变量的 `QWEN_` 前缀是历史命名 |
| `QWEN_MODEL_VL` | 测图片节点时需要网关支持的视觉模型 |
| `OTC_API_SECRET`、GOATS 凭据及 agent 标识 | 保留示例中的本地 mock 值，避免因缺配置跳过调用 |
| `DRY_RUN_BACKEND=false` | 让客户端实际发送 HTTP 到配置的 mock 地址 |
| `ENVIRONMENT=staging` | 注入 Message 客户端，使 `persist_intent` 可以实际调用 mock；`development` 会跳过 |
| `USE_MYSQL_CHECKPOINTER=true` | 随应用启动原工作流的 MySQL checkpoint；单节点图本身始终不使用 checkpoint |

LLM 配置即使在第一次测试不触发 LLM 时也需要满足应用配置校验。没有现成 `.env` 的开发者，应在 `.env.nodes.local` 中补齐上述 LLM 地址、凭据和模型名。真实凭据只保存在本地。

加载优先级为：**终端已有环境变量 → `--env-file .env.nodes.local` → `.env` → 代码默认值**。如果终端曾设置过同名变量，先移除对应变量或使用干净终端；修改文件后要重启应用。

### 1.3 分别启动 mock 和应用

终端 A：

```powershell
.venv/Scripts/python.exe -m uvicorn mock_api.server:app --host 127.0.0.1 --port 18099
```

终端 B：

```powershell
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010 --env-file .env.nodes.local
```

等终端 B 出现 `Application startup complete`，再在终端 C 检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8010/health
```

预期 `status=ok`。其中 **`backend_mode=real` 只表示未开启 dry-run，并不表示连接了客户真实后端**；本例的实际目标仍是 `127.0.0.1:18099`。`/health` 只检查服务存活，不能替代节点测试或数据库验证。

应用和 mock 的端口不同：请求节点接口使用 **8010**，业务客户端访问 mock 使用 **18099**。

## 2. 发出第一次请求

先测 `ticker/extract_candidates`，其节点逻辑是确定性处理，不调用 LLM 或业务 HTTP。

### 2.1 使用 Swagger

1. 打开 <http://127.0.0.1:8010/docs>。
2. 展开 `POST /v1/nodes/run`，点击 **Try it out**。
3. 用下方 JSON 替换整个请求体，点击 **Execute**。
4. 查看 **Server response** 的 HTTP Code 和 **Response body**。

```json
{
  "product": "ticker",
  "node": "extract_candidates",
  "state": {
    "raw_text": "腾讯控股"
  }
}
```

预期 HTTP 200，响应为：

```json
{
  "product": "ticker",
  "node": "extract_candidates",
  "output": {
    "candidates": ["腾讯控股"]
  }
}
```

当前 Swagger 下方 **Responses → Example Value** 可能显示 `"string"`，且 `state` 没有按节点展开字段。这是当前 OpenAPI 声明的限制；实际返回结构看 **Server response**，输入字段看本文和对应 State 定义。

### 2.2 使用 PowerShell

同一个请求可以直接运行：

```powershell
$body = @{
    product = 'ticker'
    node = 'extract_candidates'
    state = @{ raw_text = '腾讯控股' }
} | ConvertTo-Json -Depth 50

$response = Invoke-WebRequest `
    -Uri 'http://127.0.0.1:8010/v1/nodes/run' `
    -Method Post `
    -UseBasicParsing `
    -ContentType 'application/json; charset=utf-8' `
    -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) `
    -TimeoutSec 240

$response.StatusCode
$result = $response.Content | ConvertFrom-Json
$result | ConvertTo-Json -Depth 50
```

之后修改 `$body` 中的三个字段即可测试其他节点。显式 UTF-8 编码用于避免中文乱码，`-Depth 50` 用于完整显示嵌套输出。遇到非 2xx 响应时，PowerShell 会抛出 HTTP 异常；可以先在 Swagger 查看完整错误 JSON。

## 3. 选择节点并准备 State

请求的三个顶层字段必须齐全：

| 字段 | 含义 | 注意事项 |
| --- | --- | --- |
| `product` | 节点命名空间 | 仅允许目录中匹配的组合；不会自动写入 `state.product_type` |
| `node` | 注册的节点名 | 例如 `option_intent`；不能传 Python 导入路径 |
| `state` | 该节点本次执行所需的输入对象 | 使用 JSON 对象，不能传 JSON 字符串 |

先在[节点目录](#9-节点目录)查输入类型和必需上下文，再准备符合业务场景的内容。**“没有额外必需字段”只表示入口校验允许省略，不表示空 State 能覆盖这个节点的成功业务路径。**

| 输入类型 | 适用范围 | 字段定义 |
| --- | --- | --- |
| `AgentState` | 公共节点、业务节点和复合子图入口 | [app/graph/state.py](../app/graph/state.py) |
| `InquiryState` | `option/inquiry_*` | [extract_inquiry.py](../app/subgraphs/option/extract_inquiry.py)；含 `AgentState` 和 `iq_*` 中间字段 |
| `PlaceCloseState` | `option_close/place_close_*` | [place_close.py](../app/subgraphs/close/place_close.py)；含 `AgentState` 和 `pc_*` 中间字段 |
| `TickerState` | ticker 阶段，单条解析除外 | [resolver.py](../app/subgraphs/ticker/resolver.py) |
| `OrgItemInput` | `ticker/resolve_org_item` | [resolver.py](../app/subgraphs/ticker/resolver.py)；仅单条解析的四个输入字段 |

准备输入时遵循以下规则：

- 后端节点通常需要 `conversation_id`、`room_id`、`user_id` 三个非空字符串，以及正整数 `message_id`。目录用 `B` 标记。示例的 `mock-room`、`mock-user` 只适用于本地 mock。
- 数字和布尔值保持 JSON 类型，例如 `message_id: 2026092001`、`isFull: false`，不要写成字符串。
- `history_messages` 可传 `[{"role":"user","content":"上一条消息"}]`，`tickers` 可使用 `windCode` 等现有模型别名。接口负责转换模型，拒绝未知 State/模型字段；开放字典字段的内容仍由节点按原业务规则处理。
- 单测内部阶段时，直接提供它需要的中间字段。例如 `inquiry_submit` 要测试有效提交，需要准备订单数据，不能只提供原始文本并期待它自动提取。
- 用前一次输出构造下一次请求时，只挑选目标 State 支持且需要的字段；不要把外层 `product/node/output` 整体塞进 `state`。缺少的原始文本、用户信息等需要自行补上。
- 每次请求独立，即使 `conversation_id` 相同也不会承接上一请求。要测试历史上下文，应显式传入 `history_messages` 或对应记忆字段。

## 4. 常用请求示例

以下 JSON 均可直接粘贴到 Swagger 请求体。LLM 输出可能变化，验证时检查业务字段和含义，不要求整段 JSON 字节相同。

### 4.1 意图识别：验证 LLM 路径

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

检查 `output.intent` 是否为 `new_inquiry`，并查看 `trace` 的决策信息。此节点不调用订单后端；不要要求它返回 `api_code` 或机器人回复。具体请求是否走到 LLM，以节点实际分支和调用日志为准。

### 4.2 查询订单：验证真实客户端到 HTTP mock

```json
{
  "product": "option",
  "node": "option_extract_query",
  "state": {
    "conversation_id": "local-node-test",
    "message_id": 2026092001,
    "room_id": "mock-room",
    "user_id": "mock-user",
    "raw_text": "查询订单 Q-20260920-000001"
  }
}
```

检查 `output.query_filter.orderList[0].orderId` 为 `Q-20260920-000001`、`output.api_code` 为 `0`，并查看 `output.api_result`。在 mock 终端应能看到 `POST /admin-api/financial-orders/operate`。

这个节点确定性提取订单号，`trace` 中 `decision=deterministic,orders=1`、LLM 信息为空是正常的。返回“已成交”等内容来自 mock 的测试数据，不代表真实订单成交。

### 4.3 公共节点：单独测试回复渲染

```json
{
  "product": "main",
  "node": "render",
  "state": {
    "product_type": "option",
    "api_code": 0,
    "api_result": "本地 mock 查询成功"
  }
}
```

检查 `output.reply_text`。这里测试的是给定结果的渲染，不会执行订单查询；其他节点没有返回 `reply_text` 时，接口也不会额外补一条回复。

### 4.4 内部阶段：输入中间态，不依赖上游自动执行

独立测试 ticker 的代码推断，只需要提供候选列表：

```json
{
  "product": "ticker",
  "node": "infer_codes",
  "state": {
    "candidates": ["腾讯控股"]
  }
}
```

检查 `output.infer_codes`。接口不会先运行 `extract_candidates`；这里的候选由测试者直接给出。其他 ticker 阶段的输入、输出对应关系如下：

| 阶段 | 测试 State 中准备的内容 | 主要输出 |
| --- | --- | --- |
| `extract_candidates` | `raw_text` | `candidates` |
| `infer_codes` | `candidates` | `infer_codes` |
| `split_keywords` | `candidates` | `split_codes` |
| `judge_type` | `candidates` | `ins_family` |
| `merge_candidates` | `raw_text`，以及要验证的 `infer_codes`、`split_codes`、`ins_family` | `pending_items`、`winners` |
| `resolve_org_item` | 四字段 `OrgItemInput`，见下一节 | `winners` |
| `assemble` | 待汇总的 `winners`，可带 `candidates` | `resolved` |

期权内部阶段同样可以直接注入中间态。下面专门验证拒绝分支，不需要运行前面的询价阶段：

```json
{
  "product": "option",
  "node": "inquiry_reject",
  "state": {
    "iq_reject_reply": "测试标的不在可交易范围内"
  }
}
```

预期 HTTP 200，`output.reply_text` 等于输入文案。这是拒绝分支按设计执行成功，不代表询价建单成功。

平仓内部阶段可先独立调用解析节点：

```json
{
  "product": "option_close",
  "node": "place_close_parse",
  "state": {
    "raw_text": "平仓 OPT-ABC123 100万 市价",
    "quote_content": ""
  }
}
```

检查 `output.pc_parsed.contractCodes` 包含 `OPT-ABC123`。测试 `place_close_fetch_orders`、`place_close_extract` 或 `place_close_normalize` 时，把返回的 **完整 `pc_parsed` 对象** 放到新请求的 `state.pc_parsed`，再补充该阶段所需的原文、订单或 LLM 提取结果。只传 `{"contractCodes":[...]}` 会因其余必需字段缺失而返回 422；完整结构见 `ReferenceParseResult` 的[定义](../app/subgraphs/close/reference_parser.py)。

### 4.5 ticker 单条解析与汇总

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

该节点仅解析这一条，检查 `output.winners` 中的 `index`、`org_str` 和 `winner`。它使用 `OrgItemInput`，不要附带 `conversation_id`、`raw_text` 等完整 AgentState 字段。图承载类型是包含输入和 `winners` 的 `OrgItemState`，不会自动 fan-out 或执行 `assemble`。

要测汇总，将实际返回的 `winners` 放进 `ticker/assemble` 请求。也可用下面的固定夹具验证排序和去重；这是人为提供的汇总输入，不是本次 GOATS 校验的证据：

```json
{
  "product": "ticker",
  "node": "assemble",
  "state": {
    "candidates": ["腾讯控股", "贵州茅台"],
    "winners": [
      {"index": 1, "org_str": "贵州茅台", "winner": {"windCode": "600519.SH"}},
      {"index": 0, "org_str": "腾讯控股", "winner": {"windCode": "0700.HK"}},
      {"index": 2, "org_str": "腾讯控股", "winner": {"windCode": "0700.HK"}}
    ]
  }
}
```

预期 `output.resolved` 按 `0700.HK`、`600519.SH` 的顺序返回，重复的 `0700.HK` 只保留一次。

### 4.6 复合子图：执行其内部业务链

```json
{
  "product": "main",
  "node": "option",
  "state": {
    "conversation_id": "local-node-composite",
    "message_id": 2026092002,
    "room_id": "mock-room",
    "user_id": "mock-user",
    "product_type": "option",
    "raw_text": "期权询价 腾讯控股 1个月 100% 欧式看涨",
    "quote_content": "",
    "history_messages": []
  }
}
```

这会执行 option 子图的意图判断和相应询价链，可能调用 LLM、GOATS、Ticker 和 Option 后端；成功建单分支检查 `api_code`、业务结果及内部 trace。复合子图保留原有输出契约，不保证暴露全部内部 `iq_*` 字段；要查看某个阶段的私有输出，单独调用该阶段。

`main/swap`、`main/option_close` 同理，需改节点名并提供对应业务文本和 State。仅测试整个子图不能替代对其每个内部阶段的独立验证。

### 4.7 图片与 Excel 节点

准备服务能够访问的文件。Excel 本地测试可将有效订单文件放到 `.pytest-tmp/nodes-assets/order.xlsx`，然后另开终端提供下载地址：

```powershell
.venv/Scripts/python.exe -m http.server 18098 --bind 127.0.0.1 --directory .pytest-tmp/nodes-assets
```

```json
{
  "product": "swap",
  "node": "swap_excel_order",
  "state": {
    "raw_text": "按附件提取互换下单参数",
    "input_files": [
      {"type": "document", "url": "http://127.0.0.1:18098/order.xlsx"}
    ]
  }
}
```

检查 `output.place_params` 是否与附件内容一致。此节点下载 Excel、解析内容并调用文本模型，不自动提交订单。

图片请求改用 `node: "swap_image_order"`，`input_files` 条目使用 `type: "image"`，`url` 指向实际订单图片。图片 URL 会交给视觉模型，必须能被模型服务访问；远端模型通常无法访问你电脑的 `127.0.0.1`。节点也支持 `base64` 字段中的图片 data URL。视觉网关必须支持 `QWEN_MODEL_VL` 对应的模型；返回 `BadRequestError` 时先查看模型名和上游错误详情。

## 5. 如何判断测试通过

### 5.1 先区分 HTTP 成功与业务成功

响应正常时包含 `product`、`node`、`output`。`output` 是节点实际返回的更新，不是完整输入 State；可能是空对象。节点返回与输入相同的值仍保留，Pydantic 对象按现有别名序列化，`Overwrite` 展开为承载值，清空用的 `null` 保留。

| HTTP 状态 | 含义 | 应查看的内容 |
| --- | --- | --- |
| 200 | 节点正常返回，输出无非空 `error` | 核对目标业务字段；后端业务拒绝也可能是 200 |
| 404 | 未注册节点或命名空间不匹配 | `product`、`node`、`detail`；对照节点目录 |
| 422 | 请求、State 类型、未知字段或必需上下文错误，节点未执行 | `detail` 中的 `loc`、`msg` |
| 500，有 `output` | 节点返回非空 `error`，包括普通 IO 重试耗尽 | 完整 `output`，尤其 `output.error` 和原有 trace |
| 500，无 `output` | 节点抛出未转换异常 | 独立的 `error.type`、`error.message`；接口不伪造输出 |

一次成功路径测试应核对：

1. HTTP 200，输出中没有非空 `error`。
2. 输出满足该样例的预期，例如正确的 `intent`、订单号、参数、标的顺序或回复内容。
3. 预期调用后端时，有对应请求记录；预期写库时，有数据库记录。

`api_code` 只在部分节点输出中出现，空白不等于失败。返回 `api_code=0` 也要核对 `api_result` 的含义。`inquiry_reject` 等节点返回拒绝文案正是其预期行为；`persist` 返回 `{}` 也符合契约。ticker 的部分路径会保留原有“吞异常后返回空结果”行为，因此空列表不能单独证明所有外部依赖正常。

trace 是辅助信息：普通节点通常记录决策；ticker 阶段可能没有 trace，接口不会补造。节点自身也可能返回多条 trace，不能仅凭 trace 数量判断是否额外执行了节点。

### 5.2 确认后端确实收到请求

保持 mock 终端可见，单独执行第 4.2 节的订单查询，对照同一时间出现的 `POST /admin-api/financial-orders/operate` 和响应。需要核实具体参数时，结合客户端日志、HTTP 边界测试或后端请求记录；访问日志只能证明该路径收到请求。

当前链路是：`节点 → 现有业务客户端 → HTTP → 本地 mock`。`DRY_RUN_BACKEND=false`、mock 凭据和 GOATS agent 标识需要配置齐全。仅看 `/health.backend_mode` 或 `api_code=0`，不足以证明访问的是哪一个后端。

### 5.3 确认持久化

显式调用 `main/persist` 会将**输入的 trace** 写入业务库 `node_trace`，不会自动收集前几次单节点请求的输出。可使用下面的样例，每次验收更换唯一的 `trace_id`：

```json
{
  "product": "main",
  "node": "persist",
  "state": {
    "conversation_id": "local-node-persist",
    "message_id": 2026092003,
    "trace_id": "local-node-persist-demo-001",
    "trace": [
      {"node": "manual_probe", "decision": "persist smoke", "elapsed_ms": 7}
    ]
  }
}
```

预期 HTTP 200、`output: {}`。在配置的业务库查询：

```sql
SELECT trace_id, node_name, step_index, duration_ms
FROM node_trace
WHERE trace_id = 'local-node-persist-demo-001';
```

应查到 `node_name=manual_probe`、`step_index=0`、`duration_ms=7`。该节点写库失败仅记日志，**HTTP 200 不能作为写库成功证据**。重复调用会新增记录，接口不插入幂等步骤。

其他持久化相关节点的区别：

| 节点 | 实际行为 | 验证方法 |
| --- | --- | --- |
| `persist_intent` | 使用配置的 Message 后端；development 跳过 | 在 staging 提供消息上下文和意图，检查 `/admin-api/openapi/xbot/message/set-intent` 请求及节点输出 |
| `record_history` | 仅返回历史消息更新 | 核对 `output`；不会保存会话 |
| `remember_confirmed_params` | 仅返回已确认参数更新 | 核对 `output`；不会保存会话 |

### 5.4 确认全节点覆盖，查看已保存的结果

测试全部节点时，需要按目录为每个 `(product, node)` 准备独立 State 和预期结果，记录输入、HTTP 状态和完整响应。**有 65 行响应不等于 65 个成功样例**：还要检查名称无遗漏、HTTP 错误、业务字段和外部调用证据。一个样例成功也不代表该节点所有分支都已覆盖。

接口没有自动生成验收报告或保存执行历史的功能。在 Swagger 点击 Execute，不会更新本地 JSON 文件。

此前本地验收如果保留了 `.pytest-tmp/nodes-acceptance.json`，可用以下 PowerShell 5.1 兼容命令查看。这个文件是本地临时产物，新克隆的仓库不一定存在；命令只读旧记录，**不会重新执行节点**：

```powershell
$nodeResults = Get-Content .pytest-tmp/nodes-acceptance.json -Raw -Encoding UTF8 | ConvertFrom-Json

$nodeRows = foreach ($item in $nodeResults) {
    $nodeError = $item.body.output.error
    if (-not $nodeError) {
        $nodeError = $item.body.error
    }

    [pscustomobject]@{
        Node      = "$($item.product)/$($item.node)"
        HTTP      = $item.status
        HasOutput = ($item.body.PSObject.Properties.Name -contains 'output')
        Fields    = ($item.body.output.PSObject.Properties.Name -join ', ')
        API       = $item.body.output.api_code
        Error     = $nodeError.type
    }
}

$nodeRows | Format-Table Node, HTTP, HasOutput, API, Error -AutoSize
$nodeRows | Where-Object { $_.HTTP -ne 200 -or $_.Error } | Format-Table -AutoSize
```

查看某个节点的完整输出，例如图片错误：

```powershell
$nodeResults |
    Where-Object { $_.product -eq 'swap' -and $_.node -eq 'swap_image_order' } |
    ConvertTo-Json -Depth 50
```

不要使用 `ConvertFrom-Json | ForEach-Object` 直接处理顶层数组：Windows PowerShell 5.1 可能将整个数组作为一个管道对象，导致节点名挤成一行。上例先赋值再 `foreach`，逐条处理。

[2026-09-20 验收记录](testing/nodes-run-acceptance-20260920.md) 的结果是 **64 个 HTTP 200，1 个图片节点 HTTP 500**；图片失败原因是网关不支持配置的视觉模型。该记录采用真实文本 LLM、本地 HTTP mock、本地 MySQL，不能表述为“65 个节点全部成功”或“真实业务后端验收通过”。

## 6. 自动化测试与开发验证

先跑接口和执行器专项测试，无需手动启动 8010/18099 服务。下面显式加载覆盖配置，因此也适用于配置只写在 `.env.nodes.local` 中的开发环境：

```powershell
.venv/Scripts/python.exe -c "from dotenv import load_dotenv; load_dotenv('.env.nodes.local'); import pytest; raise SystemExit(pytest.main(['tests/test_nodes_run_api.py', 'tests/test_nodes_execution.py', '-q']))"
```

测试使用进程内 ASGI 应用，LLM 在模型边界 mock，涉及业务 HTTP 的路径通过真实客户端接入 HTTP mock。覆盖注册项与执行策略、输入校验、输出保真、上下文、隔离、重试、错误响应和代表性业务路径；**不是每个节点全部业务分支的真实 LLM 验收**。

实际 MySQL 验证默认跳过。以下命令在独立进程加载本地覆盖文件并启用测试，实际执行接口、核对唯一 trace_id 的数据库记录，最后只删除自己插入的验收行：

```powershell
.venv/Scripts/python.exe -c "import os; from dotenv import load_dotenv; load_dotenv('.env.nodes.local', override=True); os.environ['RUN_NODE_MYSQL_TEST']='1'; import pytest; raise SystemExit(pytest.main(['tests/integration/test_nodes_persist_mysql.py', '-q']))"
```

这里显式加载覆盖文件，是因为直接运行 pytest 不会继承另一终端 uvicorn 的 `--env-file`。

修改实现后，按仓库要求执行回归和静态检查：

```powershell
.venv/Scripts/python.exe -m pytest tests/ -q
.venv/Scripts/python.exe -m ruff check app/ tests/
.venv/Scripts/python.exe -m mypy app/
.venv/Scripts/python.exe -X utf8 scripts/sync_agents_md.py --check
```

已有验收时的全量基线问题记录在[验收文档](testing/nodes-run-acceptance-20260920.md)，不能仅凭专项测试通过就声称全量回归通过。新增测试放默认 pytest 收集的位置；本功能不依赖 `scripts/ai_test_langgraph/`，也不提供批量评估或 Judge。

实现入口：[路由](../app/api/nodes.py)、[注册表](../app/node_execution/registry.py)、[校验器](../app/node_execution/validation.py)、[执行器](../app/node_execution/executor.py)。

## 7. 常见问题与执行边界

| 现象 | 检查与处理 |
| --- | --- |
| 应用启动时报 MySQL `OperationalError`，8010 无法访问 | 核对两个 URI 的端口、账号、库和权限；主应用可能在 checkpoint 初始化时失败，即使单节点不使用 checkpoint |
| mock 无法绑定端口 | 检查占用或系统保留端口；换端口时同步修改三个业务 URL 和 mock 启动参数，再重启应用 |
| 修改 `.env.nodes.local` 后仍访问旧地址 | 检查终端同名环境变量，停止并重启应用以刷新缓存配置和编译图 |
| 404 | 对照命名空间和节点名，例如 `option/option_intent`，不能用 `main/option_intent` |
| 422 | 读取 `detail`；常见原因是缺少 B 上下文、数字写成字符串、传错 State 类型或未知字段 |
| 500 `BadRequestError` | 查看 `output.error.message` 或顶层 `error.message`；检查网关支持的模型和参数，图片还需视觉能力 |
| HTTP 200，但业务后端拒绝 | 查看 `api_code`、`api_result` 和业务参数；接口按节点原结果透传拒绝 |
| HTTP 200，但无后端日志 | 先确认该节点及本次分支是否应调用后端，再检查 dry-run、凭据、agent 标识和 environment |
| 输出为空、没有 reply 或没有 trace | 先对照节点契约；这些字段不是所有节点都有，空输出本身不构成失败 |
| 相同 conversation ID 的第二次请求缺上下文 | 本接口没有会话恢复；在本次 State 显式提供上下文 |

执行器为每个注册项预编译 `START → 目标节点 → END`，无 checkpointer，通过外层 `astream(stream_mode="updates")` 获取实际更新；普通 IO 耗尽时读取其原有错误处理器更新。只缓存编译图和校验元数据，请求 State 保持独立，不用输入输出差值推算返回值。

普通 IO 沿用 `add_io_node` 的 RetryPolicy 和耗尽处理；ticker 四个私有 IO 使用 `with_error_handler=False`，耗尽后异常交给接口边界。写节点及复合子图外层不新增图级重试，客户端内部既有重试保持不变。`START`、`END`、条件路由函数、辅助函数和内部错误处理器不开放按名称调用。

## 8. 切回真实业务后端

需要联调真实业务后端时，在本地覆盖文件中替换以下变量，停止并重启应用，使缓存配置和预编译图重新加载：

| 客户端 | 地址配置 | 凭据配置 |
| --- | --- | --- |
| Option / Swap / Ticker / Message | `OTC_API_BASE_URL`：后端主机根地址，客户端追加 `/admin-api/...` | `OTC_API_SECRET`，以及既有 GOATS 签名配置 |
| GOATS agent / 快速询价 parser | `GOATS_BASE_URL`：GOATS 主机根地址，客户端规范化 `/api` 前缀 | `GOATS_CLIENT_ID`、`GOATS_CLIENT_SECRET`、`GOATS_EXTAPP_SALT`、`GOATS_OPT_AGENT_ID`、`GOATS_OPT_AGENT_SUB_ID` |
| 保留的独立标的查询配置 | `SECURITIES_INSTRUMENT_URL`：完整查询 URL；现役 ticker 走上面的 TickerClient | `SECURITIES_INSTRUMENT_KEY` |

真实地址和凭据使用业务方提供的值；保持 `DRY_RUN_BACKEND=false` 才会发出真实写请求。不需要修改节点代码。本地 mock 验证只证明调用链和响应契约，不等于真实后端业务验收。

切换后还需把 State 中的 `room_id`、`user_id`、消息及订单标识替换为真实测试环境数据，并按实际后端请求记录和业务结果重新验收。

## 9. 节点目录

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
