# Harness 评测台

黄金集真源为 `tests/datasets/biz/` 与 `tests/datasets/intent/`。
统一评测入口为 `python -m harness run`，默认请求已启动的 `http://127.0.0.1:8000`。
Harness 不启动 app 或 mock_api，不修改服务配置，不连接数据库准备消息。

## 黄金集执行

```bash
python -m harness run --group biz --backend mock
python -m harness run --group intent --backend mock
python -m harness run --group all --backend mock
python -m harness run --file tests/datasets/biz/swap_prod.jsonl --case ai_trade_assist_prod_swap_order_case_1 --backend java
```

| 参数 | 含义 |
|---|---|
| `--group biz|intent|all` | 选择数据集，缺省 biz；指定文件时按目录推断 |
| `--file` | 选择文件，可重复；支持混合 biz 与 intent，显式单组不得跨组 |
| `--case` | 选择用例 ID，可重复；任一 ID 未命中即报错 |
| `--backend mock|java` | 后端声明，已有 app 须配置对应接口，缺省 mock |

mock 模式先启动 `mock_api` 并将 app 配置指向它。Java 模式使用已配置的 Java 接口及
`EVAL_USER_ID`、`EVAL_ROOM_ID` 授权身份，不核验 Java 内部下游。
后端切换通过服务启动配置完成，CLI 不切换正在运行的服务。
服务不可用或启用 dry-run 时停止评测，不创建临时服务。

数据层缺省传入 `robot_version="V2"`、`existing_command="0"`，显式版本包括 V1、null 和空串保持原值。
此默认值仅适用于评测输入，不改变 app 的 V1 缺省规则。
冻结意图调用解析节点，快速样例调用入口节点，需要引用上一轮回复的用例和业务集调用主图。
冻结意图通过不代表 Java 业务联调通过。

Python 同步完成意图与业务确定性评分，不调用 Judge，不等待平台 Rule。
缺少有效期望或未执行的已标注轮次不能通过。评分规则见 [测试指南](../docs/testing/README.md)。

## 报告与平台记录

逐条结果立即追加到 `results.jsonl`，批次收尾生成 `summary.json` 与 `report.md`。
汇总保留请求用例数、已记录数、未执行数和跳过数，PASS 率使用完整请求分母。

- Windows：系统临时目录下的 `aigc-langgraph-tmp/harness/<run-id>/`
- Linux：`/opt/work-file/code-tmp/aigc-langgraph-tmp/harness/<run-id>/`

启动时打印完整路径。运行报告不得提交仓库。

Langfuse 追踪由 `ENABLE_LANGFUSE` 和项目凭据控制，批次结束执行 flush。
本地结果不因上传失败而改变，关联 ID 与入队状态不证明平台入库。
CLI 追踪不自动生成 Dataset Experiment。
[平台 webhook](../docs/langfuse/remote-experiment-webhook.md) 通过内部适配器复用同一 HTTP 执行器和本地评分，
将结论写入 SDK Experiment 与 Score，不另设评测标准。

## 调试工具

```bash
python -m harness doctor
python -m harness node-run --data <节点样本目录>
```

`doctor` 检查已有服务的 `/health` 与 `/ready`。
`node-run` 为节点调试入口，不增加黄金集验收层，写节点禁止自动回放。
HTTP 调试使用 `--transport http` 与环境变量 `NODE_RUN_API_KEY`，详见
[节点调试指南](../docs/development/nodes-run.md)。

## 模块职责

| 模块 | 职责 |
|---|---|
| `golden.py` | 黄金文件选择、加载及平台投影 |
| `multi_turn.py`、`intent_runner.py` | 主图多轮与冻结意图 HTTP 执行 |
| `http_evaluation.py` | CLI 与平台共用的执行入口 |
| `intent_scoring.py`、`evaluation.py`、`differ.py` | 本地确定性评分 |
| `run_reports.py`、`reporting.py` | 逐条留档、汇总及 Markdown 报告 |
| `langfuse_client.py`、`remote_experiment.py` | 可选追踪与平台触发适配 |
| `node_registry.py`、`node_runner.py` | 节点展示和安全回放，契约真源在 `app/node_execution/catalog.py` |
