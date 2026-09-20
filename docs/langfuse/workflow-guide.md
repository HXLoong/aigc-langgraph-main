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

上传后的 Dataset Item 与 `tests/fixtures/categories/` 保持同一种结构：

- `input`：首轮输入和 `sub_scenes` 多轮输入。
- `expectedOutput`：首轮断言和 `sub_scenes` 多轮断言。
- `metadata`：case ID、分类、场景、来源和轮次数。

```json
{
  "input": {
    "send_text": "快速询价：欧式看涨，600519.SH，80%，1M",
    "at_bot": true,
    "sub_scenes": []
  },
  "expectedOutput": {
    "expected": {
      "product_type": "option",
      "intent": "new_inquiry",
      "winners": ["600519.SH"]
    },
    "response_contains": ["场外期权询价详情"],
    "response_contains_any": [],
    "response_not_contains": ["未搜索到相关标的信息"],
    "sub_scenes": []
  },
  "metadata": {
    "id": "case-022",
    "category": "option/inquiry"
  }
}
```

多轮用例通过 `input.sub_scenes[n]` 与 `expectedOutput.sub_scenes[n]` 按下标对应。上传脚本不转换成另一套 `turns` 或 `expected_scope` 结构。

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

### 4.2 配置 Online 自动评分

```powershell
# 预览
python scripts/langfuse/upload_evaluators.py --dataset-name golden_option_inquiry_case --dry-run

# 上传 Evaluator 和 Rule
python scripts/langfuse/upload_evaluators.py --dataset-name golden_option_inquiry_case --apply
```

脚本扫描 `scripts/langfuse/definitions/evaluators/*.json`，并为每项定义同步两类项目级配置：

1. `response-not-contains` Code Evaluator：定义如何检查禁止文本。
2. Evaluation Rule：定义何时自动运行该 Evaluator。

当前 Rule 的过滤条件是：

```text
datasetId = golden_option_inquiry_case
isExperimentItemRootSpan = true
```

因此，指定 Dataset 产生新的 Experiment Item 根 Observation 时，会异步执行 Evaluator，并写入
`det_forbidden_text_pass` Boolean Score。普通请求、`--local` 评测、子 Observations 和其他 Dataset 不满足该 Rule，不会触发。

Evaluator 从 Experiment 上下文读取 `expectedOutput.response_not_contains`，再检查根输出中的全部轮次；任一轮命中禁止文本即失败。

新增 Evaluator 时，增加一个 JSON 定义和对应的 Python 评分源码，无需修改上传脚本。重复上传时，本地定义是事实来源：内容相同则跳过，不同则更新。

### 4.3 配置人工评分口径

```powershell
# 预览
python scripts/langfuse/upload_score_configs.py --dry-run

# 上传
python scripts/langfuse/upload_score_configs.py --apply
```

脚本扫描 `scripts/langfuse/definitions/score-configs/*.json`。当前包含用例级人工指标
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
```

执行后：

- `judge_by_deepseek` 产生 `otc-option-judge` Score。
- Online Evaluation Rule 异步产生 `det_forbidden_text_pass` Score。
- 业务人员可补充 `human_business_verdict`，不会覆盖自动 Score。

在 Dataset 的 `Experiments` 页签打开名称类似 `option-eval-YYYYMMDD-HHMMSS` 的记录。

> **截图位置 3（待补）**：Experiment 列表和 `case-022` 的 Experiment Item。

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
| 路由或 intent 错误 | intent 相关 Observation |
| ticker 错误 | ticker 子图、候选结果和后端校验调用 |
| 回复错误 | 业务节点、后端响应和 render Observation |
| `det_forbidden_text_pass` 缺失 | Evaluator/Rule 是否启用，`datasetId` 和根 Observation 条件是否匹配 |
| Score 与结果不一致 | `expectedOutput`、实际 output 和 Evaluator comment |
| 多轮上下文错误 | Session ID、thread ID 和各轮 Trace |
| 用例 Trace 与 LangGraph Trace 分离 | `traceparent`、`trust_inbound_traceparent` 和 `langfuse_trace_id` |

Online Evaluator 异步执行，Experiment 完成后 Score 可能稍后显示。自托管环境还需启用 evaluator worker/dispatcher。

## 7. `scripts/langfuse/` 脚本

| 文件 | 用途 |
|---|---|
| `upload_golden_to_langfuse.py` | 上传 categories golden case 到 Dataset |
| `upload_evaluators.py` | 扫描定义文件，全量同步 Code Evaluators 和指定 Dataset 的 Online Rules |
| `upload_score_configs.py` | 扫描定义文件，全量同步人工 Score Configs |
| `langfuse_eval.py` | 执行 Dataset Experiment 或本地评测 |
| `promote_langfuse_prompt.py` | 将 Langfuse Prompt 拉取到本地 Git |
| `_definitions.py` | 读取并校验本地 JSON 定义，不单独执行 |
| `_public_api.py` | 上传脚本共用的 Public API 客户端，不单独执行 |
