# 工作计划 · 原生 LangGraph 重构 + 数据集评测 + Harness 工程

> 目标口径：[ADR 0030](./adr/0030-goal-restatement-native-langgraph-dataset-eval-harness.md)。
> 不维护任务码与 owner 表。需人工裁决 / 执行的项以 GitHub issue 跟踪（`ready-for-human`），完成项直接从表里划掉。

## 1. 当前重构与验收状态

本轮根据全部现役 ADR 重构；当前代码作为本地检查点提交，尚未完成业务验收。合并 main 后数据源为 `tests/datasets/`；不恢复退役数据目录。

| 范围 | 当前实现 | 验证状态 |
|---|---|---|
| ADR 0031 一次请求 | 主图规则准备 → 四选一联合 PromptSpec → 三产品确定性执行；真实 HTTP 请求预算共享，LLM 零重试 | 真实 SDK 请求预算与关键子图通过；交付快照完整 pytest 2450 通过、2 跳过 |
| ADR 0021 / 0027 | 本次稀疏参数与来源、选择范围、字段锁定；删除业务归一化和默认值链；确认不重建旧订单 | Java 参数透传、来源、确认与字段锁专项通过；期权剩余外部契约/时段限制见下文 |
| ADR 0026 | 删除消息占位、旧响应回放、重投静默与对账运行代码 | 独立调用和失败后新调用专项通过；历史数据库表未删 |
| ADR 0020 / 0031 附件 | deepseek-v4-pro、文本与全量 Excel，一次请求；图片及混合图片明确拒绝 | 入口和 Excel 行证据覆盖专项通过；真实 Excel 标注验收仍待补 |
| ADR 0004 Tracing | Experiment/用例/HTTP/服务端共用 Trace；根与子 Observation Session 一致 | 真实 SDK 并发/跨 HTTP 测试通过；平台实查四轮同树同 Session、评分同 Observation |
| ADR 0005 / 0029 | HTTP 执行、公共确定性 diff、SDK Experiment/Score；节点标注发布/导出/HTTP 回归入口 | 字段失败、缺轮/缺期望、写节点 SKIP 专项通过；审阅节点样本仍缺少，不宣称节点 Dataset 全通过 |
| 图文档 | [主图及全部子图](./architecture/main-graph-flow.md) 分文件维护 | 已按最终编译拓扑核对；主图链接独立子图文档 |

### 期权先行验收

范围为期权询价、开仓、平仓：16 个业务用例、50 轮，以及对应 16 个冻结意图用例、50 轮。运行环境为真实模型 + 本地 Java + 本地 GOATS Mock；成功不代表真实 GOATS 交易验收通过。

- 用户已确认：先执行现有断言，参数覆盖缺口单列；不改 expected 提高通过率。
- `case-027/029/032/033` 等写类轮缺少结构化参数期望，报告以 `parameter_assertion_coverage` 标为待业务验收。字段存在性也不等同于完整字段覆盖。
- 意图套件只验产品与意图，不承担业务参数覆盖。
- 互换拒绝集仍有旧本地数字拒绝断言，与 ADR 0027 冲突，留待业务方重新裁决；不通过修改运行代码恢复已废弃规则。
- 本轮证据与恢复点在 `/opt/work-file/code-tmp/aigc-langgraph-tmp/adr-refactor-20260928/`。测试通过、未运行、外部阻塞分别记录；完整 pytest 与全部静态检查完成前不宣称 CI 全绿。

### ADR 重构阶段验证记录（清洗与配置迁移前）

- 期权冻结意图：该阶段完整批次 **16/16 用例、50/50 轮通过**，报告 `/opt/work-file/code-tmp/aigc-langgraph-tmp/adr-refactor-20260928/intent-final-v2.json`。
- 期权业务：完整批次 `business-final/local-20260928-161031` 为 **12/16**；其中 case-028 本次 POV 方式字段遗漏已修复，并在 `business-pov-fix/local-20260928-162420` 的三轮专项通过。没有把不同版本批次拼成一次全量结果。
- case-023/024：普通入口提交雪球/参与型看涨，Java 返回“普通询价仅支持欧式看涨”。用户确认保留原数据、原断言和失败，单列入口/业务契约冲突。
- case-034：当前重验晚于其固定的 14:30–14:50，Java 正确拒绝过去的开始时间；提取参数与预期一致。较早批次在有效时段曾通过，最新版本业务终态仍需有效时段重验。case-034-lifecycle 的市价生命周期已通过。
- 参数覆盖缺口逐轮记录在 `/opt/work-file/code-tmp/aigc-langgraph-tmp/adr-refactor-20260928/parameter-coverage-gaps.md`，不修改已有 expected。
- 交付快照完整 pytest **2450 passed / 2 skipped**；ruff、mypy 和五项一致性检查通过。原工作区文档检查仍受用户未跟踪的本地导读资料、空目录与 .DS_Store 影响；保留这些资料，在仓库外仅包含本轮交付文件的快照完成验证，没有放宽检查规则。
- 实际 Langfuse 业务样本：127 个 Observations、一个根、四个 Generation，父链完整且 Session 一致；`det_business_pass=True` 已读取确认关联到用例 Observation。业务和意图输入、输出、来源、差异、版本与 Scores 保留在对应记录中。

### 后续独立验收

- case-023/024 需业务方裁决普通/快速入口契约；case-034 在有效时段重验。
- 补齐写类参数标注、节点审阅样本。节点 Dataset 功能和安全门已有实现，但没有有效标注基线时仍不能宣称该层验收通过。
- 互换真实业务、Excel 字段准确率、生产同拓扑性能基线和 7 天观察未验收；本轮业务环境为真实模型、本地 Java、GOATS 写路径 Mock。
- 旧幂等表历史记录保留策略由独立数据库变更处理，本轮不删表、不清数据。
- Java 源码、配置、wire 协议未改；协议原生化仍暂缓。Langfuse SDK/平台不升级。远程推送与部署另行执行。

### Java 请求清洗（本轮追加）

- 三产品动作节点只准备请求，父图统一经过 `option/swap/close_clean_request`，再进入写入 `submit` 或独立只读 `query_backend`。
- 不兼容业务字段有记录地省略；保留原模型标量、来源账本、实际出站请求与清洗原因。空 JSON 参数字符串兼容严格沿用 Dify 三分支请求形状。
- 主图唯一模型请求额度、Java 真实回执、订单身份/选择范围及写节点不重试保持原约束；参数字段省略后继续交 Java 处理。
- 验证记录位于 `/opt/work-file/code-tmp/aigc-langgraph-tmp/java-request-cleaning-20260928/`；本轮仅专项和受影响回归，不把早先完整 pytest / 真实期权批次当作本次验收。
- 本轮受影响回归 1265 项通过；客户端/提示词与边界补充 165 项通过（两批有重叠，不相加）。ruff、mypy、ADR/数据集/规则同步检查通过。未运行真实模型/Java/GOATS 验收；文档全目录仍有用户本地资料的原有布局问题，本轮不处理这些资料。

### 通用 LLM 配置（2026-09-28 追加）

- 模型连接与三角色变量改为 `LLM_*`；保留 STANDARD / THINKING / COMPLEX 独立配置，工厂改为 `get_llm_*`。STANDARD 为唯一业务解析模型，THINKING 供离线生成，COMPLEX 当前业务不用，structured 复用 STANDARD。
- 必填 `LLM_PROVIDER=deepseek|qwen|openai_compatible`，不再按模型名猜测厂商。旧 `QWEN_*` 配置明确拒绝，不保留别名；错误只显示键名。一次真实模型请求与零重试约束保持。
- 本地 `.env` 已完成键名迁移，保留原地址、密钥、三个模型值及其他配置；移除退役 VL 键。CI、部署模板、健康探针、评测元数据、文档与生成的代理规范已同步；业务回归预检只调用 STANDARD。
- 离线验证：核心及调用链 453 项、其余受影响调用点 220 项通过（两批文件不重叠）；本轮范围 ruff、mypy（177 个源码文件）、ADR / fixture / 阈值 / 规则同步检查与部署脚本语法检查通过。未跑全量 pytest 或真实模型 / Java / GOATS，未提交或推送。
- 仓库全目录文档检查仍有既存 `.DS_Store` 与 `docs/tickets/` 布局问题；扩大到所有脚本的 ruff 另有 9 项既存告警，本轮未涉及这些脚本，不宣称全仓检查通过。
- 待部署维护者迁移 GitHub secrets `LLM_API_BASE` / `LLM_API_KEY`，填写 variable `LLM_PROVIDER`，按需迁移三个 `LLM_MODEL_*` variables；本轮未改远程设置。配置更改后重启服务，切换业务模型或网关后重新验收。
- 变更与验证证据：`/opt/work-file/code-tmp/aigc-langgraph-tmp/llm-config-rename-20260928/`。

### 最新期权回归与报告修复（2026-09-28）

- 用户确认使用 `tests/datasets/biz/option_inquiry.jsonl`、`option_open.jsonl`、`option_close.jsonl` 和 `tests/datasets/intent/option.jsonl`、`option_close.jsonl`。正式批次完整执行 32 个用例、100 轮，数据集指纹未变。
- 业务 **11/16**：询价 1/4、开仓 5/6、平仓 5/6；开仓/平仓下单、撤单和终态查询生命周期均通过。case-021/028 存在数字字符串与数值的参数断言差异；case-023/024 保留入口契约冲突；case-034 存在固定时段过期及限价类型差异。
- 意图 **15/16**：询价/开仓 10/10、平仓 5/6；case-032 第 4 轮模型补出未在当前引用中的合约号，来源校验拒绝。未通过重跑或修改断言替换本批次失败。
- 环境为真实模型、本地 Java、GOATS Mock；命令级输出容量 8192、可信 traceparent 开启。14 个业务用例的参数标注缺口单列，不能宣称完整参数或真实 GOATS 验收通过。
- Langfuse 四个样本父链与 Session 一致，Generation 数等于执行轮数；16 条业务分数与本地状态、Observation 均核对一致。
- 报告生成器补全原始输入/期望、完整引用、逐轮实际输出、字段差异、执行异常及未执行轮次；本次结果另生成可筛选 HTML、Markdown 和完整 JSON。报告修复专项及受影响测试 253 项通过，未再次请求模型或后端。
- 正式批次和详细报告保留在 `/opt/work-file/code-tmp/aigc-langgraph-tmp/option-eval-20260928-1837/`；报告修复证据在 `/opt/work-file/code-tmp/aigc-langgraph-tmp/option-report-detail-20260928/`。上述目录与本地旧报告不纳入代码提交。
- 本地检查点不代表上线放行；以上来源校验、参数评测契约和业务契约问题继续待处理。

### 期权入口与评测修复（2026-09-29）

- 以用户最终定义为准：case-021 保持普通询价，原文、at_bot=true 和原参数期望不变；case-022/023/024 为正常快速询价，显式 fast_query="1"，保留成功卡片预期。
- 修复 JSONL 加载、派生、Dataset 投影和 HTTP runner 对快速标记的传递；entry_route 输出 entry_branch，快速入口确定性输出 option/new_inquiry，快速节点保留 backend_request。对应意图样例通过真实入口节点 HTTP 评估，不调用普通解析器或业务后端。
- 确定性断言升级 deterministic-v2：明确数值字段按有限 Decimal 精确比较；整数传输类型、Boolean、身份、枚举、时间和文本保持严格检查，不做单位换算。原值、类型和实际出站请求均保留。
- 平仓提示词明确区分当前引用含 CO+OPT（两者均提取）和仅含 CO（不补历史合约）。期权字段描述补明确算法词连比例时同时提取本次方式，避免“改POV12”只提比例；旧卡片字段仍不得回填。
- case-034 按用户要求保留固定 14:30–14:50，增加 execution_before=14:30。开始实施时已为14:33，过期前置条件在任何业务请求前失败，保留完整用例分母和六轮未执行说明；需要下一有效时段补测，不能改成拒绝成功或计PASS。
- 本轮完整 pytest 2528 passed / 2 skipped；ruff、mypy（179源码文件）、ADR/fixture/文档布局与代理规则同步检查通过。既存两份 .DS_Store 与仅含空目录的 docs/tickets 已无损迁至任务目录 local-artifacts，不删除用户文档或旧测试报告。
- final-v3 同版本正式复测：意图 16/16 通过，业务 15/16（15 个实际执行用例全部通过，case-034 前置条件未满足、六轮未执行）；实际执行 94/100 轮。开仓/平仓完整生命周期均通过；前面的失败、专项和用户更正前批次分别保留，不拼接为全量通过。
- 最终 Langfuse 样本父链和 Session 一致，快速分支本项目 Generation=0；16 条业务评分值及目标 Observation 已核对，最后一条因平台导出错误按原始结果补写，未重跑交易。
- 证据和逐轮报告目录：`/opt/work-file/code-tmp/aigc-langgraph-tmp/option-fix-20260929/`。Java 源码、配置和时间上限未修改，旧批次评分不回写。

## 2. 客户现场部署与运维（已就绪的能力）

- `scripts/deploy-customer.sh` 一键部署 + smoke 自检；`.env.customer.template`；`infra/langfuse/` self-hosted 栈
- `scripts/rollback_canary.sh` 应急回切、`scripts/drill_smoke.sh` 演练 smoke、`scripts/canary_status.py` / `scripts/metrics_snapshot.py` 灰度状态与指标快照、`scripts/run_alerts.py` 阈值告警干跑、Grafana 面板模板（`infra/`）
- `docs/operations/on-call-runbook.md` 值班手册（严重等级对齐 ADR 0019）；回切演练在首次切流前执行
- `scripts/shadow_compare.py` 为可选对照工具，不进任何门
- 待办：离线依赖包（pip wheel + docker save）；runbook 附录 A 真实 URL / 联系人回填与回切演练后升 v1.0（#234）

## 3. 后续优化方向（不阻塞主线）

- 评估 → 优化 → 再评估的自动闭环：错例聚类 → 改进 patch → A/B 评估
- Agentic memory：跨会话经验记忆 + 客户级隔离
- 回流集自动化：生产流量 → D 桶 + 人工标注 UI + 客户内网合规同步（需先与客户对齐"AI 数据标注员"角色）
- 提示词持续调优与解析契约对比（当前基线为 deepseek-v4-pro，可经通用配置切换并重新验收，ADR 0020；暂不建设多模型矩阵）

## 4. 相关文档

- `docs/adr/README.md` · 决策索引与待办表
- `docs/testing/README.md` · 测试分层与真后端切换
- `docs/operations/on-call-runbook.md` · 值班手册 / `docs/operations/troubleshooting-sop.md` · 生产排障
