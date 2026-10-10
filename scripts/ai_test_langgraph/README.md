# LangGraph 自动化测试工具

> **状态：deprecated（ADR 0024 D6，2026-09-17）。** 唯一 gate 是 `harness/`（`python -m harness run`），
> 三种 fixture 方言的现役加载器是 `harness/golden.py`；本目录保留本地运行、节点标注和
> 节点回归工作台，不作为发布 gate；页面节点回归与 `python -m harness node-run` 共用执行器。

这套工具默认按文件名排序读取本仓库 `tests/fixtures/categories/` 直属的全部 JSONL，并调用
`aigc-langgraph` 暴露的 `POST /v1/workflows/run`。同时兼容旧版
`name/send_text` 回归 JSONL。它不依赖 Dify App ID、Service
API Key 或 Console 账号，也不会执行部署、推送代码或修改工作流。

当前默认分类数据为 6 份、389 条顶层用例。CLI 未传 `--data` 和工作台数据集发现
均使用上述范围，不递归扫描子目录或 `old_typing/` 等历史归档。显式 `--data` 可重复
传入多个文件，仍按传入顺序加载并兼容原有格式。

| 文件 | 用途 |
|---|---|
| `langgraph_direct_regression.py` | 运行一个或多个 JSONL 数据集并生成 Markdown/JSON 报告 |
| `wecom_dataset_push.py` | 运行回归并预览或推送企微报告 |
| `yaml_to_jsonl.py` | 复用 Dify 测试工具已校验的 YAML 转 JSONL 能力 |
| `automation_runner_server.py` | 启动本地串行任务队列、历史报告、节点标注和节点回归 API |
| `automation_runner.html` | 本地任务配置、运行状态、历史报告、节点标注和节点回归页面 |

## 前置条件

先启动 `aigc-langgraph`：

```bash
cd ../aigc-langgraph
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

在 `aigc-langgraph/.env` 至少配置测试身份：

```dotenv
LANGGRAPH_BASE=http://127.0.0.1:8000
EVAL_USER_ID=<测试用户 ID>
EVAL_ROOM_ID=<测试群 ID>
ENVIRONMENT=development
```

测试工具使用临时 `message_id`，不会创建或删除 Java 消息记录。LangGraph 在
`ENVIRONMENT=development` 时跳过 `persist_intent`；`staging` 和 `production`
仍会严格执行消息意图写回，失败时正常返回错误。

可选配置为 `LANGGRAPH_BOT_NAME`、`LANGGRAPH_EVAL_GUID`、
`LANGGRAPH_OPTION_COUNTERPARTIES` 和 `LANGGRAPH_SWAP_COUNTERPARTIES`。后两个值必须
是 JSON 数组；未配置时沿用 Dify 回归工具的开发环境默认候选（期权 3 个、互换 5 个）。
为兼容已有 `.env`，对应的 `DIFY_*` 名称仍可作为后备值读取。

## 用例编写格式

用例文件必须是 UTF-8 编码的 JSONL：一行一个完整 JSON 对象，不能把同一个对象拆成多行。

### 常用格式：分类回归用例

```json
{"id":"case-030","name":"case-030","caseNo":"case-030","category":"option_close/place","type":"positive","source":"json/golden_case_raw/期权平仓-查持仓后平仓","scene":"第 1 轮 - 查询可平持仓","send_text":"我想平仓","at_bot":true,"expected":{"product_type":"option_close","intent":"close_order_query"},"response_contains":["序号","单号","合约编号"],"response_not_contains":["互换订单"],"sub_scenes":[{"scene":"第 2 轮 - 选择第三笔限价全平","send_text":"第三笔，限价10，全平","at_bot":false,"quote_previous":true,"expected":{"product_type":"option_close","intent":"close_order_request"},"response_contains":["场外期权平仓","限价","10","确认平仓"],"response_not_contains":["互换订单"]}]}
```

- `name`、`send_text`：必填，分别表示用例名称和首轮输入。
- `id`、`caseNo`：用于数据追溯和编号筛选，分类数据集通常与 `name` 保持一致。
- `category`、`type`、`source`：用于分类和来源追溯。
- `scene`、`at_bot`：描述当前轮次以及是否模拟 `@机器人`；`at_bot` 默认首轮为
  `true`、后续轮次为 `false`。
- `expected`：支持断言 `product_type`、`intent`、`winners`（或 `winner`）及
  `needs_hitl`。
- `response_contains`：全部子串都必须包含；`response_not_contains`：全部子串都不得包含。
- `response_contains_any`：候选子串中任一命中即通过；全部未命中只报告一次组级失败。
  三类文本断言都接受换行字符串或列表，沿用去首尾空白、忽略空行的归一化；空候选不增加约束。
- `sub_scenes`：按数组顺序执行后续轮次，每轮可独立配置上述字段；
  `quote_previous: true` 引用紧邻上一轮回复，`false` 不引用，未填写时兼容为引用首轮
  回复。

任一轮请求或断言失败后，该用例停止执行剩余轮次；不同顶层 JSONL 用例之间不会共享
`conversation_id` 或引用内容。

### 支持格式：黄金集 conversation 用例

```json
{"id":"swap-confirm-001","category":"swap/confirm","expected":{"product_type":"swap","intent":"place_order_request"},"conversation":[{"raw_content":"000001 买入5000股 限价18.12","quote_desc":""},{"raw_content":"确认下单","quote_desc":"引用上一轮订单卡片"}]}
```

- `id`：必填且在文件内唯一，加载后同时作为 `name` 和 `caseNo`。
- `conversation`：按数组顺序执行全部 `raw_content`，所有轮次共用一个
  `conversation_id`。
- `quote_desc`：只作为人工说明和引用开关，不会发送给 LangGraph；后续轮次中该值
  非空时，脚本自动引用上一轮的实际回复。
- 顶层 `expected` 只用于首轮断言；需要逐轮断言时应使用上面的常用格式。
- `expected.output` 仅作为黄金预期说明，当前工作台不判断其语义。

### 支持格式：Ticker 单轮用例

```json
{"id":"tk001","category":"ticker/complete_code","raw_content":"00700.HK","expected":{"winner":"00700.HK","needs_hitl":false}}
```

## 命令行回归

在 `aigc-langgraph/` 仓库根目录运行：

```bash
# 离线自检
python scripts/ai_test_langgraph/langgraph_direct_regression.py --self-test

# 只校验并列出用例，不访问 LangGraph
python scripts/ai_test_langgraph/langgraph_direct_regression.py --dry-run --limit 3

# 运行一个数据集
python scripts/ai_test_langgraph/langgraph_direct_regression.py \
  --data tests/fixtures/categories/swap_prod_acceptance_data.jsonl \
  --limit 3

# 按传入顺序连续运行多个数据集
python scripts/ai_test_langgraph/langgraph_direct_regression.py \
  --data tests/fixtures/categories/golden_option_close_case.jsonl \
  --data tests/fixtures/categories/swap_test_fuzzy_target_recog_data.jsonl
```

仍支持 `--name`、`--case-no`、`--keyword`、`--shuffle --seed`、`--timeout`、
`--retries`、`--throttle-ms`、`--no-report` 和 `--report-dir`。默认只允许访问
localhost 或已知 dev 域名；隔离测试环境需明确传入 `--allow-non-dev`。

每条顶层用例自动生成独立的 `conversation_id`，该用例的所有 `sub_scenes` 共用它，
并继续引用主场景回复。返回值从 `data.outputs.reply_text` 读取；完整
`data.outputs` 会写入报告，便于排查 LangGraph 的结构化结果。报告默认输出到：

```text
docs/testing/test-reports/YYYYMMDD/
├── langgraph-direct-YYYYMMDD-HHMMSS.md
└── langgraph-direct-YYYYMMDD-HHMMSS.json
```

## 本地任务页面

```bash
# 仅允许本机访问
python scripts/ai_test_langgraph/automation_runner_server.py

# 监听所有网络接口，并允许回归任务访问隔离环境中的非 dev 地址
python scripts/ai_test_langgraph/automation_runner_server.py --no-open --allow-non-dev --host 0.0.0.0 --port 9000
```

默认打开 `http://127.0.0.1:9001`。监听 `0.0.0.0` 时，请使用服务器的实际 IP 和端口访问，
并只在可信网络中开放对应防火墙端口。页面提供四种测试方式：

- “自由对话”可直接发送自定义指令，首轮自动建立 `conversation_id`，后续消息沿用
  同一会话；支持引用 LangGraph 回复、模拟 `@机器人`，并展示完整 `outputs`。
- “回归队列”可选择多个仓库内 JSONL 数据集，任务按加入顺序串行执行。
- “节点回归”自动递归发现 `tests/fixtures/nodes/**/*.jsonl`，可选择 Direct 或受保护的
  HTTP 节点接口执行；任务后台运行并逐条展示 PASS / FAIL / SKIP、字段级差异和 JSON 报告。
  HTTP 密钥只从工作台服务端环境读取，不下发浏览器；节点数量和文件列表均不硬编码。
- “历史报告标注”读取 `docs/testing/test-reports/` 下已有 JSON 报告；打开用例后，
  “节点标注”页签会按轮次从 Langfuse **只读**获取业务节点。可按产品、节点类型和
  回归能力筛选，选择字段级或对象级期望值后保存到
  `tests/fixtures/nodes/<product>/<node>.jsonl`。

节点 observation 必须来自当前 `.env` 配置的 Langfuse 项目。工作台只读取
Trace/Observation，不创建或修改 Langfuse 数据；标注结果仅写入本地 JSONL。
历史报告若生成时未启用 Langfuse，或对应 Trace 已过保留期，仍可查看执行日志，但无法
加载节点详情。写后端节点始终禁止单节点回放；当前已开放的节点可运行：

```bash
python -m harness node-run --data tests/fixtures/nodes
NODE_RUN_API_KEY='<key>' python -m harness node-run \
  --transport http \
  --base-url http://127.0.0.1:8000 \
  --data tests/fixtures/nodes
python -m harness node-run \
  --data tests/fixtures/nodes/swap/swap_place_order.jsonl \
  --mock \
  --out .harness-runs/swap-place-order-mock-report.json
```

`--mock` 只在 harness 内替换 fixture 声明的 LLM / Ticker 外部返回，仍执行真实
`swap_place_order` 节点逻辑；不会进入 `swap_place_order_submit`，因此不会调用下单接口。

开发环境启用 LangFuse 后，用例详情会在 `conversation_id` 右侧显示可点击的
`tracing_id`。每条顶层用例生成一个名为“测试任务名称-用例 ID”的父 Trace，
多轮请求作为其子链路；自由对话仍按每次请求生成独立 Trace。

自由对话的连接和身份配置在会话建立后锁定，点击“新对话”即可重新配置。页面不会
在服务端保存对话记录。使用 `--no-open` 可禁止自动打开浏览器，使用 `--host` 可修改
监听地址，使用 `--port` 可修改端口。仅在确认目标隔离测试环境安全时使用
`--allow-non-dev`，它会让回归队列访问非 localhost/已知 dev 地址。

## 企微报告

不加 `--send` 时只预览，不发送网络通知：

```bash
python scripts/ai_test_langgraph/wecom_dataset_push.py --limit 3
```

确认后添加 `--send`，Webhook 从 `WECOM_TEST_WEBHOOK` 或
`WECOM_BOT_WEBHOOK` 读取。也可用 `--report <markdown>` 推送已有报告。

## 离线验证

联合验收覆盖业务测试与工作台脚本测试。Windows 命令如下；保留仓库对真实后端
`tests/api` 的排除及现有条件跳过。离线通过表示本地自动化通过，真实模型准确率及
真实业务交易仍需在对应环境中单独验收。

```powershell
$env:PYTHONUTF8 = '1'
$env:ENABLE_LANGFUSE = 'false'
.\.venv\Scripts\python.exe -m pytest tests/ scripts/ai_test_langgraph/ -v -W error -rs
.\.venv\Scripts\python.exe -m ruff check app/ tests/ scripts/ai_test_langgraph/
.\.venv\Scripts\python.exe scripts/ai_test_langgraph/langgraph_direct_regression.py --dry-run --limit 3
.\.venv\Scripts\python.exe scripts/ai_test_langgraph/langgraph_direct_regression.py --self-test
.\.venv\Scripts\python.exe scripts/ai_test_langgraph/automation_runner_server.py --self-test
```

各辅助入口也可分别自检：

```bash
python scripts/ai_test_langgraph/test_langgraph_direct_regression.py
python scripts/ai_test_langgraph/langgraph_direct_regression.py --self-test
python scripts/ai_test_langgraph/wecom_dataset_push.py --self-test
python scripts/ai_test_langgraph/yaml_to_jsonl.py --self-test
python scripts/ai_test_langgraph/automation_runner_server.py --self-test
```
