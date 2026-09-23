# Langfuse 功能与评测链路使用指南

本文说明 `aigc-langgraph` 如何使用 Langfuse 管理黄金数据集、执行评测、自动打分，以及从失败用例追踪到 LangGraph 节点。

## 1. 功能入口

| 功能 | 用途 |
|---|---|
| Tracing | 查看 Trace 及内部 LangGraph、LLM、工具 Observations |
| Sessions | 聚合同一多轮会话的 Trace |
| Prompts / Playground | 管理和调试 Prompt |
| Scores | 统一查看自动与人工评分 |
| Evaluators | 管理自动评分逻辑和 Evaluation Rules |
| Human Annotation | 人工复核 Trace、Observation 或 Session |
| Datasets | 管理测试输入、期望输出和 metadata |
| Experiments | 执行 Dataset，并比较输出、Trace 和 Scores |
| Users / Alerts | 按用户聚合记录、配置告警 |

## 2. 对象与评测链路

```text
Dataset
└── Dataset Item：input + expectedOutput + metadata
    └── Experiment Item：一次用例执行结果
        └── Trace
            ├── root Observation：用例根输出
            └── child Observations：LangGraph 节点、LLM、工具调用

本地 SDK Evaluator ───────────────────────────────> 自动 Score
Online Evaluation Rule ─> 项目级 Evaluator ──────> 自动 Score
Human Annotation ─────────────────────────────────> 人工 Score
Session ──────────────────────────────────────────> 聚合同一多轮会话
```

- Dataset 保存测试标准，Experiment 保存本次执行结果。
- Trace 和 Observations 保存执行过程，Score 保存评价结果。
- Evaluator 是项目级评分逻辑，本身不绑定 Dataset。
- Evaluation Rule 定义过滤条件。新的 Observation 入库并满足条件时，Langfuse 自动运行 Evaluator。通常所说的“绑定了谁”，指的是 Rule 匹配谁。

## 3. Dataset 数据结构

Dataset Item 的三个字段全部由 `scripts/langfuse/upload_golden_to_langfuse.py` 写入，Langfuse 不会自动补充任何字段：

- `input`：首轮输入与 `sub_scenes` 多轮输入，键为 `send_text`、`at_bot`、`quote_previous`（有子场景时才有 `sub_scenes`）。
- `expectedOutput`：首轮断言与 `sub_scenes` 多轮断言。**只写非空字段**，所以各用例的键不完全一致：`expected`、`response_contains`、`response_contains_any`、`response_not_contains` 中保留有值的那些，另外总有 `sub_scenes`。
- `metadata`：固定 11 个字段，见 3.1。

### 3.1 metadata 字段

`metadata` 由 `upload_golden_to_langfuse.py::_metadata()` 构造，共 11 个字段，全部来自本地 fixture 或由脚本派生：

| 字段 | 来源 | 用途 |
|---|---|---|
| `id` | fixture 的 `id`（无则用 `caseNo`） | 用例编号；同时是 Dataset Item 的 ID，定位单条用例、回写结果都靠它 |
| `caseNo` | fixture 的 `caseNo`，缺失回退 `id` | 原始用例编号，用于和本地 fixture 对账 |
| `name` | fixture 的 `name`，缺失回退 `id` | 用例名，列表展示用 |
| `category` | fixture 的 `category`，缺失回退文件名 | 用例分类，按业务域统计通过率 |
| `test_function` | 由 `category` 复制 | 供 `langfuse_eval.py --filter` 匹配，决定这一轮跑哪一批用例 |
| `type` | fixture 的 `type` | 区分正例 / 负例（`positive` / `negative`）。**A 方言没有这个字段，上传后是空串** |
| `source` | fixture 的 `source` | 用例来源（`business_seed`、`llm_paraphrase`），追溯用例怎么来的。**A 方言没有这个字段，上传后是空串** |
| `scene` | fixture 的 `scene` | 场景标签。**A 方言没有这个字段，上传后是空串** |
| `overview` | 脚本生成 | 多行概览：ID / 类别 / 类型 / 来源 / 期望路由 + 逐轮对话。**本地 Judge 直接用它作为“题目”拼进评分提示词**，是这里最有实际作用的一个字段 |
| `tags` | 脚本生成 | `[category, source]`，列表里的分类标签；`source` 为空时会带一个空串，如 `["option_inquiry_case", ""]` |
| `turns` | 脚本计算 | 轮次数，用于分辨单轮 / 多轮用例 |

> A 方言指 `tests/fixtures/categories/*.jsonl`，B 方言指 `tests/fixtures/unified_golden.jsonl`；只有 B 方言带 `type` / `source` / `scene`。另外，早期用旧版脚本上传的 Dataset（如 `otc-option-golden`，350 条，2026-05 创建）只有 8 个字段，没有 `name` / `caseNo` / `scene`，需要当前字段集就用当前脚本重新上传。

下面是一条真实上传后的 Item（取自 Dataset `golden_option_inquiry_case` 的 `case-024`，`response_contains` 已截断）：

```json
{
  "input": {
    "send_text": "快速询价：参与型看涨，000002.SZ，80/80，3M",
    "at_bot": false,
    "quote_previous": false,
    "sub_scenes": []
  },
  "expectedOutput": {
    "sub_scenes": [],
    "response_contains": ["-----场外期权询价详情-----", "标的代码：000002.SZ"]
  },
  "metadata": {
    "id": "case-024",
    "caseNo": "case-024",
    "name": "case-024",
    "category": "option_inquiry_case",
    "test_function": "option_inquiry_case",
    "type": "",
    "source": "",
    "scene": "",
    "tags": ["option_inquiry_case", ""],
    "turns": 1,
    "overview": "ID: case-024\n类别: option_inquiry_case\n用例类型: \n来源: \n期望路由: product_type=, intent=\n对话:\n  第1轮: send_text=快速询价：参与型看涨，000002.SZ，80/80，3M; 无引用"
  }
}
```

多轮用例通过 `input.sub_scenes[n]` 与 `expectedOutput.sub_scenes[n]` 按下标对应。上传脚本不转换成另一套 `turns` 或 `expected_scope` 结构。

上传结果的字段值取决于 `--source` 指向的方言：`tests/fixtures/categories/*.jsonl`（A 方言）的 `category` 形如 `option_inquiry_case`；`tests/fixtures/unified_golden.jsonl`（B 方言）的 `category` 形如 `option/inquiry`，并会带上 `type` 与 `source`。

## 4. 首次配置

以下命令均在 `aigc-langgraph/` 目录执行。先确认 `.env` 已配置 Langfuse 地址和密钥。

### 4.1 上传 Dataset

```powershell
# 预览
python scripts/langfuse/upload_golden_to_langfuse.py --source tests/fixtures/categories/golden_option_inquiry_case.jsonl --dataset-name golden_option_inquiry_case --mode overwrite --dry-run

# 上传
python scripts/langfuse/upload_golden_to_langfuse.py --source tests/fixtures/categories/golden_option_inquiry_case.jsonl --dataset-name golden_option_inquiry_case --mode overwrite
```

`overwrite` 会先删除该 Dataset 的现有 Items，适合首次替换旧格式；仅新增或更新用例时使用 `--mode append`。

`--source` 指向单个 JSONL 时，只上传该文件中的用例；指向目录时，会读取目录下全部 `*.jsonl`，并将所有用例
上传到 `--dataset-name` 指定的同一个 Dataset。脚本不会按文件名自动创建多个 Dataset。

如果希望一个 JSONL 文件对应一个 Dataset，需要分别执行。例如在 Windows CMD 中：

```cmd
python scripts\langfuse\upload_golden_to_langfuse.py --source tests\fixtures\categories\golden_option_inquiry_case.jsonl --dataset-name golden_option_inquiry_case --mode append

python scripts\langfuse\upload_golden_to_langfuse.py --source tests\fixtures\categories\golden_option_open_case.jsonl --dataset-name golden_option_open_case --mode append

python scripts\langfuse\upload_golden_to_langfuse.py --source tests\fixtures\categories\golden_option_close_case.jsonl --dataset-name golden_option_close_case --mode append
```

`append` 通过稳定的 Item ID 执行新增或更新，不会删除远端已有但本次文件中不存在的 Item；需要让远端 Item 集合
与本地文件完全一致时，显式使用 `--mode overwrite`。

### 4.2 配置 Online 自动评分

对所有 Dataset 生效：

```powershell
# 预览
python scripts/langfuse/upload_evaluators.py --dry-run

# 上传 Evaluator 和 Rule
python scripts/langfuse/upload_evaluators.py --apply
```

只对指定 Dataset 生效时增加过滤参数：

```powershell
python scripts/langfuse/upload_evaluators.py --dataset-name golden_option_inquiry_case --apply
```

脚本从 `definitions/evaluators.json` 同步三个项目级 Evaluator，并创建对应的 Evaluation Rules：

- 不传 `--dataset-name`：Rule 只过滤 `isExperimentItemRootSpan=true`，匹配所有 Dataset 的 Experiment Item 根输出。
- 传入 `--dataset-name`：Rule 再增加 `datasetId` 条件，只匹配该 Dataset。
- 普通请求、`--local` 评测和子 Observations 不会触发。

三个 Evaluator 分别检查 `response_contains`、`response_contains_any` 和 `response_not_contains`，产生三个 Boolean
Score。重复同步时，同名且相同则跳过，不同则更新；改名会新建，旧记录不会自动删除。全局 Rule 与 Dataset 专属
Rule 同时启用会重复评分，应在 `Evaluators → Evaluation Rules` 中只保留一种作用范围。

### 4.3 配置人工评分口径

```powershell
# 预览
python scripts/langfuse/upload_score_configs.py --dry-run

# 上传
python scripts/langfuse/upload_score_configs.py --apply
```

脚本读取 `scripts/langfuse/definitions/score-configs.json`。当前包含用例级人工指标
`human_business_verdict`，取值为 `正确`、`错误`、`待确认`。

当前人工标注采用“分类结论 + Score Comment”：分类值用于统计，Comment 用于补充判断依据。Comment 在 Langfuse UI 中是可选字段，Score Config 的描述只能提示、不能强制填写。若需要独立、可查询的文本评分维度，可再增加 `TEXT` Score Config；文本值限制为 1–500 个字符。参见 Langfuse 官方的 [UI 人工评分](https://langfuse.com/docs/evaluation/evaluation-methods/scores-via-ui) 和 [Score 数据模型](https://langfuse.com/docs/evaluation/scores/data-model)。

Score Config 只定义评分口径，不会创建 Annotation Queue、分配人员或把 Experiment 结果入队。

## 5. 执行 Experiment

以 `case-022` 为例：

```powershell
# 预览用例
python scripts/langfuse/langfuse_eval.py --dataset golden_option_inquiry_case --ids case-022 --concurrency 1 --dry-run

# 正式执行
python scripts/langfuse/langfuse_eval.py --dataset golden_option_inquiry_case --ids case-022 --concurrency 1

# 不运行 LLM Judge，仅执行 Experiment；Online Evaluation Rules 仍会异步评分
python scripts/langfuse/langfuse_eval.py --dataset golden_option_inquiry_case --ids case-022 --concurrency 1 --no-judge
```

不传 `--ids` 时执行 Dataset 中的全部 Item：

```powershell
python scripts/langfuse/langfuse_eval.py --dataset golden_option_inquiry_case --concurrency 1
```

常用参数：

| 参数 | 含义 |
|---|---|
| `--ids case-022` | 只执行一个 Item |
| `--ids case-021,case-022` | 执行多个指定 Item，使用逗号分隔 |
| 不传 `--ids` | 执行过滤后的全部 Item |
| `--concurrency 1` | 最多同时执行一个 Item，即串行执行 |
| `--concurrency 3` | 最多同时执行三个 Item；单个多轮用例内部仍顺序执行 |
| `--limit 10` | 只执行过滤后的前十个 Item |
| `--dry-run` | 只预览选中的 Item，不执行 LangGraph 和评分 |
| `--no-judge` | 不注册 `judge_by_deepseek`；仍执行 Experiment 和 Online Evaluation Rules |

调试、写操作、后端容易限流或模型配额较小时使用 `--concurrency 1`；只读评测可根据后端与模型容量逐步提高。

执行后：

- 默认由 `judge_by_deepseek` 产生 `otc-option-judge` Score；指定 `--no-judge` 时不注册该 Evaluator。
- Online Evaluation Rules 异步产生三个文本断言 Score。
- 业务人员可补充 `human_business_verdict`，不会覆盖自动 Score。

在 Dataset 的 `Experiments` 页签打开名称类似 `option-eval-YYYYMMDD-HHMMSS` 的记录。

> **截图位置 3（待补）**：Experiment 列表和 `case-022` 的 Experiment Item。

### 5.1 Environment 与评分查看位置

Environment 用于区分数据来源。部分名称由 Langfuse SDK 固定使用，不是本项目自定义：

| Environment | 含义 | 默认是否出现在 Scores 主列表 |
|---|---|---|
| `default` | 未显式配置环境的普通 Trace；当前 `--local` 评测通常也在这里 | 是 |
| `production` / `staging` / `development` | 应用通过 `LANGFUSE_TRACING_ENVIRONMENT` 配置的业务环境 | 是 |
| `sdk-experiment` | Langfuse SDK 执行 Dataset Experiment 时使用的官方内部环境 | 否 |
| `langfuse-code-eval` | Langfuse-managed Code Evaluator 自身的执行 Trace | 否 |
| `langfuse-llm-as-a-judge` | Langfuse-managed LLM Judge 自身的执行 Trace | 否 |

本项目通过 `--dataset` 执行后，用例 Trace、`otc-option-judge` 和
三个文本断言 Score 都属于本次 Experiment，主要在 Dataset 的 `Experiments` 对比页查看。它们关联的用例
Observations 使用 `sdk-experiment` 环境；Scores 主列表默认隐藏该内部环境，因此列表中看不到并不代表 Score 未生成。

需要在 Scores 主列表查看时，展开左侧过滤面板，显式选择 `Environment = sdk-experiment`，再按 Score 名称过滤。
Code Evaluator 返回的业务 Score 仍关联被评测的 `sdk-experiment` Observation；`langfuse-code-eval` 只用于查看
Evaluator 自身的执行日志、耗时和错误。

使用 `--local` 时不会创建 Dataset Experiment。此模式产生普通 Trace，通常落在 `default` 或
`LANGFUSE_TRACING_ENVIRONMENT` 指定的环境中，Score 直接从 Tracing 或 Scores 页面查看。

### 5.2 Score Source

Scores 页面的 `Source` 表示 Score 的产生方式，与 Dataset 和 Environment 无关：

| Source | 含义 | 本项目中的例子 |
|---|---|---|
| `EVAL` | 由 Langfuse 的评测流程产生，包括 Experiment Evaluator、Code Evaluator 和 LLM Judge | Dataset Experiment 中的 `otc-option-judge`，以及三个 Online Code Evaluator Score |
| `ANNOTATION` | 由人员在 Langfuse UI 或 Annotation Queue 中人工评分 | `human_business_verdict` |
| `API` | 应用、脚本或 CI 通过 Langfuse API/SDK 主动写入 | `--local` 模式调用 `create_score()` 写入的 Judge Score，或业务侧用户反馈 |

`Source` 由 Score 的创建路径自动设置，不能通过 Score Config 指定。同一个 Score 名称如果通过不同路径写入，可能
同时出现不同 Source。例如 `otc-option-judge` 在 Dataset Experiment 中属于 `EVAL`，在当前 `--local` 模式中属于
`API`。筛选 `EVAL` 只查看自动评测结果，筛选 `ANNOTATION` 只查看人工结论。

## 6. 查看链路与排查问题

```text
失败 case
→ Experiment Item
→ Trace
→ root Observation
→ 异常或输出不符的 child Observation
→ 对照 Expected Output、实际 output 和 Score comment
```

查看步骤：

1. 从 Dataset 的 `Experiments` 页签打开本次 Experiment。
2. 按 case ID 找到 Experiment Item，并进入关联 Trace。
3. 展开 root Observation，定位 LangGraph、LLM 或工具调用。
4. 检查输入、输出、错误和耗时，再对照 Expected Output 与 Scores。
5. 多轮问题继续检查 Session；需要业务复核时，在用例根输出记录一个 `human_business_verdict`。

| 现象 | 检查位置 |
|---|---|
| Dataset 中没有 Experiment Item | 是否使用 Dataset 模式；`--local` 不创建 Dataset Experiment |
| Experiment 有 Score，但 Scores 主列表没有 | 显式选择 `Environment = sdk-experiment`；该内部环境默认被隐藏 |
| 路由或 intent 错误 | intent 相关 Observation |
| ticker 错误 | ticker 子图、候选结果和后端校验调用 |
| 回复错误 | 业务节点、后端响应和 render Observation |
| 文本断言 Score 缺失 | Evaluator/Rule 是否启用，`datasetId` 和根 Observation 条件是否匹配 |
| Score 与结果不一致 | `expectedOutput`、实际 output 和 Evaluator comment |
| 多轮上下文错误 | Session ID、thread ID 和各轮 Trace |
| 用例 Trace 与 LangGraph Trace 分离 | `traceparent`、`trust_inbound_traceparent` 和 `langfuse_trace_id` |

Online Evaluator 异步执行，Experiment 完成后 Score 可能稍后显示。自托管环境还需启用 evaluator worker/dispatcher。

## 7. `scripts/langfuse/` 脚本

| 文件 | 用途 |
|---|---|
| `upload_golden_to_langfuse.py` | 上传 categories / intent golden case 到 Dataset（`--suite` 默认按路径判定，metadata 带 `suite` / `backend`）|
| `upload_evaluators.py` | 读取集中定义，按套件（`--suite` 或 dataset 前缀 `intent-`）同步 Code Evaluators 和全局或指定 Dataset 的 Online Rules |
| `upload_score_configs.py` | 读取集中定义，全量同步人工 Score Configs |
| `langfuse_eval.py` | 执行 Dataset Experiment 或本地评测（`--suite intent` 不跑 Judge，trace tags 带套件名）|
| `upload_prompt_to_langfuse.py` | 把 git 的提示词推到 Langfuse（单轮实验用；**不从 Langfuse 拉回**）|
| `_definitions.py` | 读取并校验本地 JSON 定义，不单独执行 |
| `_public_api.py` | 上传脚本共用的 Public API 客户端，不单独执行 |

## 8. 两套件：意图集 / 业务集分离

意图识别只依赖 LLM，业务操作（询价 / 下单 / 平仓）依赖 Java 后端与授权账号。两类用例放在
不同目录、上传到不同 Dataset、绑定不同 Evaluator，互不污染：

| 维度 | 意图集（intent） | 业务集（business） |
|---|---|---|
| fixture 目录 | `tests/fixtures/intent/<product>.jsonl` | `tests/fixtures/categories/*.jsonl` |
| 用例形态 | A 方言子集：逐轮 `expected.{product_type, intent}`，**不写** `response_*` | A 方言：卡片文本断言（`response_contains` 等） |
| 期望值来源 | 各子图 `models.py` 的意图枚举（lint 校验） | Java 真实回复 |
| 运行后端 | `mock_api`（`metadata.backend=mock`） | 真后端 / staging |
| Dataset 命名 | `intent-<product>` | `business-<文件名>`（历史 `golden_*` 命名仍按 business） |
| 自动评分 | `det_intent_match_pass`（`harness/evaluators/intent_match.py`）+ 标的识别子集 `det_instrument_match_pass`（`harness/evaluators/instrument_match.py`） | `det_required_text_pass` / `det_required_any_text_pass` / `det_forbidden_text_pass` + `otc-option-judge` |
| LLM Judge | 不跑（脚本强制 `no-judge`） | 跑 |
| Trace tags | `eval, intent` | `eval, business` |

`upload_evaluators.py` 按套件绑定 Rule：`--dataset-name intent-swap` 只创建
`golden-intent-match:intent-swap`；`--dataset-name business-*` / 历史命名只创建三个文本断言 Rule。
不要给意图集绑全局（all-datasets）Rule，否则 intent_match 会对业务集 Item 产生大量失败 Score。

### 8.1 意图集从业务集派生

```bash
# 统计：哪些 case 缺逐轮 intent 标注
python scripts/derive_intent_fixtures.py --dry-run
# 写草稿到 tmp/intent_drafts/<product>.jsonl（未标注轮 intent 为空并带 review.pending）
python scripts/derive_intent_fixtures.py --out tmp/intent_drafts
# 业务方 review 补齐 intent 后，只把已完整标注的 case 写进意图集
python scripts/derive_intent_fixtures.py --source tmp/intent_drafts --only-labeled --out tests/fixtures/intent
python scripts/check_fixture_consistency.py --verbose
```

脚本只做确定性搬运：`product_type` 沿用原标签或按 category 前缀推导，`intent` 只沿用已有标注，
不用模型猜；lint 会拒绝空 intent、非法枚举、文本断言和非 `intent-` 前缀的 id。

### 8.1a 标的识别子集（`tests/fixtures/intent/swap_instrument.jsonl`）

标的识别是意图集里的独立数据集：LangGraph 只提取用户原文里的标的表达（`placeOrderWindCode` 逐字保留）
和市场限定（`placeOrderTransactionType`），权威识别由 Java 完成，所以它同样只调 LLM + mock 后端。
`expected.instruments[i]` 给出**原文表达的任一候选**与**交易品种候选**，`instrument_match` 按订单无序匹配：

```bash
# 从三份 swap 业务集派生（订单数以卡片 标的代码 行为准；--ignore-token 只影响抽取，不改 send_text）
python scripts/derive_instrument_fixtures.py --dry-run --ignore-token "11125测试短名（张天琪专用）" --ignore-token "聚鸣价值精选" --ignore-token "临沂阿凡提"
python scripts/derive_instrument_fixtures.py --only-reviewed --ignore-token "…" --out tests/fixtures/intent/swap_instrument.jsonl
python scripts/langfuse/upload_golden_to_langfuse.py --source tests/fixtures/intent/swap_instrument.jsonl --dataset-name intent-swap_instrument --mode overwrite
python scripts/langfuse/upload_evaluators.py --dataset-name intent-swap_instrument --apply   # 绑 intent_match + instrument_match
python scripts/langfuse/langfuse_eval.py --dataset intent-swap_instrument --concurrency 3
```

抽取规则与人工复核口径见 `tests/fixtures/intent/README.md`；`reference.backend_codes` 保留后端码仅供核对。

### 8.2 执行

```bash
# 意图集：终端 1 起 mock_api，终端 2 以 OTC_API_BASE_URL 指向 mock 起应用
python scripts/langfuse/upload_golden_to_langfuse.py --source tests/fixtures/intent/option_close.jsonl --dataset-name intent-option_close --mode overwrite
python scripts/langfuse/upload_evaluators.py --dataset-name intent-option_close --apply
python scripts/langfuse/langfuse_eval.py --dataset intent-option_close --concurrency 3
# 本地不上传：路径含 intent/ 自动判定套件
python scripts/langfuse/langfuse_eval.py --local tests/fixtures/intent --concurrency 3

# 业务集：真后端 / staging，写类流程串行
python scripts/langfuse/upload_golden_to_langfuse.py --source tests/fixtures/categories/swap_prod_data.jsonl --dataset-name business-swap_prod_data --mode overwrite
python scripts/langfuse/upload_evaluators.py --dataset-name business-swap_prod_data --apply
python scripts/langfuse/langfuse_eval.py --dataset business-swap_prod_data --concurrency 1
```

意图集 Experiment 命名为 `intent-eval-YYYYMMDD-HHMMSS`，业务集沿用 `option-eval-YYYYMMDD-HHMMSS`。
`--local` 模式下 A 方言用例没有 `expected.output`，Judge 期望由逐轮 `expected` + 文本断言拼成
（`build_expected_text`），不再是空串。

### 8.3 CI 集成：意图集不依赖后端，业务集只在开发环境跑

- 意图集的评分逻辑与 Langfuse Online Rule 是同一份源码（`harness/evaluators/`），`langfuse_eval.py --local`
  对 `suite=intent` 直接在本地执行 `intent_match` / `instrument_match`，不需要 Langfuse、Java、GOATS；
  `--fail-under 0.95` 低于门槛退出码 1，`--report` 写 JSON 摘要
- `.github/workflows/intent-eval.yml`：runner 上起仓库内 `mock_api`（GOATS 22 + Java 10 端点假实现）顶替后端，
  LLM 网关走 secrets `QWEN_API_BASE` / `QWEN_API_KEY`。PR 触碰 `app/prompts/**`、路由/意图节点、评估器、
  `tests/fixtures/intent/**` 时自动跑；Actions 页可手动 Run workflow 并改 `fixture` / `limit` / `fail_under`
  （首次可用 `fail_under=0` 只出基线报告，再定门槛）
- 未配置 secrets 时：PR 触发只做 fixture lint，评估步骤跳过并打 warning（Step Summary 注明"已跳过"，不算通过）；
  手动触发直接失败。配好 secrets 后无需改 workflow，门槛自动生效
- 启用 Langfuse 时 `--local` 也会把每个评估器的 score（`det_*`）写回 trace；`--no-judge` 的兜底评分现在按
  `reply-check` 名写回（此前误用 `otc-option-judge`）
- 业务集（`categories/`）依赖 Java 后端与授权账号，只在开发 / staging 环境用 `--dataset business-*` 或
  `scripts/local_eval.py` 跑，不进 CI；依赖矩阵见 `docs/testing/README.md` §一a
