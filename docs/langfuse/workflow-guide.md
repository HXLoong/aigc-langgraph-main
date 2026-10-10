# Langfuse 功能与评测链路使用指南

本页说明本项目的本地评测、追踪与平台数据之间的关系。
执行命令和正式评分规则只在 [测试指南](../testing/README.md) 维护；
使用界面见 [Web UI 手册](./web-ui-operation-manual.md)，自托管见 [部署说明](./self-hosted-deployment.md)。

**正式结果由本地 Python 同步确定性评分，不调用 Judge，不等待 Langfuse JS Rule，也不需要 Node.js 服务。**
Langfuse 是可选记录与分析平台；追踪成功不等于评分成功，SDK 入队不等于已入库。
实现缺口与待办见 [工作计划](../work-plan.md)。

## 1. 功能入口

| 对象／功能 | 用途 | 与本地结果的关系 |
|---|---|---|
| Trace / Observation | 保存用例、HTTP 轮、图节点、模型和外部调用过程 | 用于定位失败，不决定 PASS |
| Session | 聚合同一会话的执行记录 | 不替代多轮断言 |
| Dataset / Dataset Item | 平台上的输入、期望和来源 metadata | 黄金真源仍是 git 的 `tests/datasets/` |
| Experiment / Experiment Item | 关联一次数据集执行及逐条结果 | 需要执行器显式关联，不因上传 Trace 自动生成 |
| Score | 保存确定性结果或人工复核 | 应注明来源，不与平台补充评分混用 |
| Evaluator / Evaluation Rule | 平台运行的可选评分逻辑与触发规则 | 平台异步分数不阻塞本地结束 |
| Prompts / Playground | 提示词演练与查看 | 生产提示词仍从 git 加载 |

## 2. 对象与评测链路

本地正式链路：

```text
 tests/datasets/{biz,intent}（输入 + 明确期望）
  → harness.golden 加载与选择
  → HTTP 执行（解析／入口节点或主图）
  → Python 确定性评分
  → 本地 report / PASS / FAIL / REJECTED
```

启用 Langfuse 时的追踪链路：

```text
用例根 Observation
  → HTTP 轮 Observation
  → app 图／节点／模型 Observation
```

Dataset 同步、Trace 上传、最终 report／Score 上传、Experiment 关联是不同操作。
黄金集 `harness run` 使用可选追踪并在批次收尾 flush，不自动创建 Dataset Experiment。
平台 webhook 通过内部适配器复用相同 HTTP 执行器，最终 report 与本地 Score 由 SDK Experiment 记录。
节点 Dataset 工具是独立调试能力，不证明黄金集平台闭环可用，也不增加正式验收层。

## 3. Dataset 数据结构

`harness.golden` 是用例加载真源；平台同步工具将数据投影为：

- `input`：首轮消息与 `sub_scenes` 多轮输入，包括明确引用、历史及已有入口标记。
- `expectedOutput`：明确结构／文本断言，不从实际输出反推 expected。
- `metadata`：稳定用例 ID、名称、类别、来源、数据文件与行号等，用于追溯和展示。

Dataset 名通常取数据文件的相对路径、去掉 `.jsonl`，例如 `biz/swap_prod`、`intent/swap_instrument`。
原始 case ID 应保留用于对账；平台 Item ID 与本地 case ID 不是必然同一值。
`category` 是数据标签，不提供新的 CLI 分类选择参数。

loader、HTTP runner 与平台投影保留 `robot_version`／`existing_command`。
评测输入缺省 V2，显式版本保持原值，app 的缺省 V1 不改变。
平台触发前须重新同步包含入口字段的数据集，输入和期望与 git 不一致时拒绝执行。
冻结历史、参考证券码和 expected 不得混入当前用户证据。

## 4. 配置与数据同步

### 4.1 可选追踪

通过安全的环境配置填写 `ENABLE_LANGFUSE`、`LANGFUSE_BASE_URL`、
`LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY`。关闭开关或缺凭证时追踪不启用，本地评分不依赖它。

需要贯通 harness → app 的父子记录时，两侧使用同一项目；只在可信网络启用
`TRUST_INBOUND_TRACEPARENT=true`。已有服务需要重启才会使用新的进程配置。
返回 Trace ID 只是关联信息，平台是否收到 Observation／Score 必须另查。

### 4.2 黄金集同步

```bash
python scripts/langfuse/upload_golden_to_langfuse.py --sync-all
```

该操作上传数据，不执行用例、不完成评测。它会向配置的 Langfuse 发送用例内容，
只在允许数据共享的环境运行，具体选择／覆盖行为先查脚本 `--help`。
数据集审阅和修改在 git 完成，平台新增标注先导出复核，不自动回写黄金期望。

### 4.3 平台评分与人工复核

`harness/evaluators/` 与 `scripts/langfuse/definitions/` 是平台评分资产。
已有 Online Rule 可以异步产生补充 Score，但正式本地结果不等待它，也不要求部署本地 JS 服务。
是否继续维护这些资产由工具链收敛方案决定，不把平台 evaluator 自测当成 app 核心验证。

人工标注可用于复核失败和修订期望；不能以平台分数覆盖本地字段差异，
不能把无适用断言、未执行或环境阻塞标记成业务通过。

## 5. 执行评测与 Experiment 边界

黄金集只用 `python -m harness run`，四类参数为 `--group`、`--file`、`--case`、`--backend`。
运行、范围、Java 写入授权与报告位置见测试指南，不另换脚本以启用追踪。

CLI 与平台适配器固定访问已有 8000 服务，不临时启动 app、不修改服务配置。
正式本地结果与平台上传状态分开记录。

[Remote Experiment webhook](./remote-experiment-webhook.md) 校验签名和范围后启动内部评测进程，
从平台取数并与 git 黄金集绑定，复用本地执行和评分，再通过 SDK Experiment 记录结果。
本地评分不等待平台 Rule；受理成功不代表执行或上传成功。

## 6. 从失败结果定位节点

1. 从本地报告取得 case ID、失败轮、实际输入、期望、diff、error 以及关联 ID（若有）。
2. 先核对入口版本／分支，再查产品、动作、来源、实际出站参数，最后核对 Java 原始回复。
3. 在平台按关联 ID 找用例根、HTTP 轮、服务端图和模型记录，核对父子关系与 Session。
4. Observation 缺失单列为追踪缺口；不要把平台不可用当业务通过，也不要因上传失败篡改业务结果。
5. 对 app 根因先补核心回归再修复，只重跑相关范围；Java 业务数据或识别问题不在 app 内补字典。

Java `code=0` 不等于黄金断言 PASS；拒绝／处理中等真实回复不得改写为本地订单卡。

## 7. `scripts/langfuse/` 脚本职责

| 工具 | 用途 |
|---|---|
| `upload_golden_to_langfuse.py` | git 黄金用例 → 平台 Dataset |
| `upload_prompt_to_langfuse.py` | git 提示词 → 平台演练资产，不替代生产真源 |
| `upload_evaluators.py` | 可选平台 Code Evaluator 与 Online Rule 同步 |
| `upload_score_configs.py` | 人工 Score Config 与 Annotation Queue 同步 |
| `node_dataset.py` | 审阅后的节点标注发布、导出和安全节点 Experiment 调试 |

参数和安全调用见 [脚本说明](../../scripts/langfuse/README.md)。该目录不再有黄金集执行脚本。
写类节点不自动回放；节点样本调试不替代 `tests/datasets/` 验收。

## 8. 意图集与业务集

- **意图集**：逐轮标注产品／动作／入口，标的子集标注原文表达及允许的交易品种。
  普通冻结样例调唯一解析节点，快速样例调入口节点；引用上一轮回复等回放样例走主图和所选后端。
- **业务集**：主图调用 mock 或 Java，比较实际参数和业务回复；真后端验收必须使用授权身份和数据。
- **标的子集**：直接评联合解析结果，不追加第二次模型提取，不由 app 补证券代码或计算近月；
  `reference.backend_codes` 仅作参考，不参与原文表达评分。
- **评分**：意图由 `harness/intent_scoring.py` 判定，业务由 `harness/evaluation.py`／`differ.py` 判定。
  两类黄金集均本地同步给结论，不进 CI 自动批量调用真实模型。

数据格式、固定时段、引用断言和标注覆盖详见 [数据集说明](../../tests/datasets/README.md)。
