# Harness（评测台）

三种运行方式，设计见 ADR 0002 / ADR 0014 / ADR 0029：

| 方式 | 入口 | 执行 | 数据 |
|---|---|---|---|
| HTTP 回归 | `python -m harness run` | 经本地 `/v1/workflows/run` 驱动 LangGraph，与 `app/` 解耦 | `tests/datasets/biz/`（依赖 Java） |
| 意图级 | `scripts/langfuse/langfuse_eval.py --local tests/datasets/intent` | 冻结用例经 `/v1/nodes/run` 执行联合解析；拒绝验收（及回放）用例经主图 HTTP + `mock_api` | `tests/datasets/intent/` |
| 节点回归 | `python -m harness node-run` | 默认 `--transport direct` 经同一 NodeExecutor 适配 JSON 状态并执行单个节点；`http` 调 `/v1/nodes/*` | 节点级 fixture 已退役（`--data` 自备目录） |

## 模块

| 模块 | 职责 |
|---|---|
| `cli.py` | `python -m harness <doctor\|run\|node-run>` 入口 + 报告渲染 |
| `golden.py` | fixture 唯一加载器，各方言归一化为 `GoldenCase` |
| `multi_turn.py` | 多轮 case 的 HTTP 执行（quote 引用 / 早停 / at_bot 透传） |
| `differ.py` / `references.py` / `scenario_inputs.py` | 字段级 diff、文本 / 结构化断言；断言与输入里的订单引用只从实际卡片解析 |
| `intent_context.py` / `intent_runner.py` | 意图集冻结 / 回放模式判定；HTTP 联合解析 runner |
| `evaluators/` | Langfuse Code Evaluator（文本断言、意图、标的、拒绝），清单见 `scripts/langfuse/definitions/evaluators.json` |
| `node_registry.py` / `node_annotations.py` | 节点展示与回放策略；节点契约真源是 `app/node_execution/catalog.py`，Langfuse 提供来源 observation 与 Dataset/Experiment；写节点禁止自动回放 |
| `node_fixtures.py` / `node_runner.py` / `node_mocks.py` | 节点 fixture 持久化与执行；`--mock` 仅模拟 `parse_instruction` 的外部模型边界 |
| `http_tape.py` | 私有工具 HTTP 录放（`scripts/run_with_http_tape.py`），回放不回退到真实网络 |
| `langfuse_client.py` / `token_tracker.py` / `report_history.py` | Langfuse SDK 封装、token 成本、本地历史报告索引 |
| `case_generator/` | LLM 对抗式 paraphrase 生成 C 桶候选（`python -m harness.case_generator`） |

## 用法

```bash
python -m harness doctor          # 环境体检（/health /ready）
# HTTP 回归：必须提供授权测试身份（--user-id / --room-id 或 EVAL_USER_ID / EVAL_ROOM_ID），默认端口 8000
python -m harness run --help      # --backend real|mock|dry-run、--checkpoint none|mysql
python -m harness node-run --data <节点 fixture 目录>
# 调已启动后端的受保护接口（密钥只通过环境变量传入；HTTP 模式不支持 --mock）
NODE_RUN_API_KEY='<key>' python -m harness node-run --transport http \
  --base-url http://127.0.0.1:8000 --data <节点 fixture 目录>
```

节点回归：带写副作用或 fixture 里 `replay.enabled != true` 的节点显示 `SKIP`，不计入失败；
未在注册表中的节点报错并计为 FAIL；全为 SKIP 时退出码 2，保留待验收状态。

业务和意图批量评分都使用明确字段与文本断言，不调用 Judge。`--no-judge` 只作旧命令兼容；缺期望或未执行轮必须失败。写类结构化参数标注缺口单列待验收，不把当前 PASS 当作完整参数覆盖。

平台实验：`python -m scripts.langfuse.langfuse_eval --local tests/datasets/intent --base-url http://127.0.0.1:8201`；需先启动同版本 LangGraph 服务。平台 Dataset 可用 `--dataset-version <带时区ISO时间>` 固定版本。本地 Java 验收仍使用 `scripts/local_eval.py` 准备授权测试消息。

节点闭环：`python -m scripts.langfuse.node_dataset publish|export|run --help`。发布需要审阅者及来源 Trace/Observation，导出只写待复核快照，回归共用 `node_runner` 的字段比较；全为 SKIP 或没有样本时退出码 2，不能当作通过。

Langfuse 必須与服务端使用同一项目。可信本地服务设置 `TRUST_INBOUND_TRACEPARENT=true`，根与子 Observation 共用本次用例 Session。报告的 `trace_status` 检查返回关联，`score_status=enqueued` 仅表示排入 SDK 队列；实际入库仍需通过平台查询核对。模型调用没有重试；观测导出超时单独配置 `LANGFUSE_TIMEOUT_SECONDS` 和 `LANGFUSE_FLUSH_AT`。
