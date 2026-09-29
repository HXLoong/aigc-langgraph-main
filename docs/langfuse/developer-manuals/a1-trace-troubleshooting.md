# A1 · Trace 查看与排障

| 页面属性 | 内容 |
|---|---|
| 负责人 | @HXL |
| 状态 | 草稿 |
| 适用 Langfuse 版本 | Python SDK v4（本机 4.15.0）；自托管 4.46.0 |
| 最后验证日期 | 2026-09-29 |
| 验证人 |  |

## 1. 适用人群与使用场景

开发、测试和业务同事在遇到答错、报错或响应慢时，用本手册找到对应请求，指出哪一步、哪个字段出了问题。

## 2. 前置条件

- **账号**：已能登录 Langfuse，并有项目的查看权限；

- **环境**：通过管理员提供的 `LANGFUSE_BASE_URL` 进入沙箱。

| 使用方式 | 需要的环境变量名称 |
|---|---|
| 只看网页 | 无需在本机设置环境变量；向管理员获取 `LANGFUSE_BASE_URL` 对应的入口 |
| 第 3 节的只读命令 | `LANGFUSE_BASE_URL`、`LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY`；旧 CLI 兼容变量 `LANGFUSE_HOST` |
| 本次查询的本地变量 | `LANGFUSE_CLI_PATH`（已有 CLI 的 `bin/langfuse.mjs` 文件路径）、`TRACE_ID`（要查询的 Langfuse Trace ID） |
| 找不到记录时，由开发核对应用配置 | `ENABLE_LANGFUSE`、`ENVIRONMENT`、`TRUST_INBOUND_TRACEPARENT` |


## 3. 操作步骤

### 步骤 1：进入 Tracing，选对时间范围

1. 登录后确认左上角的项目是指定沙箱。
2. 在左侧 `Observability` 下点击 `Tracing`。
3. 可在每一行tracing最前面看见时间，可根据start time筛选所需的tracing

![从 Observability 进入 Tracing](../images/00-observability-nav.png)




**列表里一行是一个 Observation，不一定是一条请求。** 同一 Trace ID 出现多行是正常的。概念说明见 [Langfuse 数据模型](https://langfuse.com/docs/observability/data-model)。

### 步骤 2：按手里的信息找到目标请求

以下四条路任选一条

**有 Trace 链接或 `langfuse_trace_id`：**

1. 打开链接；只有 ID 时，在 `Filters` 最顶部的搜索栏中搜索 `Trace ID`，填入完整 ID。
2. 点击结果行，打开详情。
3. 核对时间和 Input，确认确实是要查的那次请求。

报告中的 `trace_id` 是应用审计 ID，`langfuse_trace_id` 才是 Langfuse 侧 ID；接入评测父 Trace 时两者可能不同。不要拿 `message_id` 填 `Trace ID`。

**有 `run_name`：先找批次，再找用例。**

1. 左侧进入 `Experiments`，按完整运行名找到本次实验。`name` 是一批评测的名字，不是某个节点的名字。
2. 打开实验，按 `case_id` 找失败条目，进入它关联的 Trace。
3. 若这次由 `local_eval.py` 运行，没有 Experiment 入口：回到 `Tracing`，在 `Metadata` 条件中按键 `run_name` 和完整运行名筛选，打开名为 `regression_case` 的用例记录。
4. 查不到时清除 `Is Root Observation` 限制。`regression_case` 可能挂在实验条目下面，不是最外层记录。

**有 `conversation_id`：先找会话，再找这一轮。**

1. 在 `Tracing` 的 `Filters` 最顶部的搜索栏中搜索 `Session ID`，填入接口返回的 `outputs.session_id`；也可从左侧 `Sessions` 打开同一 ID。
2. 普通常见的 `conversation_id` 与 Session ID 相同；含中文或特别长的 ID 可能经过映射。查不到时向开发索取实际返回的 `session_id`，不要自行截短 ID。
3. 按时间找目标轮，打开详情，再核对 Input 中的 `raw_text`、`message_id`。同一会话可能包含多轮，不能只看最后一条。

**只有 `message_id`：在输入中找消息，再核对整条链路。**

1. 限定发生时间，清除 `Is Root Observation` 限制。
2. 在顶部 Search 输入 `input:"<完整消息 ID>"`，将尖括号部分替换为测试消息 ID，按 Enter。这里搜的是步骤输入，不是 Metadata。
3. 打开命中行，核对 Input 中的 `message_id` 或原始请求中的 `inputs.message_id` 是否完整一致；确认时间、原文也一致。
4. 没命中时，可能是输入未上报、被脱敏或所选节点没有这个字段。让开发从应用日志或 `langgraph_node_trace` 按消息 ID 找到 `thread_id`、审计 `trace_id`，再取对应响应中的 `session_id` / `langfuse_trace_id` 继续查。

同一 `message_id` 可能被调用端再次提交，出现多条 Trace。保留全部候选，按时间和 Observation ID 区分。搜索支持 `input:` 和 `output:`，说明见 [官方筛选语法](https://langfuse.com/docs/observability/features/filter-search-bar)。

![Filters：在 Search filters 中找字段；Text 可手填；Is Root Observation 控制是否只看入口](../images/39-tracing-filters.png)

图为仓库既有的控件截图；只找入口时可保留 `Is Root Observation = True`；要在列表找内部步骤时清除此条件，**不要改成只选 False**，否则入口又会被排除。打开详情后的树也要展开子节点。

### 步骤 3：读懂 span 树，选中正确的一轮

1. 在详情右侧选 `Tree`，展开节点左边的箭头。
2. 如果从实验进入，先看实验条目，再展开 `regression_case`。在每个 `workflow_http` 的 Metadata 中看 `turn`，找到目标轮。
3. 展开该轮的服务端图，点击具体节点；右侧 `Preview` 查看 Input / Output，`Attributes` 查看 Metadata，`Scores` 查看评分和评语。

下面是读树用的简图，省略了中间节点：
```text
实验条目                         ← 一条测试用例的完整报告
└─ regression_case              ← 用例执行过程
   ├─ workflow_http（turn = 1）   ← 第 1 轮 HTTP 请求
   │  └─ 服务端主图
   │     ├─ ingest              ← 收到的输入
   │     ├─ parse_instruction   ← 解析产品、意图和参数
   │     │  └─ GENERATION       ← 实际模型调用
   │     ├─ 业务参数检查与提交
   │     └─ render              ← 最终回复
   └─ workflow_http（turn = 2）   ← 第 2 轮 HTTP 请求
      └─ …
```

直接业务请求没有上面的实验包装层；冻结意图用例可能只出现解析节点，不经过完整业务图。先看报告的 `mode`，再对照[当前主图流程](../../architecture/main-graph-flow.md)，不要因为没看到提交节点就判断丢数据。

节点名方括号里的英文是定位代码的标识，例如 `[parse_instruction]`。`[parse_instruction/llm]` 是它内部的模型步骤，不是第二次业务解析。节点显示名的依据见 [node_labels.py](../../../app/observability/node_labels.py)。

### 步骤 4：打开 `turns`，读这一轮的富集报告

1. 先选**实验条目**，在 Output 找 `turns`，展开目标轮；数组第 1 项对应第 1 轮。
2. 若只能看到 `regression_case` 的原始输出，回到实验条目。用例执行节点通常记录每轮原始 `outputs`，富集报告还会加入输入、期望和差异。


`turns` 是本项目补充的报告字段，不是每条 Langfuse Trace 都自带。以下是阅读顺序；实际结构以 [harness/evaluation.py](../../../harness/evaluation.py) 为准。

| 先看什么 | 看懂什么 |
|---|---|
| `turn`、`raw`、`source_text` | 第几轮、实际发送了什么；原用例文本与发送文本可能因订单引用替换而不同 |
| `quote_content`、`history` | 这一轮引用了什么、用例声明了哪些历史；`quote_passed` 只是短预览，内容不全时看 `quote_content`。实际模型上下文还要核对解析节点 Input |
| `assertions` 与 `diff` | 本轮要求什么、哪里不符；每项差异看 `path`、`expected`、`actual` |
| `product_type`、`intent` | 实际识别的产品和动作 |
| `place_params`，或 `outputs` 中的其他参数 | 提取或提交了哪些字段；进一步核对 `outputs.backend_request`、`outputs.cleaning_records` |
| `api_code`、`api_result`、`reply` | 后端实际返回什么，最终回复什么 |
| `error`、`outputs.diagnostic`、`trace` | 出错节点和错误类别，以及经过了哪些节点 |
| `langfuse_trace_id`、`observation_id`、`elapsed_ms` | 跳回哪条链路、哪一轮服务端入口，以及该轮耗时 |

最后看报告顶层的 `failure`、`unexecuted_turns`：后续轮可能因前一轮失败而没有执行，不要把“无输出”理解成“通过”。

**意图集的 `diff` 为空，不代表意图正确。** 当前意图评分由后台 JS Rule 异步生成，要看对应 Score 的值和 comment。业务参数是否测全也不能只看 PASS，覆盖说明见报告的 `parameter_assertion_coverage`；评分口径链接见第 7 节。

### 步骤 5：从错误字段找到第一个出错节点

1. **先看 `error.node` 和 `error.code`。** 在树里找同名节点。需要原因时看 `outputs.diagnostic`、节点的 Status Message 和 Output；公开 HTTP 响应不保证包含原始 `error.message`。
2. **再看差异中的 `path`。** 它指出错的是产品、意图、参数还是回复。不要只停在最终的兜底回复。
3. **对照该节点的 Input / Output 和上一步的 Output。** 找到字段第一次缺失、变错或被拒绝的位置。

| 看到的现象 | 下一步点哪里、看什么 |
|---|---|
| 产品或动作不符 | 打开 `parse_instruction`，对照当前原文、引用、历史与解析结果；再看前面的产品规则判断 |
| 引用内容为空或用了旧信息 | 从 `ingest`、输入准备到解析节点逐步核对；区分引用未传入与模型没有使用引用 |
| 参数缺失或变了 | 对照解析节点的 `parsed_instruction` / `field_records`、参数准备节点及最终 `backend_request`；若字段被省略，查 `cleaning_records` 的理由 |
| 模型请求失败或输出校验失败 | 打开 `GENERATION` 及其父解析节点，看 Status Message、Output 和耗时；模型已有返回也可能在结构或来源检查时失败 |
| 参数提交正确，后端拒绝或识别结果不对 | 保留提交参数及 `api_code/api_result`，交 Java 负责人核对；标的职责依据见 [ADR 0025](../../adr/0025-instrument-resolution-delegated-to-backend.md) |
| 最终回复与后端结果看起来不同 | 核对 `render` 的 Input / Output 与[后端回执契约](../../api-contracts/java-backend.md)，保留后端原结果，不凭展示文字判断交易成功 |
| 没报错但响应慢 | 切到 `Timeline`，找耗时最长的步骤，再确认是模型、后端还是存储；父节点包含子节点耗时，不能把整棵树的时间直接相加 |

## 4. 验证：做完后应该看到什么

选一条已有的沙箱失败用例或慢请求，按实际场景逐项核对。无需重新发送交易、重跑实验或修改评分配置。没有合适记录时，将对应项记为“待验证”。

### 4.1 逐项检查操作结果

| 检查项 | 做完后应该看到什么 | 需要留下的证据 |
|---|---|---|
| 找到了正确请求 | 通过步骤 2 的任一查找方式进入详情；项目、发生时间和测试输入都与目标请求一致，完整 ID 已核对 | 查找方式、时间及时区、Langfuse Trace ID、目标 Observation ID；有会话时记录 Session ID |
| 看懂了执行过程 | 能展开目标步骤，看到它的 Input / Output，并说明它在本次执行中的作用；节点范围与当前执行模式相符 | 目标节点名称和关联的 Observation ID；缺失的内容单独注明 |
| 选中了正确轮次（多轮记录） | 能按 `workflow_http` 的 `turn` 找到目标轮，该轮输入与要排查的消息一致，没有把其他轮的结果混进来 | 轮次、消息 ID，以及该轮对应的 Observation ID |
| 读到了富集报告（有此报告的评测记录） | 能在实验条目的 `turns` 中找到目标轮，将输入、预期、实际结果和差异对应起来；有未执行轮次时能指出 | 用例编号、轮次和实际差异；具体字段按步骤 4 核对，不另建一份报告结构 |
| 找到了异常线索（错误或答错记录） | 能指出某个字段第一次缺失、变化或被拒绝的可见步骤，并用相关节点的输入、输出或错误说明支持判断 | 节点名称、有问题的字段、预期与实际的脱敏摘要；只有最终兜底回复时，记“证据不足，待继续排查” |
| 核对了评分（需要评分的评测记录） | 能找到该用例已有的 Score，读出值及 comment 中的理由，并与目标运行、用例对应；分数未出现时明确记为待评分 | 评分名称、值和理由摘要；意图集不能只凭空 `diff` 判断通过 |
| 找到了耗时线索（慢请求） | 能在 `Timeline` 中指出耗时较长的步骤，记录该步骤耗时和目标轮的总耗时，区分模型、后端或存储环节 | 节点名称、耗时与单位；保留父子关系，不把父节点和子节点的耗时直接相加 |

每项记录为“已核对”“待验证”或“不适用”，并写明原因。例如，普通业务 Trace 没有实验富集报告，可以记“不适用”；本应有评分却尚未出现，应记“待验证”，不能记为通过。

发现异常的可见位置后，仍需区分事实与推测。例如，“参数已提交，后端返回拒绝”是可核对的事实；后端为什么拒绝，要保留原结果交对应负责人继续确认。不能仅凭最终回复或一个错误标签认定根因。

### 4.2 留下一份别人能继续排查的记录

按实际结果填写，缺少的信息写“未取得”，不猜测或补造：

```text
核对日期 / 操作人：
沙箱项目 / 发生时间及时区：
查找方式 / 运行名与用例编号（如有）：
Langfuse Trace ID / 目标 Observation ID：
Session ID / 消息 ID / 轮次（如有）：
现象与预期（脱敏摘要）：
最早可见的异常步骤 / 字段，或耗时较长的步骤：
实际结果与证据（脱敏摘要）：
已确认的事实 / 尚待确认的原因：
各检查项结果 / 未完成原因：
需要谁继续核对 / 具体核对什么：
```

证据截图只使用测试数据；涉及真实记录时，先遮盖客户名、证券、金额、群名、用户标识、订单号、邮箱和地址栏，再上传。不在记录中填写密钥、密码、API Key 或内网地址；平台入口用 `LANGFUSE_BASE_URL` 表示。

另一位有权限的同事应能凭这些 ID 找到同一条记录，并复核你的判断。完成实际操作后，再更新页面属性中的“最后验证日期”和“验证人”；尚未完成的检查保留待验证说明。

**本节验证的是能否找到请求、读懂证据并交接问题。它不表示缺陷已修复、交易已成功或数据集验收已通过。** 业务与评分结论继续按第 7 节链接的仓库规则判断。

## 5. 常见问题

| 问题 | 处理办法 |
|---|:-:|
| 一条记录都没有 | 依次检查项目、时间及时区、Environment、已有筛选；仍为空，让开发核对前置条件中的应用配置和导出日志 |
| 能找到实验，找不到服务端步骤 | 清除根节点和环境限制，核对每轮的 `langfuse_trace_id`；交开发检查请求的 `traceparent` 和 `TRUST_INBOUND_TRACEPARENT`，不要通过重复交易来补 Trace |
| 没有 `turns` 或 `diff` | 可能选中了普通业务 Trace 或 `regression_case`。按步骤 4 返回实验条目或本地报告；意图集另看 Score comment |
| Experiment 完成了，Score 还没出现 | 评分异步执行，稍后刷新；仍缺失时交评测维护人查 Rule 与 worker。 |
| Scores 主列表找不到实验分数 | 先在实验条目中查看；需要列表筛选时包含 `sdk-experiment` 环境 |
| `error` 为空，是否成功了 | 还要看后端结果和断言差异。字段答错、业务拒绝不一定是程序异常；HTTP 成功也不等于交易成功 |
| 一个 Trace 有多次模型调用，是否违规 | 先按 `workflow_http` 分开每轮，再看实际 `GENERATION`；多轮用例可能共用一条 Trace，计数边界见 [ADR 0031](../../adr/0031-single-model-request-per-message.md) |

## 6. 本项目不用的功能及原因

| 功能 | 本次怎么处理、为什么 |
|---|---|
| 用 LLM Judge 判断数据集通过 | 本项目使用确定性评分，依据见 [ADR 0005](../../adr/0005-annotation-roles-judge-plus-business-spotcheck.md) |
| 在 Langfuse 改 Prompt 后直接当成生产发布 | 生产提示词真源在 Git，依据见 [ADR 0014](../../adr/0014-langfuse-as-harness-backend.md) 与 [ADR 0023](../../adr/0023-prompt-as-code-langgraph.md) |
| 把客户 Trace 发布为公开链接或传到外部演练服务 | 数据留在授权环境，依据见 [ADR 0014](../../adr/0014-langfuse-as-harness-backend.md) |

## 7. 参考

本文只写操作方法。Notion 使用本文时保留以下链接；数据集字段、提示词真源和评分口径仍由仓库维护，不在 Notion 另建规则。发现差异记入审阅记录，交负责人处理。

| 要核对什么 | 仓库依据 |
|---|---|
| 项目排障顺序、修复纪律 | [根项目说明：排查与修复流程](../../../CLAUDE.md#排查与修复流程bug-debug-workflow)；[生产故障 SOP](../../operations/troubleshooting-sop.md)（资料差异见审阅记录） |
| 完整页面介绍与既有截图 | [WebUI 操作手册 §1.1](../web-ui-operation-manual.md#11-tracing查看一次调用的完整链路) |
| 富集报告、原始轮输出与父子关系 | [harness/evaluation.py](../../../harness/evaluation.py)、[harness/multi_turn.py](../../../harness/multi_turn.py)、[harness/langfuse_client.py](../../../harness/langfuse_client.py) |
| 接口输出和追踪身份 | [app/api/routes.py](../../../app/api/routes.py)、[app/observability/tracing.py](../../../app/observability/tracing.py)、[ADR 0004](../../adr/0004-trace-granularity-node-level.md) |
| 数据集字段与评分口径 | [数据集说明](../../../tests/datasets/README.md)、[Harness 说明](../../../harness/README.md)、[ADR 0005](../../adr/0005-annotation-roles-judge-plus-business-spotcheck.md)、[ADR 0029](../../adr/0029-node-level-debug-api-and-regression-workbench.md) |
| 字段来源、参数清洗与 Java 边界 | [ADR 0027](../../adr/0027-field-evidence-contract.md)、[ADR 0025](../../adr/0025-instrument-resolution-delegated-to-backend.md) |
| 已发现的过时说法与未验证项 | [2026-09-29 资料审阅记录](../../reports/2026-09-29-langfuse-manual-source-review.md) |

Langfuse 官方文档：[数据模型](https://langfuse.com/docs/observability/data-model)、[v4 列表与根节点筛选](https://langfuse.com/faq/all/explore-observations-in-v4)、[筛选语法](https://langfuse.com/docs/observability/features/filter-search-bar)、[Sessions](https://langfuse.com/docs/observability/features/sessions)、[CLI](https://langfuse.com/docs/api-and-data-platform/features/cli)。
