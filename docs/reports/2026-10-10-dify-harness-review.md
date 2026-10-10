# Dify 行为对齐与 Harness 工具链审阅（2026-10-10）

## 范围与结论

审阅当前工作区的未提交改动，重点为根目录用户提供的 Dify workflow `场外交易-scz.yml`、
app 入口及本轮业务改动、黄金数据集执行与评分、部署调用方和使用文档。
本轮不重放 Java 写入，不恢复用户已决定删除的非 app 核心测试，也不擅自修改 app 实现。

**结论：入口分支已取得局部对齐证据，但不能据此宣称 Dify 全业务行为对齐或 Harness 统一改造完成。**
正式 CLI 缺入口版本、已删除脚本仍被 webhook 调用、部署默认触发 Java 全量以及 CI 配套缺失，应先收敛。

## 一、按优先级列出的发现

### P1-1：正式 CLI 没有传递新入口字段，无法复现本次 Java 评测

证据：

- `harness/golden.py:24–46` 的 `TurnSpec` 和 `:103–137` 的 `_turn_from_object` 未声明／读取
  `robot_version`、`existing_command`；即使在 JSONL 增加字段，加载器也不会把它们传给执行器。
- `harness/multi_turn.py:178–188` 的 HTTP inputs 没有这些字段。
- `harness/intent_runner.py:19–30` 的冻结输入同样缺少版本；快速样例直接调用 `entry_route`，
  因而按 V1 进入存量分支，而不是预期的 V2 快速询价。
- `harness/cli.py:148–153` 没有注入版本的 `before_turn`；
  `harness/eval_server.py:52–86` 总是启动新的临时 app，并不复用已有 `127.0.0.1:8000`。

影响：普通业务用例在 CLI 下走 V1 静默，既不验证互换子图，也不验证 Java 回复。
此前三个文件的 633 条评测是调用 HTTP runner，向已有 8000 服务发送请求，并在主图请求前显式注入 V2；
**不是当前正式 CLI 的验证结果**。

建议：数据集输入 → 加载器 → Dataset 投影 → 冻结／主图 HTTP 执行全链路保留入口字段。
普通业务黄金集按实际机器人版本明确标注；不要把 app 默认值改成 V2 来迁就评测。
收敛临时服务与已有服务的执行方式，保持用户约定的四个 `run` 参数，不另开评测脚本。

### P1-2：删除旧评测脚本后，Langfuse webhook 仍调用它

证据：`app/api/langfuse_webhook.py:49` 指向已删除的 `scripts/langfuse/langfuse_eval.py`；
`:121–149` 仍组装 `--dataset / --ids / --limit / --concurrency / --no-judge`，`:157–175` 启动该路径。

影响：开启 webhook 后可以受理请求，但子进程找不到入口，不能完成所宣传的 Dataset Experiment。
`docs/langfuse/remote-experiment-webhook.md` 原先仍引导用户启用它。

建议：保持关闭，先决定该平台触发能力是否保留。若保留，接入同一执行／本地评分逻辑并补齐 Experiment 关联；
不能仅替换成 `python -m harness run`，因为新 CLI 不接受旧参数，也没有等价的平台 Dataset 执行闭环。

### P1-3：部署脚本自动执行 Java 全量，且没有测试刚部署的 app

证据：`scripts/deploy-customer.sh:600–625` 的 `step11_real_backend_probe` 在存在 EVAL 身份时执行
`python3 -m harness run --backend java`，缺省加载全部 biz，默认部署流程调用此步骤。

影响：把原有限范围探针替换成业务黄金集全量，扩大真实写入范围。
Harness 又临时启动另一 app，不验证刚部署服务；结合缺 V2 问题，甚至可能只得到静默失败。

建议：部署预检以存活／依赖检查为主；黄金集 Java 写入由用户显式授权并选择文件／用例范围。
不要自动全量，也不要重新建立与黄金集重复的探针验收层。

### P1-4：CI 没跟随配置和测试范围迁移

证据：

- `.github/workflows/ci.yml:73–75` 仍执行已删除的 `tests/test_import_without_env.py`。
- CI fast／slow 环境没有 `LLM_MODEL_STANDARD / THINKING / COMPLEX`，而
  `app/config.py:33–35` 本轮将三项改为必填。
- 以 CI 占位配置、禁止读取 `.env` 离线构造 `Settings`，得到上述三个字段的 `missing`。
- CI `:52–53` 仍运行 `harness/evaluators/evaluators.test.js`，与用户“不维护非 app 核心测试”的范围不一致。

影响：本地 `.env` 能掩盖模型字段缺失，但干净 CI 环境不能；无配置导入步骤必定找不到文件。

建议：补齐 CI 必填配置占位，删除已退役测试步骤，按用户要求收敛测试对象。
保留必要 lint／类型／数据与文档一致性检查，不通过恢复支撑测试或给模型加默认值掩盖迁移缺口。

### P2-1：本地评分已接上，但 Langfuse 完整结果上传尚未接上

证据：

- `harness/http_evaluation.py:43–59` 调用 Python `score_intent`，本地评分无需等待平台。
- `intent_runner.py:82`、`multi_turn.py:151–152` 在评分前写用例根输出，未包含最终 report、diff 或 intent_scores。
- `harness/langfuse_client.py:135–153` 的 `record_business_score` 存在，但新 CLI／HTTP 评分路径未调用。
- CLI 结束没有调用该模块的 `flush()`；删除旧脚本后，黄金集 `run` 也未接上 Dataset Experiment。

影响：存在追踪初始化或输出上传，不代表已经具备完整 Experiment／Score 闭环。
平台 JS Rule 可能产生自己的分数，不能将其与本地正式判定混称为同一已核验结果。

建议：正式判定继续使用本地评分；上传最终报告及相同确定性 Score，并在批次结束导出。
平台可选、上传故障不修改评测结果；SDK 入队和平台已入库必须区分，不恢复“等待平台评分”的门槛。

### P2-2：选择、报告与中断恢复仍未统一

证据：

- `harness/golden.py:319–322` 拒绝混用 biz 和 intent 文件，即使传 `--group all`。
  离线选择这次意图文件与业务文件，复现 `ValueError: all --file entries must belong to the same dataset group`。
- `harness/cli.py:133–140` 将 `skip_reason` 用例从待执行列表排除，只打印数量，未纳入最终 requested 汇总。
- `:157–173` 完成全部用例后才写 `.harness-runs/`；中断前没有逐条落盘报告，且目录位于仓库内。
- run ID 精确到秒，快速并行启动存在输出目录碰撞风险。

建议：按文件目录决定评分套件，支持跨组的指定文件组合；保留 requested／已执行／未执行完整计数。
逐条落盘，报告统一写仓库外任务目录，使用不碰撞的运行 ID；不再增加用户拒绝的 `--out` 等参数。

### P2-3：旧核心 smoke 仍按旧入口准备输入，类型检查也有残留

`tests/test_smoke.py` 本轮复验 4 项失败：模型请求数为 0，业务调用未发生。
测试未提供 V2，按新入口 V1 普通静默；这不是 app 丢失模型请求。
应按新规则更新业务测试输入并保留单模型／单提交和多轮历史断言，不回退入口规则。
新人文档改用已通过的入口专项，不再将该旧 smoke 宣传为可直接通过的快速检查。

`ruff check app/ tests/ harness/` 通过；`python -m mypy app/ harness/` 失败，
唯一诊断是 `app/config.py:144` 的 `Unused "type: ignore" comment`。
本轮审阅未修改 app 来消除该诊断，不能宣称静态检查全部通过。

### P2-4：新增业务防御逻辑仍缺专项回归证据

本轮新增了 `needs_close_order_context`、互换待补对手广播、引用顺序定位、有效锁替代和
`validate_applied_picks` 提交边界复验。现有选择测试通过，但没有搜索到这些新增分支的专门测试覆盖。
这不等于已证明实现错误，却是涉及订单范围和字段锁的验收缺口。

建议只补 app 核心行为测试：

1. 普通身份／查询／确认不触发平仓预查询，真实补参才读取上下文。
2. 裸对手选项仅补引用中的待补订单，不覆盖已完整订单；缺失目标整批拒绝。
3. 引用顺序与出站数组顺序不同，仍能定位正确订单。
4. 已验证选择可替代候选锁；伪造 `.selection`、篡改 evidence 或字段值不得进入提交。

不新增 harness、mock_api 或脚本单测来代替这些核心行为断言。

## 二、Dify 对齐证据与边界

### 已取得证据

1. 用户提供的 workflow 含 76 个节点、107 条边。入口先判断
   `existing_command == "1" && at_bot == "0"`；否则进入版本分流节点 `1789860000001`。
2. 提取该 Dify Code 节点并与 app 的 `select_entry_branch` 对照：
   版本 `None / 空 / V1 / V2 / UNKNOWN / v2` × 快速标记 `0 / 1 / None` ×
   存量标记 `0 / 1 / None` × @ 标记 `0 / 1 / None`，共 **162 组、0 差异**。
3. V1 快速走存量查询、V1 普通静默、V2 快速走快速询价、V2 普通走业务前置路由；
   非法版本静默，非 @ 存量优先。app 图边按此接线。
4. `tests/domain/test_request_cleaning.py` 已覆盖三产品烂 JSON 回退、有效类型清洗和身份结构拒绝。
   本轮与入口、互换选择、平仓引用相关的小范围测试共 **82 项通过**。

### 不应称为逐字／逐拓扑对齐的部分

Dify 的清洗节点递归处理 `null`，app 还按 Java DTO 做有审计的类型兼容清洗和字段省略；
对于有效 JSON 但身份／订单结构损坏，app 明确拒绝，不把它当烂 JSON 回退。
Dify 原流程的多次模型请求、图片处理、本地证券识别和业务默认补齐，也不能机械迁入 app：
按 ADR 0031／0025／0027，app 保持单次模型预算、暂不处理图片、证券识别交 Java、Code 不做业务换算或默认补齐。

因此，“对齐”应逐条以入口、动作、身份范围、实际 wire、真实回复和批准的差异清单验收，
不是只看节点名称相同或返回了订单卡。本轮没有完成所有动作／产品的差异矩阵和真实验收。

## 三、此前三个指定文件的真实评测记录

以下是此前按用户要求向已有 `127.0.0.1:8000` 服务执行的结果，本次 review 没有重跑：

| 文件 | 总数 | PASS | FAIL |
|---|---:|---:|---:|
| `intent/swap_instrument.jsonl` | 348 | 341 | 7 |
| `biz/swap_prod.jsonl` | 123 | 62 | 61 |
| `biz/swap_prod_acceptance.jsonl` | 162 | 0 | 162 |
| 合计 | 633 | 403 | 230 |

- 意图：4 条标的匹配差异、3 条字段／动作证据错误。
- 生产业务：58 条卡片断言差异、3 条节点错误（证据或超时）。
- 验收业务：159 条卡片差异、3 条解析证据错误；授权环境缺少预期对手“聚鸣价值精选”，
  大合约编号／对手／确认卡与原黄金期望不符。算法等差异仍需逐条对照实际提交，不统一归咎于环境。
- 业务共 285 条，279 条返回 Java `code=0`；这不等于卡片／参数断言通过。
- 两条冒烟中意图通过，业务进入互换并取得 Java 回复，但业务断言失败；数量 1453／3071 已实际提交，
  Java 返回缺持仓及数量待补，不能归类为 app 没提取数量。
- 主图请求通过 runner 的 `before_turn` 显式注入 V2；冻结意图独立调用解析节点。
  这些结果不能用来证明正式 CLI 已可复现，也不能证明已有服务未连接审计数据库。

完整逐条结果保留在仓库外：
`C:\Users\PC\AppData\Local\Temp\aigc-langgraph-tmp\swap-eval-20261009-185859`。
早一轮模型网关／代理失败和中断的结果不混入本次质量统计，不替换其中的失败为通过。

## 四、文档整改与仍需处理的内容

本轮整理新人入口：根 README 不再展开目标、进展、计划；提供安装、配置、无数据库调试、启动、
V2 请求、两类测试与学习导航。测试／Harness／数据集／Langfuse 的实操说明应清楚区分
本地判定、追踪上传与尚未接通的平台实验；平台触发暂不作为可用入口推荐。

本次不修改纪律真源、ADR 正文或生成物。owner 需更新：

- `CLAUDE.md`、`.claude/rules/testing.md`、相关 skill 与 `scripts/CLAUDE.md` 的旧命令和非核心测试范围；
  之后通过 `sync_agents_md.py` 生成，不手改 AGENTS／`.agents`。
- ADR 0002／0030 的入口描述、ADR 0021 的已删测试引用以及节点回归定位；节点调试保留不等于增加黄金集之外的验收层。
- 部署文档应同步 P1-3 的最终执行策略；历史报告保留原时点命令，不追改快照。

当前动态待办统一归入 `docs/work-plan.md`，不要再写入根 README。

## 五、验证记录

- 小范围核心 pytest：82 PASS，19.41 秒（关闭 MySQL checkpoint／Langfuse，启用 UTF-8）。
- Dify 入口离线对照：162 组、0 mismatch，无模型或后端请求。
- `python -m harness run --help`：确认 `run` 仅四类参数，旧 `--no-judge` 等不受支持。
- 混合文件选择：离线复现失败，见 P2-2。
- 无 `.env` 的 CI 占位配置：复现三个模型字段缺失，见 P1-4。
- 另跑旧 smoke 与字段锁提交测试：4 FAIL（旧 smoke）、3 PASS（字段锁提交）。未修改这些测试或 app。
- ruff 通过；mypy 175 个源码文件中 1 项诊断，见 P2-3。
- 文档布局／命名／链接、数据集一致性、AGENTS 同步检查通过。
- ADR 引用检查失败：ADR 0002 两处已删脚本、0021 一处已删测试、0030 两处已删评测脚本引用，共 5 项。按规则保留正文，交 owner 更新，不恢复退役文件来掩盖检查。
- 未运行全量 pytest、Java 重放、真实模型批量评测、部署流程或 Langfuse 入库核验。

以上验证不抵消 P1 发现；实现完成、专项通过、外部数据阻塞和待用户验收必须分别记录。
