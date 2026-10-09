# 测试指南

本页是测试执行与失败定位入口。黄金数据格式见 [数据集说明](../../tests/datasets/README.md)，
执行器细节见 [Harness](../../harness/README.md)，测试身份准备见 [本地种子与授权边界](./local-backend-seed.md)。
进展和未完成项只在 [工作计划](../work-plan.md) 维护。

## 1. 两类正式验证

| 类型 | 入口 | 验证内容 |
|---|---|---|
| app 核心测试 | `python -m pytest` | 路由、状态、参数、来源、引用选择、出站请求、错误兜底和 app HTTP 契约 |
| 黄金数据集评测 | `python -m harness run` | 实际模型和业务链路输出是否满足 `tests/datasets/` 中的明确期望 |

不另设 mock 集成、真后端探针或真后端回归层。
`mock_api` 是可替换的外部接口 stub，`node-run` 是单节点调试工具，部署 smoke 是环境检查。
pytest 不维护 harness、辅助脚本、mock_api、平台或基础设施自身的测试。
静态检查不是额外的业务评测层。

## 2. app 核心测试

从仓库根目录运行，避免本地 `.env` 开启持久化或追踪：

```bash
# Linux / macOS / Git Bash
# 新入口规则专项
PYTHONUTF8=1 USE_MYSQL_CHECKPOINTER=false ENABLE_LANGFUSE=false python -m pytest tests/graph/test_entry_branches.py tests/graph/test_entry_route_guard.py -q
```

Windows PowerShell 先设置 `$env:PYTHONUTF8="1"`、`$env:USE_MYSQL_CHECKPOINTER="false"`、
`$env:ENABLE_LANGFUSE="false"`，再运行相同的 `python -m pytest ...`。
修改代码后先执行受影响路径，完整验收再运行 `python -m pytest tests/ -q`。
核心规则修复遵循 RED → GREEN，业务样本显式使用 V2 输入，不改变 app 的 V1 默认规则。
主图冒烟命令为 `PYTHONUTF8=1 USE_MYSQL_CHECKPOINTER=false ENABLE_LANGFUSE=false python -m pytest tests/test_smoke.py -q`。

必要静态检查：

```bash
ruff check app/ tests/ harness/ scripts/probe_goats/ scripts/langfuse/ scripts/goats_api_mock/
python -m mypy app/ harness/

```

### CI 执行内容

`.github/workflows/ci.yml` 由 main push、PR 和手动触发执行。

| Job | 内容 |
|---|---|
| fast · ruff + mypy + app 核心快速测试 | ruff；mypy；`pytest tests/ -k "not e2e"` |
| slow · app 核心全量测试 | fast 成功后执行 `pytest tests/`，包含隔离外部 IO 的 E2E |

两个 Job 使用统一占位配置，显式配置三类模型名，关闭 MySQL checkpoint 与 Langfuse。
CI 仅保留 ruff、mypy 和 app 核心 pytest，不执行五项一致性检查或平台 JS evaluator 自测。
黄金数据集评测通过 Harness 单独运行，支持全量、文件与用例选择，以及 mock 和 Java 后端；不进入 CI 自动执行。
CI 不调用真实模型、Java 或真实数据库。
静态检查可覆盖 harness 和脚本，但不为这些支撑工具维护独立 pytest。

## 3. 黄金集范围与后端

| 数据集 | 目录 | 执行方式 | 正式判定 |
|---|---|---|---|
| 业务集 | `tests/datasets/biz/` | 主图 HTTP，多轮引用取真实回复，外部后端 mock 或 Java | 本地参数／字段／卡片文本断言 |
| 意图集 | `tests/datasets/intent/` | 冻结输入调解析节点；快速样例调入口节点；需回放的样例走主图 | 本地产品／动作／入口及已标注标的断言 |

冻结意图不调用 Java 业务接口；即使选择 Java，也不能把解析节点通过当成 Java 联调通过。
回放意图和业务样例使用本次选择的外部后端；本项目不核验 Java 内部的下游环境。
所有黄金集都可能消耗真实模型请求，不进 CI 自动批量运行。

统一 CLI 只有四类 `run` 参数：

| 参数 | 作用 |
|---|---|
| `--group biz|intent|all` | 选择数据集分组，未指定文件时缺省 biz |
| `--file <路径>` | 指定现役文件，可重复；单组文件可自动推断 group |
| `--case <ID>` | 指定用例，可重复；任一 ID 未命中就报错 |
| `--backend mock|java` | 声明本次外部后端，已有 app 须配置对应接口，缺省 mock |

```bash
# 各组全量（Java 全量必须先获得明确授权）
python -m harness run --group intent --backend mock
python -m harness run --group biz --backend mock
python -m harness run --group all --backend mock

# 指定文件与单条用例
python -m harness run --file tests/datasets/biz/swap_prod.jsonl --backend mock
python -m harness run --file tests/datasets/biz/swap_prod.jsonl --case ai_trade_assist_prod_swap_order_case_1 --backend java
```

### 执行注意事项

- CLI 固定访问已启动的 `http://127.0.0.1:8000`，不启动或关闭 app、mock_api，不修改 `.env`。
- mock 评测先启动 `uvicorn mock_api.server:app --port 8099`，并将 app 的 `OTC_API_BASE_URL` 和 `GOATS_BASE_URL` 配置为 `http://127.0.0.1:8099` 后启动 app。
- Java 评测将 app 配置为实际 Java 接口；EVAL 身份、群、对手及持仓必须已获授权，不核验 Java 内部下游。
- Harness 不准备数据库消息。无数据库评测服务使用 `USE_MYSQL_CHECKPOINTER=false`、`MYSQL_URI=""`，已有服务改配置后需重新启动。
- 评测输入缺省使用 V2 和普通指令标记，显式版本及存量标记按数据集原值透传；app 缺省版本仍为 V1。
- `--file` 支持跨 biz／intent 混合文件；未指定 group 时推断为 all，显式单组不得跨组。
- mock 使用独立 stub，不读取 `expected` 来伪造通过，不保证全部真后端卡片断言匹配。

## 4. 本地确定性评分

正式结果在 Python 内同步得出，不需要 Node.js，也不等待 Langfuse 回传。

### 意图集

实现为 `harness/intent_scoring.py`：

- 按轮比较已标注的 `expected.product_type`、`intent`、`entry_branch`，字符串精确相等。
- `expected.instruments` 对订单进行无序、一对一匹配；每个标的的 `expression` 可列多个可接受表达。
  表达比较忽略空白并统一大小写，交易品种只接受已标注候选，不补证券代码。
- 缺少实际轮次、有已标注字段不匹配、标的遗漏或多出标的，判相应评分失败。
- 合并存在有效断言的评分项；没有任何可评分标注不能通过。不适用的标的评分不单独导致普通意图失败。

### 业务集

实现为 `harness/evaluation.py`、`differ.py`、`references.py`：

- 文本的 `response_contains` 必须全部命中，`response_contains_any` 至少一个命中，
  `response_not_contains` 不能命中；`response_blocks` 在指定卡片块内检查。
- `expected` 中明确声明的结构字段逐项比较；参数优先取实际提交投影。
  `$ref` 只从本轮真实引用解析订单／对手／持仓身份，缺失或歧义不能通过。
- 对 Java 契约允许数字字符串的十进制字段使用有限 Decimal 比较；整数、Boolean、身份、枚举和普通文本仍严格检查。
  不做业务单位换算、默认补齐或证券匹配。
- 节点错误、技术错误、前置时段失败和未执行轮次保留失败；Java `code=0` 或“有回复”不等于断言通过。
- 无差异且执行成功为 `PASS`；业务拒绝且无其它差异为 `REJECTED`，不计 PASS；其余为 `FAIL`。
  有字段标注不等于整个订单已完整覆盖，报告保留参数断言覆盖信息。

## 5. 报告与失败定位

CLI 逐条追加 `results.jsonl`，收尾写 `summary.json` 和 `report.md`。
Windows 使用系统临时目录下的 `aigc-langgraph-tmp/harness/<run-id>/`，
Linux 使用 `/opt/work-file/code-tmp/aigc-langgraph-tmp/harness/<run-id>/`，启动时打印完整路径。
汇总保留完整请求分母与未执行、跳过数量，跳过、外部阻塞或未执行不算通过。
运行报告不可提交仓库。

失败时依次检查：

1. 输入及 `entry_branch`：版本、@、快速／存量标记是否正确传递。
2. `product_type / intent` 和模型错误：区分网关／代理失败与解析／证据错误。
3. 实际提交参数与引用：核对原字段、来源账本、清洗记录、出站请求。
4. Java 原始回复：区分权限、缺对手／持仓、业务拒绝和真实输出差异。
5. 只对已定位问题做核心测试复现与相关用例复验；不改低 expected、不伪造 Java 卡片。

Langfuse 可以辅助追踪，上传故障不改变本地结果。
CLI 提供可选追踪并在收尾 flush，不自动创建 Dataset Experiment。
平台 webhook 复用同一执行与评分入口，通过 SDK Experiment 上传结果和 Score。
平台入库仍须核查，不以关联 ID 或 SDK 入队代替证据，详见 [Langfuse 链路](../langfuse/workflow-guide.md)。
