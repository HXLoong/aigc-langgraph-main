# LangGraph 自动化测试工具

这套工具直接读取本仓库 `tests/fixtures/*.jsonl`，并调用
`aigc-langgraph` 暴露的 `POST /v1/workflows/run`。同时兼容旧版
`name/send_text` 回归 JSONL。它不依赖 Dify App ID、Service
API Key 或 Console 账号，也不会执行部署、推送代码或修改工作流。

| 文件 | 用途 |
|---|---|
| `langgraph_direct_regression.py` | 运行一个或多个 JSONL 数据集并生成 Markdown/JSON 报告 |
| `wecom_dataset_push.py` | 运行回归并预览或推送企微报告 |
| `yaml_to_jsonl.py` | 复用 Dify 测试工具已校验的 YAML 转 JSONL 能力 |
| `automation_runner_server.py` | 启动本地串行任务队列和页面 API |
| `automation_runner.html` | 本地任务配置、运行状态和日志页面 |

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
是 JSON 数组；未配置时沿用 Dify 回归工具的开发环境默认候选。为兼容已有 `.env`，
对应的 `DIFY_*` 名称仍可作为后备值读取。

## 命令行回归

在 `aigc-langgraph/` 仓库根目录运行：

```bash
# 离线自检
python scripts/ai_test_langgraph/langgraph_direct_regression.py --self-test

# 只校验并列出用例，不访问 LangGraph
python scripts/ai_test_langgraph/langgraph_direct_regression.py --dry-run --limit 3

# 运行一个数据集
python scripts/ai_test_langgraph/langgraph_direct_regression.py \
  --data tests/fixtures/golden.jsonl \
  --limit 3

# 按传入顺序连续运行多个数据集
python scripts/ai_test_langgraph/langgraph_direct_regression.py \
  --data tests/fixtures/golden.jsonl \
  --data tests/fixtures/golden_ticker_2026-05.jsonl
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
python scripts/ai_test_langgraph/automation_runner_server.py
```

默认打开 `http://127.0.0.1:9001`。页面提供两种测试方式：

- “自由对话”可直接发送自定义指令，首轮自动建立 `conversation_id`，后续消息沿用
  同一会话；支持引用 LangGraph 回复、模拟 `@机器人`，并展示完整 `outputs`。
- “回归队列”可选择多个仓库内 JSONL 数据集，任务按加入顺序串行执行。

自由对话的连接和身份配置在会话建立后锁定，点击“新对话”即可重新配置。页面不会
在服务端保存对话记录。使用 `--no-open` 可禁止自动打开浏览器，使用 `--port` 可修改
端口。

## 企微报告

不加 `--send` 时只预览，不发送网络通知：

```bash
python scripts/ai_test_langgraph/wecom_dataset_push.py --limit 3
```

确认后添加 `--send`，Webhook 从 `WECOM_TEST_WEBHOOK` 或
`WECOM_BOT_WEBHOOK` 读取。也可用 `--report <markdown>` 推送已有报告。

## 离线验证

```bash
python scripts/ai_test_langgraph/test_langgraph_direct_regression.py
python scripts/ai_test_langgraph/langgraph_direct_regression.py --self-test
python scripts/ai_test_langgraph/wecom_dataset_push.py --self-test
python scripts/ai_test_langgraph/yaml_to_jsonl.py --self-test
python scripts/ai_test_langgraph/automation_runner_server.py --self-test
```
