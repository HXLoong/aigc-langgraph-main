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
- 互换拒绝集已裁决：以 biz 出卡为准（2026-09-30），`intent/swap_rejection.jsonl` 与 `rejection-match` 评分链一并退役；基线由意图集 391 条重定为 364 条，口径见 `docs/reports/2026-09-30-swap-rejection-vs-biz-adjudication.md`。不通过修改运行代码恢复已废弃规则。
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
- 离线验证：核心及调用链 453 项、其余受影响调用点 220 项通过（两批文件不重叠）；本轮范围 ruff、mypy（177 个源码文件）、ADR / 数据集 / 阈值 / 规则同步检查与部署脚本语法检查通过。未跑全量 pytest 或真实模型 / Java / GOATS，未提交或推送。
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

### 互换显式字段提取与比例修复（2026-09-30）

- 核对用户提供的 Dify 历史快照：市场只从明确市场词提取，币种只从金额短语中的币种标记提取；
  港股/美股及证券名称、代码不推导币种或交易市场。仅金额倍率不补 CNY，金额中明确的“元”可提取 CNY，复合币种词优先。
- 更新互换字段描述、互换与跨产品联合提示词：金额倍率在唯一一次模型提取时展开，
  明确方向和金额单位不能随缺省市场/币种一起丢失；市场词里的“股”不作为数量单位。
  保留来源检查、单次模型请求与原有类型清洗，不在 Code 中换算金额、补币种或证券事实。
- 标的业务集 `case_14` 的默认 POV 预期改为 9%；`case_73` 按用户确认将输入及成功卡片预期均改为 9%，
  同源意图正文同步。历史节点标注仍保留实际采样的 25% 原文，不改写旧 Trace 的输入。
- 31 条相关业务用例补充实际参数约束；修复阶段同一版本业务复验 **38/40**，其中 31 条的已标注参数约束 **31/31** 通过，
  9 条原先通过的业务对照保持通过。节点专项保存 13 条真实模型输出，原始候选比较 12/13；
  唯一差异为股数的纯数字字符串，经现有生产清洗转换为 Java 整数后复核 **13/13**，原始结果保留。
- 该阶段的两条业务失败：`case_88` Java 默认返回 `GC2806.CMX`，原断言要求主选 `GCM28.CMX`；
  `case_90` 完整提交“恒生科技指数2706”，Java 却提示标的池查不到 `HTIF2602.HK`。阶段报告保留原始失败。
- 相关离线测试 **54 项通过**；ruff、mypy、数据集、ADR、文档及 AGENTS 同步检查通过。
  该阶段仅相关用例与对照复验，未重跑 90 条全量或真实成交；参数断言存在不代表全部订单字段已完整标注。
- 证据与最终 HTML/Markdown 报告保留在 `/opt/work-file/code-tmp/aigc-langgraph-tmp/swap-extraction-fix-20260930-105544/`，
  早期批次单列，不拼接不同版本的通过项；Langfuse 仍存在服务端导出超时，本地返回关联 ID 不作为完整入库证明。

### 四类数据集统一回归（2026-09-30）

- 用户确认 `case_88` 的正确预期为 `GC2806.CMX`；业务集补齐交易对手文本断言，同源意图集仅同步
  `reference.backend_codes`，产品、意图和标的原文断言不变。旧报告与 `黄金数据集.xlsx` 未改写。
- 最新同版本业务 **104/106**、同源意图/提取 **106/106**：期权询价 **4/4**、开仓 **6/6**、
  平仓 **5/6**、标的智能化识别 **89/90**；实际执行 **274/280** 步。
- `case-034` 超过 14:30 前置窗口，六步业务未执行，仍需在规定时段复验；`case_90` 再次出现错月，
  本轮 Java 排序输入的 100 个候选不含 `HTIF2706.HK`，最终选择 `HTIF2602.HK`。未修改 Java 或 Dify 工具。
- `case_88`、`case_91` 本次通过；开仓和平仓完整生命周期均完成确认、撤单及“已撤单”终态查询。
  环境为真实模型、本地 Java、期权 GOATS Mock，不代表真实交易验收；本轮未修改代码或数据、未重试替换失败结果。
- 本地记录完整，业务评分 **106/106** 已读回；意图平台评分未读回，服务端 Observation 仍有导出缺失，不能宣称完整追踪闭环。
  完整输入、预期、输出和错误报告：`/opt/work-file/code-tmp/aigc-langgraph-tmp/four-suites-eval-20260930-150201/`。

### Dify 入口、Harness 收敛与互换评测（2026-10-10 审阅）

- 新入口以用户提供的 `场外交易-scz.yml` 为准：非 @ 存量指令优先；缺省 V1，V1 普通静默，V2 普通业务／快速询价分别分流。离线 **162 组入口组合、0 差异**；本轮相关核心测试 **82 项通过**。这仅是局部证据，不代表所有产品／动作已完成 Dify 行为验收。
- 此前向已有 `127.0.0.1:8000` app 执行三个指定文件：意图 `swap_instrument` **341/348**、业务 `swap_prod` **62/123**、`swap_prod_acceptance` **0/162**；总计 **403/633 PASS**。主图请求经 runner 的 `before_turn` 显式注入 V2，**不是正式 CLI 的验证结果**。本次 review 未重跑 Java。
- 主要失败为标的／证据错误、业务卡片差异及外部身份数据不匹配；验收集预期对手“聚鸣价值精选”在授权环境缺失。业务 **279/285** 返回 Java `code=0`，但不能据此当作断言通过。算法等差异仍需对照实际提交，不能一律归为环境问题。
- 逐条结果在仓库外 `C:\Users\PC\AppData\Local\Temp\aigc-langgraph-tmp\swap-eval-20261009-185859`；审阅与执行边界见 [报告](./reports/2026-10-10-dify-harness-review.md)。早一轮网关／代理失败和中断结果不混入通过率。
- 新人根 README 已按安装、配置、启动、V2 调用、两类测试与学习导航整理；主要实操说明改为同一 Harness／本地评分口径，不再推荐已删脚本。目标仍归 ADR，动态状态仅在本页维护。

### Harness、CI 与部署整改（2026-10-10）

| 范围 | 已实施内容 | 验证边界 |
|---|---|---|
| Harness 固定入口 | 删除临时 app 启动模块，CLI 固定请求已有 `127.0.0.1:8000`；四类 run 参数不变；后端由已有服务启动配置提供 | 离线 MockTransport 核对 URL，CLI 禁止 Popen 检查通过；未重放 Java 写入 |
| 评测输入与选择 | 评测输入缺省 V2，显式 V1、null、空串和存量标记原值透传；支持跨 biz／intent 文件；平台投影保留入口字段和块级断言 | 离线 HTTP、加载、选择与投影检查通过；app 默认 V1 不变 |
| 报告 | 每条写 results.jsonl，收尾汇总与 Markdown 写仓库外；保留完整 requested、SKIP 与未执行分母；批次 flush | 离线生成路径与本地判定通过；强制终止进程时仅保证已写逐条结果，不保证执行 finally |
| 平台触发 | webhook 改为内部 `harness.remote_experiment` 适配，复用 run_case 和本地评分；平台条目绑定 git 用例并核对输入与期望；SDK Experiment 输出 report 与确定性 Score | 签名 ASGI、错误范围与 mock SDK 流程通过；真实平台触发、入库与父子关联待验收；CLI 追踪不自动生成 Experiment |
| CI | 按用户确认仅保留 ruff、mypy、app 核心快速／全量 pytest；移除五项一致性检查，不新增替代门槛；共用模型与依赖占位配置 | 黄金集通过 Harness 单独评测，不进入 CI 自动执行；历史 ADR 引用问题归文档维护，不再阻塞 CI |
| 主图冒烟 | 原先 4 FAIL 为输入缺少 V2；测试按新入口传 V2 与 @，保留原断言 | 主图冒烟及入口专项共 31 PASS；未运行完整 pytest |
| 部署 | 删除自动 Java 黄金集全量；移除虚构账号业务 smoke，自检只核对健康、依赖和 OpenAPI 入口 | bash -n 通过；未实际部署，服务检查不代表业务验收 |
| 文档 | 根 README 精简为配置、启动、测试与文档索引；同步开发、测试、Harness、数据集、mock、Langfuse 与部署说明 | 实操文档不再描述临时服务或未透传版本；审阅报告保留其当时快照 |

离线证据位于 `C:\Users\PC\AppData\Local\Temp\aigc-langgraph-tmp\harness-offline-20261010`。
这些记录使用假 HTTP 与 SDK，只证明工具链路径，不是三个黄金文件的模型或 Java 验收结果。

**最大跟量公共 prompt 核对：未完整对齐，未修改其业务语义。**

- Dify 节点 `17797951842080` 输出公共 keywords 和 hasFastExecutionIntent 规则。keywords 注入互换、期权、平仓意图，字段规则注入期权下单与平仓参数；并非所有互换参数节点都消费公共字段规则。
- 公共规则规定“最大跟量”优先 true，不被价格、POV／TWAP 或明确比例覆盖；其它快速执行词仅在没有具体跟量比例时 true；普通“跟量／市价跟量”不是快速执行；仅判断机器人名过滤后的本次输入。
- app 三套提示词目前只有概括性意图说明，未完整表达上述优先级与词语边界，没有对应公共 prompt 资产。仅存在同名字段不能证明行为对齐。
- Dify 自身存在矛盾：公共规则未命中 false，期权下单稀疏段未命中 null，平仓旧段落又把普通跟量设为 true。app 当前保留稀疏 null 和非 null 字段证据，不能擅自补无证据 false。下一步需明确采用公共判定规则与稀疏提交边界，再补相关回归与提示词。

**剩余验收与 owner 配套：**

1. 最大跟量规则收敛及三产品专项；平仓预查询门控、待补对手范围广播、引用顺序定位与锁定边界复验仍按相关核心范围执行。
2. 真实 Langfuse webhook → SDK Experiment → HTTP → Score 入库验收；先同步包含版本字段的 Dataset，不将 202 或关联 ID 当作成功。
3. owner 更新 `CLAUDE.md`／`.claude/**`／`scripts/CLAUDE.md` 的旧命令与测试范围，修正 ADR 0002／0030 的已删脚本引用、0021 的已删测试引用，再生成 AGENTS／`.agents`。本轮未修改受保护真源或 ADR 正文，不通过恢复退役文件规避检查。
4. 完整 pytest、三个指定文件的统一 Java 复验与真实部署尚未执行；保留前次批量结果，不宣称新 CLI 全量验收通过。

## 2. 客户现场部署与运维（工具与待验收事项）

- `scripts/deploy-customer.sh` 提供部署、健康与接口自检，不自动执行黄金集；语法检查通过，真实部署待验收。另有 `.env.customer.template` 与 `infra/langfuse/` self-hosted 栈
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
- `docs/testing/README.md` · app 核心测试与黄金集 mock／Java 执行
- `docs/operations/on-call-runbook.md` · 值班手册 / `docs/operations/troubleshooting-sop.md` · 生产排障
