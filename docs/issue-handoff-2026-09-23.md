# feature-xsc 工作交接：未完成事项与下一步

> 2026-09-24 更新：后续自主修复见 [PR #244](https://github.com/GZTL-AI/aigc-langgraph/pull/244)。原始四条 RED 已修复；当前显式意图集 391 条，本地网关及首轮 CI 为 381/391（97.44%）；最新 bb66ae9 CI 为 380/391（97.19%），正向 353/364，明确拒绝 27/27；静态检查、完整测试与真实 MySQL CI 均通过。
>
> 已处理并关闭 #162、#173、#174、#226、#227、#228、#230（#173/#174 为过期方案关闭，不是上线验证通过）。#127/#133/#169/#220 的完整业务验收仍需要匹配的测试资产和可核验状态；#234 缺真实生产 URL/联系人及回切演练；#233 独立 dry-run 全量采样已完成：417 次 HTTP、P95 8554ms、5xx 0、cascade 41（9.83%）；这是参考基线，业务断言仅 2/391 PASS，生产 7 天观察仍待验收。Java 源码、配置文件、JAR、agentUrl、DTO 未修改。
>
> 下文保留原交接时点的历史事实，不应据其旧 RED 数量或旧通过率重新判定当前分支。最新证据在 GitHub issue 评论及 `tmp/goal-issues/`；未满足的外部验收没有标为完成。

更新日期：2026-09-23。范围：PR #216 / #217 后续问题及 #227 校准。

本次按用户明确指令提交、推送暂停时的工作快照。**当前仍有 4 条失败测试，模型评测未达到 95% 门槛；这不是可直接合入 main 或上线的完成版本。** Java 源码、配置及现行 wire DTO 未修改。

## 1. 已交付的改动

| Issue | 本次代码与数据进展 | 验收边界 |
|---|---|---|
| [#220](https://github.com/GZTL-AI/aigc-langgraph/issues/220) | HTTP harness / local_eval 支持从本轮完整引用绑定订单号、对手选项、持仓合约；逐轮和 `any_turn` 结构断言、声明 lint、示例与歧义防御已实现 | 首批 12 轮业务 expected 仍是待审核草稿，未覆盖正式 categories |
| [#226](https://github.com/GZTL-AI/aigc-langgraph/issues/226) | 复用源 categories 的既有标签，补入两条生命周期、共 12 轮；意图集由 381 增至 383 条。评测入口补对手上下文、动态单号；mock 期权/平仓契约及生命周期已调整 | 新增的 8 条／16 轮意图标签草稿未应用；mock 通过不等于真实交易验收 |
| [#227](https://github.com/GZTL-AI/aigc-langgraph/issues/227) | 增加明确别名、数量及算法组合表达归一化；区分动作和持仓描述；限定订单证据范围；保留否定、条件和负号；非正数量阻止后端写入并提示纠正；增加字段级诊断 | 仍有代码缺口、抽取错误和待裁决的业务表达，详见下文 |
| [#228](https://github.com/GZTL-AI/aigc-langgraph/issues/228) | 只读核验本地 43 条有效 Java SWAP 模板后，移除 8 条 `response_contains` 的 `@端到端测试机器人` 首行 | 其余卡片断言保留；未执行这 8 条的真实后端写入回归 |

此前本地提交 `788327f` 的 harness / CI 清理也随本次分支推送交付。用户原有 `.gitignore` 换行改动保留在工作区，不纳入本次业务提交。

## 2. 验证结果：区分单次全量与追加复测

| 检查 | 结果 | 说明 |
|---|---|---|
| 最后一次完整离线回归（新增四条复现测试之前） | 3427 passed / 3 skipped / 13 warnings | 3 条跳过项为需显式启用的真实 MySQL 测试；warnings 为已有问题 |
| 新增四条复现测试 | 4 failed | 已观察到 RED；用户要求暂停时尚未实现修复，失败测试保留 |
| 提交前当前完整回归 | **3427 passed / 4 failed / 3 skipped / 13 warnings** | 56.02 秒；失败项恰为第 3 节四条；无 `.env` 的隔离副本，未接入真实后端 |
| 静态与类型检查 | ruff 相关范围通过；mypy app 145 个文件通过 | fixture lint、ADR 引用、隔离副本的 AGENTS 同步检查通过 |
| 真实模型：单次完整 383 条 | **302/383，78.85%** | 内网模型网关＋隔离 mock 后端，耗时 1182 秒；门槛 95%，评测退出码为 1 |
| 后续受影响案例复测 | **18/28** | 按修改涉及的输入语法选取全部受影响案例，不按旧结果挑选通过项 |
| 逐例组合覆盖统计 | **302/383；意图 383/383；标的 294/375** | 用后续 28 条结果替换对应旧结果；这是跨运行组合报告，不是最终代码的又一次单次全量运行 |

完整运行和追加复测的失败案例成员有所变化，虽然总通过数同为 302，不能把它们当作同一次实验。正式发布验收仍需在修复后的同一版本重新跑全量及 GitHub Actions。

本轮未修改正式意图集来消除失败，未降低门槛，未上传 Langfuse，未进行真实 Java / GOATS 交易写入。

## 3. 最先处理：四条已复现、未修复的问题

测试均位于 [test_order_semantics.py](../tests/subgraphs/swap/test_order_semantics.py)。继续工作时先复现 RED，再逐项修复；不要删除测试或将其改为跳过。

| 顺序 | 测试与问题 | 修改方向 | 验收要求 |
|---|---|---|---|
| 1 | `test_buy_to_close_is_not_treated_as_opening_a_long_position`：明确的“买入平仓”被误判为开仓冲突 | 修复 `normalize.py` 的动作冲突判断，区分买入平仓与买入开仓，保留否定和矛盾指令防御 | 方向为 `SHORT_CLOSE`，平仓意图为 true；“不要买入平仓”不能变成正向请求 |
| 2 | `test_same_instrument_and_quantity_can_use_distinct_execution_markers`：同标的、同数量的两笔订单无法建立独立证据范围 | 改进 `candidate_scope.py` 的订单定位，利用各笔明确的执行条件、价格等证据；不因数量相同就混合订单 | 集合竞价和开盘尽快执行两笔保持分离，价格、数量及动作不串单；无法确定归属仍拒绝 |
| 3 | `test_pov_with_participation_label_is_the_same_algorithm`：`pov跟量` 未被识别为 POV | 支持确定的算法名称与中文标签组合，比例仍独立提取和校验 | `pov跟量` → `POV`；不把任意执行风格或未知算法转为 POV |
| 4 | `test_matching_currency_suffix_can_follow_yuan_unit`：`1500万元 CNY` 解析失败 | 支持同一币种的中文单位与币种代码组合，同时检查冲突 | 金额为 15000000；`1500万元 USD` 等币种冲突必须报错 |

## 4. #227 还剩哪些问题

下表来自逐例组合覆盖报告，按每个失败案例的首个阻断点分类，合计 **81 条**。数量表示案例数，不是需要增加的代码分支数，也不表示每条都是程序缺陷。

| 首个阻断点 | 数量 | 后续处理 |
|---|---:|---|
| 方向枚举不匹配 | 35 | 分开检查“明确买卖方向”“只表达清仓／平仓”“历史或暂定动作”；不能把裸“清仓”一律当作 SELL |
| 算法枚举不匹配 | 12 | 区分 POV 标签组合、最大跟量意图、执行风格、ASAP 等表达；仅支持明确契约，不生成后端默认比例 |
| 标的表达／订单数／市场评分差异 | 10 | 检查原文提取、漏单／多单及数据候选；继续执行港股严格 `HK_STOCK`、混写可接受完整表达／代码／名称的用户口径 |
| 名义金额解析 | 7 | 明确的复合币种单位可修语法；“约”“大概”“左右”是否只是参考估值需业务确认，不静默删掉限定词 |
| 原文证据不一致 | 4 | 检查模型是否拼接、改写或借用参考名称；保留证据校验，不能放宽为子串猜测以提高分数 |
| 订单证据归属与定位 | 6 | 包含同标的同数量拆单、跨订单方向／比例等；先判断是否正常输入被误拦，再修归属逻辑 |
| 比例、价格、品种、平仓语义等其他校验 | 6 | 逐例核对，含上表“买入平仓”缺陷及“不低于某价格”等表达 |
| 非正数量拒绝 | 1 | `accept_order_case_77` 的负数量已正确阻止写入；正式数据的拒绝验收需单独审核，不能删除案例或改成正数量 |

### 继续迭代顺序

1. 先修第 3 节四条 RED，跑受影响的互换、渲染和证据归属测试。
2. 按上表逐类检查实际候选和字段差异，优先修明确的代码缺口与错误订单归属；有歧义的业务表达单列审核。
3. 同时审核 #220 的 12 轮结构断言，以及 #226 的 8 条／16 轮新增意图标签；两条已有标签的生命周期不需重新猜测。
4. 对修复案例做真实模型专项复测，再在同一代码版本跑完整 383 条意图集。报告分别列意图、标的、运行错误及正确拒绝，不只给总体通过率。
5. 达到 95% 门槛且没有未处置的 P0/P1 问题后，再按用户授权提交、推送，检查 GitHub Actions。不要因本次代码已推送就关闭 #227。
6. 准备授权账号、群、对手和持仓后，再由主代理或用户调度真实 HTTP / Java 验收；本轮 mock 结果不能代替它。

## 5. 其他尚未关闭的 issues

截至本次交接核对，GitHub 共有 13 个 open issue。#225 的 Actions 公网模型连接和首次基线任务已完成；模型质量问题继续由 #227 跟踪。

| Issue | 未完成内容 | 优先级／依赖 |
|---|---|---|
| [#220](https://github.com/GZTL-AI/aigc-langgraph/issues/220) | 审核并应用首批 12 轮结构断言，完成真实引用及写入验收 | 与 #227 并行；历史 unified 的 560 条不纳入本轮 |
| [#226](https://github.com/GZTL-AI/aigc-langgraph/issues/226) | 审核 8 条新意图案例／16 轮、复核 375 条互换标签，再验证完整意图集 | 与 #227 并行；不能把模型实际输出直接反抄成 expected |
| [#227](https://github.com/GZTL-AI/aigc-langgraph/issues/227) | 四条 RED、81 条模型失败分类处置、最终版本全量与 CI 验收 | 当前最高优先级 |
| [#228](https://github.com/GZTL-AI/aigc-langgraph/issues/228) | 前缀清理随本次提交交付；真实后端 8 条写入回归未执行 | 按真实后端验收结果决定关闭，不要求修改 Java |
| [#230](https://github.com/GZTL-AI/aigc-langgraph/issues/230) | Langfuse Dataset 上传、Evaluator Rule 绑定、Experiment / Score 验收 | 可后置；不阻塞本地与 Actions 的确定性评分 |
| [#233](https://github.com/GZTL-AI/aigc-langgraph/issues/233) | 当前模型的 P95、5xx、cascade 基线采样及阈值回填 | 上线前；需要指定环境和授权测试数据 |
| [#234](https://github.com/GZTL-AI/aigc-langgraph/issues/234) | 运维文档的真实地址／联系人、首次回切演练及版本更新 | 上线前；由部署负责人提供环境信息 |
| [#127](https://github.com/GZTL-AI/aigc-langgraph/issues/127) | 真后端业务跑通总任务图 | 历史任务，需与现有验收证据重新对账 |
| [#133](https://github.com/GZTL-AI/aigc-langgraph/issues/133) | 本地真实后端五条业务流 | 核对 #169 种子及已有联调证据，不以 mock 替代 |
| [#169](https://github.com/GZTL-AI/aigc-langgraph/issues/169) | 评估身份、授权、交易对手和标的种子 | 历史任务，先核查现状，再决定补齐或关闭 |
| [#162](https://github.com/GZTL-AI/aigc-langgraph/issues/162) | Grafana 退出门面板及指标快照 | 灰度上线前处理 |
| [#173](https://github.com/GZTL-AI/aigc-langgraph/issues/173) | 旧提示词 v2 灰度与收编 | 先核查是否已被后续 PromptSpec 重构替代 |
| [#174](https://github.com/GZTL-AI/aigc-langgraph/issues/174) | 旧提示词深度瘦身 | 后置；依赖语义审核和 #173 裁决 |

## 6. 验证纪律与证据位置

- 修复继续使用 RED → GREEN；保留本次发现的否定、条件、跨订单、负号截取和多行输入反例。
- Java、现行接口协议和后端权威识别边界保持不变。不得伪造成功卡片、固定业务字典或掩盖后端响应。
- 本地使用既有内网模型网关；GitHub Actions 使用已配置的 DeepSeek 公网 OpenAI 入口和 `deepseek-v4-pro`。密钥继续保存在环境与 Actions Secrets，不写入文档。
- 当前 `scripts/langfuse/langfuse_eval.py` 会加载仓库 `.env` 并覆盖部分进程变量。完整单测／mock 模型评测应使用无 `.env` 的隔离 worktree，并显式配置 mock 地址、禁用真实持久化与 Langfuse 上传。不要仅靠命令前缀变量假定已经隔离真实后端。
- 本次推送只交付工作快照，不创建 PR，不代表 CI 或上线验收通过。此后的 commit／push 仍需用户明确授权。

以下为本地取证路径，**`tmp/` 不入 Git**；本文已包含远端阅读所需的结论和下一步。

| 本地目录 | 内容 |
|---|---|
| `tmp/issue227-followup-20260923/` | `baseline-final.json`、`affected-complete.json`、`results-summary.json`、`remaining-failures.json`、带来源的 `coverage-rollup.json`、RED/GREEN 日志、验证快照哈希 |
| `tmp/issue227-handoff-20260923/` | 本次提交前检查、远端状态及推送回执 |
| `tmp/parallel-issues-20260923/` | #220 可审核补丁／预览、#228 动态模板核验、第一轮并行实施证据 |
| `tmp/intent-baseline-20260923/` | #220／#226 草稿审核表及原始本地模型基线 |
| `tmp/github-public-model-20260923/` | #225 Actions 公网模型配置核验与首次远端基线 |

当 #220／#226 草稿审核完成后，应将正式标签与审核结论通过正常代码变更交付；这些本地草稿目前不等于正式数据集。
