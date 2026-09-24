# Harness（评测台）

三种运行方式，设计见 ADR 0002 / ADR 0014 / ADR 0029：

| 方式 | 入口 | 执行 | 数据 |
|---|---|---|---|
| HTTP 回归 | `python -m harness run` | 经本地 `/v1/workflows/run` 驱动 LangGraph，与 `app/` 解耦 | `tests/fixtures/biz/`（依赖 Java） |
| 意图级 | `scripts/langfuse/langfuse_eval.py --local tests/fixtures/intent` | 冻结用例进程内只跑意图子链（`intent_runner.py`）；拒绝验收（及回放）用例走主图 + `mock_api` | `tests/fixtures/intent/` |
| 节点回归 | `python -m harness node-run` | 默认 `--transport direct` 进程内调单个节点；`http` 调 `/v1/nodes/*` | 节点级 fixture 已退役（`--data` 自备目录） |

## 模块

| 模块 | 职责 |
|---|---|
| `cli.py` | `python -m harness <doctor\|run\|node-run>` 入口 + 报告渲染 |
| `golden.py` | fixture 唯一加载器，各方言归一化为 `GoldenCase` |
| `multi_turn.py` | 多轮 case 的 HTTP 执行（quote 引用 / 早停 / at_bot 透传） |
| `differ.py` / `references.py` / `scenario_inputs.py` | 字段级 diff、文本 / 结构化断言；断言与输入里的订单引用只从实际卡片解析 |
| `intent_context.py` / `intent_runner.py` | 意图集冻结 / 回放模式判定；只跑意图子链的 runner |
| `evaluators/` | Langfuse Code Evaluator（文本断言、意图、标的、拒绝），清单见 `scripts/langfuse/definitions/evaluators.json` |
| `node_registry.py` / `node_annotations.py` | 节点展示与回放策略；节点契约真源是 `app/node_execution/catalog.py`，Langfuse 只用于取标注 |
| `node_fixtures.py` / `node_runner.py` / `node_mocks.py` | 节点 fixture 持久化与执行；`--mock` 目前只支持 `swap_place_order` |
| `http_tape.py` | 私有工具 HTTP 录放（`scripts/run_with_http_tape.py`），回放不回退到真实网络 |
| `langfuse_client.py` / `token_tracker.py` / `report_history.py` | Langfuse SDK 封装、token 成本、本地历史报告索引 |
| `case_generator/` | LLM 对抗式 paraphrase 生成 C 桶候选（`python -m harness.case_generator`） |

## 用法

```bash
python -m harness doctor          # 环境体检（/health /ready）
# HTTP 回归：必须提供授权测试身份（--user-id / --room-id 或 EVAL_USER_ID / EVAL_ROOM_ID），默认端口 8000
python -m harness run --help      # --backend real|mock|dry-run、--checkpoint none|mysql、--include-unified
python -m harness node-run --data <节点 fixture 目录>
# 调已启动后端的受保护接口（密钥只通过环境变量传入；HTTP 模式不支持 --mock）
NODE_RUN_API_KEY='<key>' python -m harness node-run --transport http \
  --base-url http://127.0.0.1:8000 --data <节点 fixture 目录>
```

节点回归：带写副作用或 fixture 里 `replay.enabled != true` 的节点显示 `SKIP`，不计入失败；
未在注册表中的节点报错并计为 FAIL。

LLM Judge 评估主入口是 `scripts/langfuse/langfuse_eval.py`（见根 `CLAUDE.md`「关键命令」）。
