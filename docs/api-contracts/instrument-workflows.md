# 标的推断与排序工作流接口

本接口供 Java 的 `InstrumentApiSearchHelper` 调用，复用现有 FastAPI 进程。Java 继续负责数据库搜索、候选选择及业务处理，企微主图不直接编排标的工具。

2026-10-10 调整定稿：Java 不修改源码，仅通过现有后台配置 URL、超时和重试次数。Python 工作流执行失败返回 HTTP 500，整体超时返回 504；成功和正常空分支契约保持不变。原计划中的“执行失败返回 HTTP 200”和“Java 新增状态及输出校验”不再适用。

## 实现与部署

- 根目录 `instrument_inference/`、`instrument_ranking/` 各含 `models.py`、`workflow.py`、`api.py`。
- 四份 git 提示词位于 `app/prompts/instrument/`。原 YAML 保留；仅将输出 XML/JSON 格式约束迁移到 Pydantic 契约，原业务规则继续生效。
- 启动时编译两张独立图，每次请求使用新 State，不使用 checkpointer。推断先去空、去重，三个模型分支并行，全部完成后检查错误并合并；排序先按 `windCode` 去重，再调用一次模型。
- `PromptSpec.state_schema` 可指定独立 TypedDict，默认仍是 `AgentState`。工具 spec 不进入主图注册表。
- 复用 `LLM_MODEL_STANDARD`、`LLM_PROVIDER`、模型地址和密钥；工具温度 0.1、关闭思考、零重试，结构化调用显式 `function_calling` 和 `include_raw=True`。
- 根模型预算默认为一次，推断 HTTP 入口设为三次，排序一次，空输入零次；并行共享同一计数对象，嵌套 scope 不扩大已有预算。
- 包发现已包含两个新包；现有 `app.prompts` 的 `**/*.md` 资源规则覆盖四份提示词；CI Ruff/mypy 范围已扩展。

本地启动使用 8201。以下命令仅在该 PowerShell 进程覆盖配置，不修改 `.env`：

```powershell
$env:OTC_API_BASE_URL = 'http://127.0.0.1:48081'
# 仅工具开发调试可关闭主图 checkpointer；生产仍遵守原主图配置要求。
$env:USE_MYSQL_CHECKPOINTER = 'false'
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8201
```

交互式 OpenAPI：`http://127.0.0.1:8201/docs`；机器契约：`http://127.0.0.1:8201/openapi.json`。

## 请求

公共信封保留 `inputs`、`response_mode`、`user`；`response_mode` 默认且仅允许 `blocking`，`user` 为可选字符串，用于观测。直连 Python 使用 `Content-Type: application/json`，不复制 Dify Bearer Token。

| POST 路径 | 必填 inputs | 可选 inputs |
|---|---|---|
| `/instrument-inference/v1/workflows/run` | `list: string` | `transactionTypes: string = "[]"`、`inferencePrompt: string = ""` |
| `/instrument-ranking/v1/workflows/run` | `list: string`、`keyword: string` | `predictedInsFamily: string = ""`、`expectedTransactionType: string = ""` |

`list` 是 JSON 列表的字符串，不能直接传数组；`transactionTypes` 同样是 JSON 列表字符串。外层字段类型错误或必填缺失返回 422。字符串无法解码为列表时沿用 YAML 回退为空列表。

推断示例：

```json
{
  "inputs": {
    "list": "[\"0700.HK腾讯\",\"沪铜12月\",\"华泰柏瑞沪深300ETF\"]",
    "transactionTypes": "[]",
    "inferencePrompt": ""
  },
  "response_mode": "blocking",
  "user": "ai-trading-assistant"
}
```

排序示例：

```json
{
  "inputs": {
    "list": "[{\"windCode\":\"0700.HK\",\"insShtDesc\":\"腾讯控股\",\"insFamily\":\"EQUITY\",\"tradableNow\":true,\"hasPermission\":true,\"transactionTypes\":[\"港股\"]}]",
    "keyword": "0700腾讯",
    "predictedInsFamily": "EQUITY",
    "expectedTransactionType": "港股"
  },
  "response_mode": "blocking",
  "user": "ai-trading-assistant"
}
```

PowerShell 调用示例：

```powershell
$body = @{
  inputs = @{ list = (@('0700.HK腾讯', '沪铜12月') | ConvertTo-Json -Compress) }
  response_mode = 'blocking'
  user = 'instrument-manual'
} | ConvertTo-Json -Depth 8 -Compress
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8201/instrument-inference/v1/workflows/run' -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 70
```

## 响应

```json
{
  "workflow_run_id": "88a18385-1665-4a8f-9f8c-ecfc9cd43f73",
  "task_id": "88a18385-1665-4a8f-9f8c-ecfc9cd43f73",
  "data": {
    "id": "88a18385-1665-4a8f-9f8c-ecfc9cd43f73",
    "workflow_id": "instrument-inference",
    "status": "succeeded",
    "outputs": {
      "result": [{"orgStr":"0700.HK腾讯","keywords":[{"id":"opaque-id","keyword":"0700.HK","isFull":true}]}],
      "insFamily": "{\"0700.HK腾讯\":\"EQUITY\"}"
    },
    "error": null,
    "elapsed_time": 1.5,
    "total_tokens": 100,
    "total_steps": 6,
    "created_at": 1791599917,
    "finished_at": 1791599919,
    "model_requests": 3,
    "usage": {"input_tokens":80,"output_tokens":20,"total_tokens":100}
  }
}
```

上例输出与用量为简化展示。`id` 是不透明关键词标识；去前导零副本与原关键词共享 ID，保留原 YAML 行为。`insFamily` 仍为 JSON 字符串，值为 `EQUITY/FUND/FUTURE/INDEX` 或无法确定时的空字符串。

| 情况 | HTTP / outputs |
|---|---|
| 推断成功 | 200 / `result` 为关键词对象数组，`insFamily` 为 JSON 字符串 |
| 推断空输入 | 200 / 仅 `{"result":[]}` |
| 排序成功 | 200 / `{"result":["0700.HK"]}`；模型正常过滤无匹配时为数组 `[]` |
| 排序空候选 | 200 / `{"result":"[]"}`，字符串类型是原 YAML 兼容要求 |
| streaming 或其它非 blocking 模式 | 400 |
| 缺少必填字段、字段类型错误 | 422 |
| 模型异常、截断、结构化解析失败、图执行异常 | 500 / `data.status="failed"`、`outputs={}`、非空 `data.error` |
| 工具整体超时 | 504 / failed 信封，`data.error` 含 `workflow_timeout` |

失败不会再次请求模型，不会把异常伪装成空候选成功。`usage` 是模型已返回的实际用量；上游在响应前失败时可能为零，不能据此断言上游未计费。`model_requests` 是实际模型 HTTP POST 尝试次数，包括失败请求。正常推断总步骤 6，排序 2，空分支 1。

每个进入图执行的请求生成独立运行 UUID，保留在响应体的 `workflow_run_id`、`task_id` 和 `data.id`；移除连字符得到 32 位 `trace_id`，通过 `X-Trace-Id` 响应头返回，并用于 Python 日志与 Langfuse。成功、执行失败和整体超时均保留这些标识。Java 不新增业务日志或标识提取代码；现有 HTTP 集成日志在 `save_log=1` 时保存响应体、响应头及 HTTP 状态，通过其中的运行标识与 Python 关联。验收 HTTP 500/504 时以 `httpStatusCode` 和响应体判断，不能仅依据集成日志的 `transactionStatus`（原实现按是否发生 HTTP 客户端异常设置该值）。

## Java 行为与超时

本次 `InstrumentApiSearchHelper` 源码改动已撤销。原 Java 两个入口先检查 HTTP 状态，非 200 直接抛入现有异常处理；HTTP 200 按原方式读取 `data.outputs`。不新增 `data.status` 检查或严格输出校验，因此 Python 必须将执行失败映射为 500，不能用 HTTP 200 的 failed 信封代替。正常 Top 5、同公司且同品种补回、数据库搜索与展示保持原实现；知识库工具未改动。

| 层级 | 超时 |
|---|---:|
| 单次模型请求 | 20 秒 |
| Python 单工具整体（含观测接入） | 60 秒 |
| Java 单工具 HTTP 建议配置 | 70 秒；当前 dev 库实测仍为 30 秒 |
| 网关（如有） | 至少 80 秒 |
| Java 业务入口手工客户端（推断、排序串行） | 160 秒 |

本次不调整企微主图等待 Java 的现有 15 秒配置或主图总期限，因此不构成企微完整嵌套链路验收。

## 开发配置与切换

### 当前联调环境（2026-10-10 16:14，Asia/Shanghai）

最新联调使用 Java `127.0.0.1:48081`、`dev` profile 和 `goats_ai_trading_dev` 数据库。该库沿用原配置 ID 43（推断）和 39（排序），用户已直接将两条 URL 改为本地 8201 的对应工具路径；均启用，超时 30000ms、重试 0、保存日志 1。该库没有本次新增的 47、48 配置，不能套用下方历史 dev1 切换步骤。

本次主图 → Java → 本地推断 → Java 搜索候选 → 本地排序 → Java 待补参卡片链路成功，意图、会话及节点审计也已只读核验。它不包含真实交易提交、确认或成交，不代表失败分支或全量业务验收通过。工具响应中的 trace ID 不证明 Langfuse 已入库。

当时 Python 进程采用 `ENVIRONMENT=staging`、`OTC_API_BASE_URL=http://127.0.0.1:48081`、`BACKEND_TIMEOUT_SECONDS=50`、`REQUEST_TIMEOUT_SECONDS=80`；这些是进程覆盖，不是配置文件默认值。Java 当前 30 秒期限短于 Python 工具整体 60 秒期限，故障及超时分支验收前仍需核对预算。

切换或回退前，应按实际 Java profile 与数据库重新读取两类配置并记录原 URL、请求头、启用状态和超时；确认每类唯一启用后操作，禁止凭旧 ID 推断当前目标。共享库内的回环 URL 仅适用于与 Python 同机运行的 Java。本次不修改共享配置。

### 历史 dev1 快照（非当前环境操作步骤）

2026-10-10 已核对开发库 `goats_ai_trading_dev1`，Dify 系统 ID 11，系统编号 `178759361703213`。
初次交付时因开发环境联调请求未暂停，仅新增禁用配置。用户随后已在后台自行切换；2026-10-10 核对新 ID 47、48 启用，旧 ID 43、39 禁用，每组唯一启用。主代理只读核验配置和日志。

| 类型 | 旧 ID / 状态 / 超时 | 新 ID / 状态 / 超时 | 新 URL |
|---|---|---|---|
| `DIFY_LLM_INSTRUMENT_INFERENCE` | 43 / 禁用 / 30000ms | 47 / 启用 / 70000ms | `http://127.0.0.1:8201/instrument-inference/v1/workflows/run` |
| `DIFY_LLM_RERANK_CODES` | 39 / 禁用 / 30000ms | 48 / 启用 / 70000ms | `http://127.0.0.1:8201/instrument-ranking/v1/workflows/run` |

新配置均为 POST、重试 0、保存日志 1，仅 JSON Content-Type，无 Authorization。旧配置保留原地址、请求头及超时，启用状态已由用户切换为禁用。每个系统编号＋数据类型目前仍只有一条启用记录。

知识库开关 `swap_order_use_instrument_knowledge_tool` 在该库中没有未删除记录；Java 空值判断结果为 false。本轮未插入或修改该开关。验收前须重新核对当时原值；若需显式设 false，先记录原始状态，包括“原记录不存在”。

后续重复切换时，先暂停共享联调请求，再按现有后台页面执行：

以下步骤及回退仅适用于已核对仍采用上述 47/48 配置的 dev1 环境，不适用于当前 dev 库的 43/39 原记录改 URL 方案。

1. 核对本地 Java 48081 和 Python 8201 均就绪；Java 使用原有实现，无需部署本次源码变更。远端 Java 不能使用本机回环 URL。
2. 再次记录旧配置状态/超时和知识库开关，确认暂停其他联调请求。
3. 逐组禁用旧 ID 43、39，启用对应新 ID 47、48；每组切换后确认只有一条启用配置。
4. 验收期间使知识库开关有效为 false；核对测试群、用户与授权对手范围。
5. 从 Java 实际业务入口使用缺参请求验收，客户端等待 160 秒。必须有精确查询未命中且召回多候选的样本，证明“推断 → 数据库搜索 → 排序”；另核对精确命中、单候选短路。
6. 记录可能产生的草稿/询价记录，禁止补齐到可以真实提交交易的参数；结束后恢复知识库开关原值/原缺失状态。

失败回退：暂停请求，逐组禁用新 ID 47、48、恢复旧 ID 43、39 为启用；不删除任何 API 配置；确认每组唯一启用并使用原 Dify 路径复核。旧 30000ms 超时从未修改，无需重写。新配置应保留禁用，以便排查。

## 本次验收证据

证据目录：`C:/opt/work-file/code-tmp/aigc-langgraph-tmp/instrument-migration-20261010/`。以下是实际执行结果，不是全量验收结论。

| 检查 | 实际结果 / 证据 |
|---|---|
| Ruff / mypy | 通过；mypy 覆盖 app、harness 和两个新包；AGENTS/skills 同步检查通过，`static-checks.json` |
| 导入、图编译、安装资源 | 通过；`uv build` 构建 wheel，隔离目录安装后导入两个包、编译图、加载四份提示词；`installed-check.txt`；初版两条 OpenAPI 路径导出至证据目录 `openapi.json`，更新后的 500/504 声明见 `java-zero-change/openapi.json` |
| Java 恢复与编译 | `InstrumentApiSearchHelper.java` 相对 HEAD 无差异，其余已有差异未改；恢复后以 JDK 17.0.12 编译相关模块并跳过测试，退出 0；`java-zero-change/java-restore.json`、`java-zero-change/java-compat.json` |
| 初版 Python 手工检查（历史证据） | 21 项通过；失败状态码已被本次 500 契约替代，当前状态码以补充检查为准。原生图＋模拟模型 HTTP 传输，覆盖 422/400、损坏列表、空分支类型、去重、三分支并行、原文/市场词/前导零/期货日期、3/1/0 次、解析失败、截断、模型 503、嵌套额度、整体超时；`manual-http.json`、`manual-additional.json`；另核对单分支失败等待其余分支、模型正常空数组、无 checkpointer 和工具 spec 不注册。超时检查将内存期限缩短至 50ms，未实际等待 60 秒 |
| 初版 Java 手工检查（已撤回实现的历史证据） | 原新增校验的 17 项检查保留在 `java-manual.log`，不作为当前原版 Java 的验收结论；当前兼容性见下两项 |
| 当前 Python HTTP 契约 | 22 项通过：两条真实图的模型异常、解析失败、截断、单次模型超时及图异常返回 500；整体超时返回 504；成功、空分支、400/422、模型次数、用量及运行标识保留；OpenAPI 声明 500/504 信封。模型 HTTP 使用内存模拟传输，整体期限仅在检查中缩短为 30ms；`java-zero-change/python-http.json`、`java-zero-change/openapi.json` |
| 当前原版 Java 兼容性 | 恢复并编译后的原类通过 19 项检查：接收上述 Python 响应，两个入口拒绝 500/504，成功/空输出兼容，失败时不清空原排序候选；并核对新增校验方法已不存在和完整 URL 行为。HTTP API、对手提示和交易时段仅内存隔离，无网络或业务写入；`java-zero-change/java-compat.json`、`java-zero-change/java-compat.log`。不等同于 Spring 业务入口联调 |
| 配置切换 | 初次交付的禁用状态见 `config-record.json`；用户已切换为新 ID 47、48 启用、旧 ID 43、39 禁用，唯一性及 70000ms/零重试/保存日志已核对；当前证据 `java-entry-success.json` |
| Java 实际业务入口正常链路 | 用户经本地 Java 48081 发起，消息 ID `202610100001`。推断日志 `1143986`：配置 47、HTTP 200、模型 3 次、10549 tokens、14.324 秒；数据库召回 25 个候选后，排序日志 `1143988`：配置 48、HTTP 200、模型 1 次、6052 tokens、14.906 秒。两个 URL 均指向本地 Python 8201，运行标识与响应头 trace 对应。最终展示 Top 5 并生成待补参草稿；`java-entry-success.json` |
| 真实模型工具调用 | 5 次 HTTP 调用成功；包含两个空分支和下表三个非空调用；`live-python-http.json` |

真实模型非空调用：

| 用例 | run ID | 请求数 / tokens / 耗时 | 观察结果 |
|---|---|---|---|
| 批量推断，含重复输入、名称＋代码、12 月沪铜、ETF 管理人消歧和指数类型 | `88a18385-1665-4a8f-9f8c-ecfc9cd43f73` | 3 / 10851 / 13.923 秒 | 去重后 5 组；沪铜得到 CU2612；指定管理人得到单一 ETF 代码，未指定得到多候选；类型分别含 EQUITY/FUTURE/FUND/INDEX |
| 精确代码 `00700` | `9fb1bd14-994e-48e0-89b2-54d8949a96fa` | 1 / 3850 / 13.899 秒 | 返回候选中的 0700.HK、700.HK，过滤无关代码 |
| 复合查询 `2612螺纹钢` | `4b08f8d8-d67b-418e-a64b-3653ee63130b` | 1 / 3849 / 14.269 秒 | 只返回 RB2612.SHF，过滤同月份沪铜与数字巧合股票 |

待验收和限制：

- Java 48081 的本次正常链路已验收，用户请求生成草稿 `H-20261010-9604085248`，数据库状态 `NEED_COMPLETE_PARAMS`；数量、方向和交易对手为空，GOATS 订单标识为空。该草稿需要纳入验收记录，未自动删除或补参。正式测试对手范围核对、精确代码命中/单候选短路、Java 实际入口的 HTTP 500/504 故障路径以及失败回退实操仍待验收。主代理未发起 Java 业务请求。
- Langfuse 服务 `127.0.0.1:3000` 连接被拒绝，SDK 导出失败，CLI 查询也失败；trace 入库、父子关系与服务端用量审计仍待验收，不能将响应中的 trace ID 视为入库成功。`langfuse-read.txt`、`python-server.stdout.log` 保留证据。空分支本次耗时 11–13 秒，包含不可用观测服务的开销；观测恢复后需复核，不作性能达标声明。
- 文档全仓检查被原有 `tmp/langfuse-pr-preflight/pytest` 访问权限阻塞；此外仓库已有的 `docs/langfuse/developer-manuals/` 删除造成旧链接缺失。本次未恢复或修改这些用户改动；改用 Git 文件清单在内存中限定扫描后，发现 12 项既有断链，新增接口文档与索引零违规；JSON 示例均可解析。
- 未新增或修改测试脚本，未运行 pytest、业务数据集评测或压测；两个仓库原有未提交改动及原 YAML 保留。未 push、未创建 PR。

实现参考：[LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)、[Langfuse trace ID](https://langfuse.com/docs/observability/features/trace-ids-and-distributed-tracing)、[Langfuse trace 审计要求](https://langfuse.com/docs/observability/best-practices)。
