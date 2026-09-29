# Langfuse 操作手册资料审阅记录

- 日期：2026-09-29
- 本次范围：A1 · Trace 查看与排障
- 记录人：Codex
- 交审阅人：@HXl
- 状态：待审阅；原资料未改写，未修改 SDK、自托管部署或平台数据

## 已核对的事实

| 项目 | 证据与结果 |
|---|---|
| 本机自托管版本 | `LANGFUSE_BASE_URL` 的 `/api/public/health` 只读查询返回版本 4.46.0 |
| Python SDK | 当前 Python 环境的包元数据为 4.15.0；[pyproject.toml](../../pyproject.toml) 约束主版本为 v4 |
| 只读 API | 使用本机已有 langfuse-cli 1.2.4 查询 Observations，HTTP 200，返回记录的项目身份与指定项目相符；未输出或保存输入、输出、凭据 |
| 测试用例链路 | 本次按 `name=regression_case` 查询未返回记录，未据此断言项目中不存在实验；未新建用例或重跑交易 |
| `turns` 字段 | 核对 [evaluation.py](../../harness/evaluation.py)、[http_evaluation.py](../../harness/http_evaluation.py)、[multi_turn.py](../../harness/multi_turn.py) 和 [intent_runner.py](../../harness/intent_runner.py)；区分富集报告与用例节点的原始轮输出 |
| 图片 | A1 复用 `00-observability-nav.png`、`39-tracing-filters.png`，目视确认只含导航、控件、计数和节点名；没有复用含客户原文或交易字段的详情截图 |
| 官方资料 | 已查阅 [数据模型](https://langfuse.com/docs/observability/data-model)、[列表说明](https://langfuse.com/faq/all/explore-observations-in-v4)、[筛选语法](https://langfuse.com/docs/observability/features/filter-search-bar) 和 [CLI](https://langfuse.com/docs/api-and-data-platform/features/cli) |
| 命令可用性 | 已通过 `node` 直接执行现有 CLI 的帮助和只读查询；PowerShell 的 `npx` 被执行策略拦截，离线 npx 也缺少包解析缓存，因此正文使用 `LANGFUSE_CLI_PATH` 指向现有文件，不修改系统策略或安装依赖 |
| 文档检查 | ADR 引用检查通过；文档布局检查的 307 项失败全部来自已有 `.pytest-tmp`、`.tmp`、`tmp` 目录中的旧引用，`docs/` 内无发现。本次不清理用户临时目录、不修改检查脚本 |

## 资料差异：交审阅人处理

下表只记录原文位置、核对依据和建议，不在任务手册中建立第二份契约。

| 位置 | 发现的问题 | 审阅依据与建议 |
|---|---|---|
| [workflow-guide.md](../langfuse/workflow-guide.md) §5.1、§6、§8.2 | 写有“`--local` 不创建 Dataset Experiment”“本地不上传”，与 §8.3 的说明冲突 | [langfuse_eval.py](../../scripts/langfuse/langfuse_eval.py) 的 `run_local()` 经 `_run_items()` 调 `run_experiment()`。请统一措辞，区分本地数据来源、平台运行记录及是否绑定已有 Dataset；另与 `local_eval.py` 区分 |
| 同上 §5.1、§5.2 | 仍以 `otc-option-judge`、本地 Judge Score 为当前评分示例 | 请按 [ADR 0005](../adr/0005-annotation-roles-judge-plus-business-spotcheck.md) 与当前 [评测入口](../../scripts/langfuse/langfuse_eval.py) 复核，移除已退役入口示例 |
| 同上 §6 | 将 ticker 错误指向“ticker 子图” | 按 [ADR 0025](../adr/0025-instrument-resolution-delegated-to-backend.md) 核对，应区分 LangGraph 的表达提取错误与 Java 内部的识别错误 |
| [troubleshooting-sop.md](../operations/troubleshooting-sop.md) §1.3、§2.3 | 提到 `Traces → Group by → fail_node` 和若干 metadata 错误标志，未与本次 v4 页面、当前上报字段逐一对应 | 当前错误线索见 [tracing.py](../../app/observability/tracing.py) 与 [diagnostics.py](../../app/observability/diagnostics.py)。请实机核对后更新按钮和字段，不把旧示例当成必有入口 |
| 同上 §2.4 | 建议模型失败后切备用模型、加重试 | 与 [ADR 0031](../adr/0031-single-model-request-per-message.md) 的调用内模型零重试要求冲突，请审阅后更新 |
| [WebUI 手册](../langfuse/web-ui-operation-manual.md) §1.1.1.1 与详情截图 | 截图含历史节点名、历史条数；“默认只看根”也会受保存的视图影响 | A1 仅复用无业务内容的控件图，并标注其用途；完整详情图需从沙箱重新截图。默认筛选条件以 [官方说明](https://langfuse.com/faq/all/explore-observations-in-v4) 为核对依据 |
| [Agent Skill 与 CLI](../langfuse/agent-skill-and-cli.md) 及本地技能 | 使用 `langfuse-cli` 包名 | [官方 CLI 文档](https://langfuse.com/docs/api-and-data-platform/features/cli) 现推荐 `@langfuse/cli`，同时说明旧包仍维护。A1 沿用本机已有 CLI，本次不安装或升级；后续由维护人决定是否统一安装说明 |

## 发布前仍需验证

1. 由 @HXl 确认练习项目与样本均为沙箱测试数据，提供一条失败用例的运行名、会话 ID 和消息 ID。
2. 按 A1 分别走完三种查找路径；确认当前权限下的 `Experiment`、`Metadata`、`Session ID` 和 `input:` 搜索入口可用。
3. 打开实验条目、`regression_case`、`workflow_http` 和服务端节点，核对父子关系、轮次及富集报告位置；本次没有完成此项实操。
4. 用该测试数据补充 span 树和 `turns` 的详情截图；上传前检查客户名、证券、金额、群名、用户及订单信息、地址栏。
5. 由审阅人处理以上资料差异，填写实际验证日期与验证人后再决定发布状态。不得将本次版本/API 核对写成完整 UI 验收通过。

本次只生成仓库 Markdown，尚未写入或发布 Notion。

## A2 补充审阅记录（2026-09-29）

本节对应 [A2 · Session、User、Tag 与过滤](../langfuse/developer-manuals/a2-sessions-users-tags-filters.md)，保留上方 A1 记录不变。记录人 Codex，审阅人 @HXl；A2 状态为草稿，尚未进行沙箱 UI 验收或发布 Notion。

### 核对结果

| 项目 | 依据与结论 |
|---|---|
| 版本 | 本次读取 Python 包元数据为 4.15.0；自托管 4.46.0 沿用上方同日健康检查记录，本次未再次连接部署 |
| 会话 | `tracing.py::session_identifier` 保留符合条件的会话 ID，其他情况映射；主接口返回 `data.outputs.session_id`，节点接口返回 `tracing.session_id` |
| 用户与标签 | `routes.py::_build_run_config` 读取本轮业务 `user_id`，默认标签为环境名；`nodes.py` 不保证上报同一套 User / Tag 字段。没有核对到默认产品标签，手册不虚构 `option` / `swap` / `close` 标签 |
| 多轮 | `harness/langfuse_client.py` 与 `harness/multi_turn.py` 可把多个 HTTP 轮次挂到同一父 Trace；Trace 数和 Observation 行数均不能直接等同轮数 |
| 截图 | 目视核对后，仅复用 `00-observability-nav.png`、`39-tracing-filters.png`。`01-tracing.png` 含业务输入输出，`02-sessions.png`、`03-users.png` 含用户标识和登录信息，A2 不复用这些整页图片 |
| 官方资料 | 核对 Sessions、User Tracking、Tags、Environments、Filter search bar；确认精确匹配、查询别名、标签不可事后修改与保存查询能力 |
| CLI | 本机现有 CLI 1.2.4 的 `observations list --help` 确认 `--session-id`、`--fields`、`--limit`、`--cursor` 等参数；其输出代码确认 `--json` 包装为 `body.data`。未查询未确认归属的沙箱数据，命令未完成联网验收 |
| UI 核验条件 | 浏览器工具返回没有可连接的浏览器；`My Views`、`Columns` 入口从既有截图确认，保存弹窗和恢复行为仍待实机验证 |
| 文档检查 | A2 七节模板与页面属性、PowerShell 代码块语法检查通过；ADR 引用和生成文档同步检查通过。文档布局检查在 `docs/` 内零发现；全仓仍有既有临时目录的 307 项失效引用（`.pytest-tmp` 64、`.tmp` 242、`tmp` 1），未修改这些目录 |

### 资料差异与交审事项

| 位置 | 需要审阅的说法 | 建议 |
|---|---|---|
| [WebUI 手册 §1.2](../langfuse/web-ui-operation-manual.md#12-sessions复盘多轮会话) | 按各轮 Trace 阅读容易被理解为“一轮一定对应一条 Trace” | 补充评测父 Trace 情况，按 `workflow_http` 的 `turn` 读轮次；还要说明 Session 聚合不证明上下文已传给模型 |
| [WebUI 手册 §1.3](../langfuse/web-ui-operation-manual.md#13-users按终端用户查看使用情况) | User ID 为空即推断应用未稳定上报，对节点调试等入口不够准确 | 区分主接口、节点接口和评测包装层；结合实际入口检查，而非一律判断埋点失败 |
| [WebUI 手册 §1.1.1](../langfuse/web-ui-operation-manual.md#111-列表区域怎么看) | My Views 已有概述，但未核对当前版本保存弹窗、时间范围是否恢复及视图共享范围 | 请在沙箱新建独立练习视图，改变筛选后恢复，重新打开再查时间、列与排序；不要覆盖团队已有视图 |
| 同手册 §1.2 / §1.3 图片 | 既有整页截图带用户标识和登录信息，不能未经处理复制到新手册或 Notion | 用明确的沙箱样本补拍，检查客户名、证券、金额、群名、用户及订单标识、邮箱和地址栏后再插入 |

### 发布前仍需验证

1. 由负责人指定已有的两轮以上沙箱测试会话、User ID 和实际 Tag，按 A2 第 4 节逐项验收。
2. 补充 Session 两轮详情、User 关联与保存视图恢复的测试数据截图，填写 UI 验证人及实际日期。
3. 如采用可选 CLI 步骤，在同一沙箱执行只读查询，对齐时间和过滤条件后比较 Observation ID；不执行则注明不适用。
4. 资料差异交 @HXl 审阅；本次不重写原 WebUI 手册、ADR、数据集契约或业务代码。

## A3 补充审阅记录（2026-09-29）

本节对应 [A3 · Dashboard 与指标分析](../langfuse/developer-manuals/a3-dashboard-and-metrics.md)。记录人 Codex，审阅人 @HXl；保留 A1、A2 记录与既有功能手册。A3 为草稿，未发布 Notion，未连接正式项目修改配置或数据，未升级 SDK 或部署。

### 核对结果

| 项目 | 依据与结论 |
|---|---|
| 版本 | 本次读取 Python 包元数据为 4.15.0；自托管 4.46.0 沿用本报告 A1 的同日健康检查记录，本次未重新连接部署 |
| 操作依据 | 核对官方 Custom Dashboards、Metrics、v4 Dashboard changes、Chart any table、Token & Cost Tracking、Metrics API、Alerts；官方功能说明不等于本项目 4.46.0 的逐项 UI 验收 |
| 模型与请求范围 | [ADR 0031](../adr/0031-single-model-request-per-message.md) 允许零次模型请求；[harness/langfuse_client.py](../../harness/langfuse_client.py) 的 `regression_case` 可以包含多个 `workflow_http`。手册不把模型调用数、步骤数、Trace 数当成 HTTP 请求数 |
| 错误统计 | 练习分别统计同范围 Generation 总数与 ERROR 数，分母为零记无样本；不把这一比率当成 HTTP 5xx、cascade 率或确定性评测失败率 |
| 告警实现 | [alerts.py](../../app/observability/alerts.py) 的 `_evaluate_metric` 用相邻快照增量计算比率，P95 使用累计直方图结果；Grafana 部分查询使用滚动窗口。只核对代码，未验证运行中的告警调度或通知 |
| 截图 | 新增 `44-a3-dashboard-official.png`，来源为 [Langfuse 官方 Metrics 文档](https://langfuse.com/docs/metrics/overview)的 [Demo 图片](https://langfuse.com/images/docs/llm-analytics.png)。目视确认是 `Langfuse Demo / langfuse-docs`，没有项目客户原文或内网地址；正文标明旧版标题、示例数据和非项目实测。复用已目视检查的 `39-tracing-filters.png` 控件图 |
| 图片取舍 | 官方另一张成本图含用户标识，未用于交付；只保留明确标有 Demo 的总览图。未新增客户截图，也未将生产记录上传外部平台 |
| 命令 | 已执行 SDK 版本查询，核对 `metrics_snapshot.py --help` 和 `--url` 实现；手册用 `OTC_AGENT_METRICS_URL` 传入完整沙箱指标地址，并在变量缺失时停止。未执行联网快照或 `run_alerts.py` |
| 文档检查 | A3 七节结构、五项页面属性、36 个本地链接及图片、所引用本地标题锚点、两段 PowerShell 语法检查通过；ADR 引用、生成文档同步与 `git diff --check` 通过。全仓文档布局检查仍报已有临时目录的 307 项失效引用（`.pytest-tmp` 64、`.tmp` 242、`tmp` 1），`docs/` 内零发现；未清理这些目录 |

### 资料差异与交审事项

| 位置 | 发现的问题 | 审阅依据与建议 |
|---|---|---|
| [Grafana JSON](../../infra/grafana/dashboards/otc-agent-overview.json) 的“节点 P95 延迟”；[Grafana README](../../infra/grafana/README.md) 的节点直方图说明 | 仍使用 `otc_agent_intent_latency_ms_bucket` 配合非空 node 标签统计节点延迟 | 当前 [metrics.py](../../app/observability/metrics.py) 的 `emit_node_completed` 写 `otc_agent_node_latency_ms`，端到端指标单独写入。请维护人核对部署查询并更新真源；本次不修改模板或另发一份查询替代它 |
| [Grafana README](../../infra/grafana/README.md) 的“维护建议” | “阈值红黄与 alerts 同步”容易被理解为整张看板都采用故障升级阈值 | 看板同时含 ADR 0030 上线观察面板，README 前文已有不同用途说明；建议明确区分退出门参考线、趋势窗口与 ADR 0019 故障定级 |
| [WebUI 手册 §1.4](../langfuse/web-ui-operation-manual.md#14-alerts创建成本延迟和质量告警) | 介绍平台原生 Alerts，但没有在该节说明本项目现有 `run_alerts.py` 与它的分工 | 原生 Alerts 是平台能力，不能据此认定项目已接通该通知链。请补充项目适用边界，避免重复配置告警 |
| [ADR 0019](../adr/0019-incident-severity-thresholds.md) 的短期监控描述与 [alerts.py](../../app/observability/alerts.py) 的采样实现 | 规则所说的持续越线时间，不能直接理解为所有指标都来自同长度滚动窗口 | 比率按轮询间隔取增量；P95 的累计直方图局限已在代码注释说明。请审阅是否需要在运维真源解释该差异；本次不调整阈值或实现 |
| 官方总览图片及官方不同页面 | 总览图片仍有旧版 `Traces by time`，当前 Custom Dashboards 与 v4 FAQ 对 Home 的介绍也有更新时差 | A3 只用图片帮助认图，不照图保证 v4 控件；新建练习卡片使用 Observations，部署入口仍需沙箱实机验收 |

### 发布前仍需验证

1. 在负责人确认的沙箱，用同一批已有测试记录依次创建调用量、延迟、token、成本、ERROR 数卡片，保存并重新打开；核对当前版本按钮、单位和筛选继承。
2. 补拍沙箱面板、卡片配置和慢调用定位截图；发布前检查业务字段、用户标识、邮箱、凭据和地址栏。官方 Demo 图不充当项目验收证据。
3. 按相同时间和范围核对错误计数；缺少错误样本或价格信息时明确记待验证，不为填满图表重跑交易或补造价格。
4. 由运维核对已有 Grafana 的数据源、节点 P95 查询与基线来源，区分上线观察线和故障阈值；本次不覆盖已部署面板。
5. 如需快照，在指定沙箱执行只读命令；不执行则记不适用。实际操作人填写验证日期和姓名后，交 @HXl 审阅发布。

### A3 本轮截图核对与操作范围调整

用户随后要求只查看已有 Dashboard，并提供三张实际页面截图。本轮按截图更新 A3；上方初稿关于新建卡片、保存面板及快照命令的验收安排不再用于当前手册。当前验收以 [A3 第 4 节](../langfuse/developer-manuals/a3-dashboard-and-metrics.md#4-验证做完后应该看到什么)为准。

| 核对项 | 截图证据与本轮处理 |
|---|---|
| 版本和入口 | 截图显示 `v4.46.0`、`Dashboards` 与 `Langfuse Home (Langfuse Maintained)`；据此替换泛化卡片名称与入口描述，没有登录页面或验证点击后的交互 |
| 筛选 | 时间选择器为 `Past 7 days`，Env 为 `4 selected`；Model Usage、Model latencies 各有模型选择框并显示 `+9`。手册要求分别核对环境与模型，截图未展示的弹窗选项不写成已确认 |
| 延迟 | 截图保留三张延迟分位数表；Model latencies 当前选中 `50th Percentile`，另有 75/90/95/99 标签。手册明确查看 P95 时选择 `95th Percentile`，不沿用“此部署可能没有 Trace 延迟表”的泛化说明 |
| 需要维护人核对：Generation 表 | Generation latency percentiles 有 `regression_case` 等名称，Observation latency percentiles 出现同名 `CHAIN` 记录。截图不足以确认前者的实际查询范围；请维护人核对卡片查询与记录 Type，未将其认定为纯模型耗时，也未认定为平台缺陷 |
| 需要维护人核对：数量 | Traces 与 User consumption 的 Total traces 数字不同；截图不足以解释差异，请按同一时间、环境与卡片筛选核对，不直接拿来作模型错误占比分母 |
| 费用 | Model costs 已有 token 数量，费用为零；Model Usage 的 Cost by model 显示 No data。手册增加切到 Usage by model、检查单条费用字段和模型匹配的路径，没有据此断言免费、无调用或价格配置错误 |
| 评分 | 核对顶部 Scores 的 Name / # / Avg / 0 / 1、Show all，中部 Moving average per score，以及底部 Scores Analytics / Select scores。评分名称、来源、类型分开阅读，业务规则仍链接仓库与 ADR |
| 图片与数据 | 所附原图含用户标识与登录账号信息，本轮只据图核对界面，不将未脱敏整图入库或复制这些标识。既有官方 Demo 图移到参考节作为补充，不能充当实际页面截图 |
| 尚未验证 | 时间与环境选择后的刷新、卡片模型筛选、评分选择后的图表、Generation 表的实际数据范围、同范围错误总数和 Grafana 查询；发布前仍需在指定沙箱核对并填写实际验证人 |

### A3 Scores 页面补充核对

本轮用户提供的 Scores 页面显示 `v4.47.0`。A3 步骤 7 已改为 `Evaluation → Scores → Scores → Table` 的单条评分查看流程，并同步调整验证清单；此前 Dashboard 汇总卡片的 `Avg`、`Show all`、`Select scores` 不再作为该步骤的操作入口。

已核对 `Scores / Analytics`、`Table / Chart`、搜索框的 `name:` / `source:` 语法、`Count` 图、`Columns` 及 Timestamp / Name / Value / Comment / Trace / Observation / Session 字段。保留评分来源和验收口径的仓库链接；从 Comment 中提示评分可能按已保存结果补写，不把评分时间当成新业务执行时间。未复制业务标识、登录信息或关联 ID。

版本属性分别注明既有部署核对记录、Dashboard 界面版本与 Scores 界面版本；本轮未查询部署版本或执行升级。筛选结果、Chart / Analytics 展开内容和关联链接跳转仍待实机核对。

### A3 告警规则与 Grafana 使用范围补充核对

同日只读检查本机 Docker 容器（含已停止容器）、进程和仓库 Compose 服务定义，未发现 Grafana 或 Prometheus 服务；`infra/grafana/` 提供面板 JSON 模板和导入说明，不能据此认定已有可访问的部署。远程是否部署尚未核实。上方关于打开已有 Grafana 及核对其查询的安排不再作为当前 A3 的必做步骤。

A3 步骤 8 改为“查看告警阈值与处理规则”，链接可观测性文档、ADR 0019 和值班手册；同步调整前置条件、验证清单、记录表、常见问题及目录索引。阈值数值仍由仓库真源维护，未在手册中另建规则表。

已核对 `alerts.py::THRESHOLDS` 和 `scripts/run_alerts.py`：脚本直接读取应用 `/metrics`，不依赖 Grafana 或 Prometheus 服务；未配置 `WECHAT_ALERT_WEBHOOK_URL` 时仅记录日志。告警调度、状态持久化和通知送达均未作运行验证，本轮未执行告警脚本、推送通知或更改配置。

交 @HXl 审阅：[值班手册 §4、§5.1–5.2](../operations/on-call-runbook.md#4-监控告警来源)仍有从 Langfuse 仪表盘读取 HTTP 5xx 或 fallback 比率的表述，容易与 Langfuse Observation ERROR 占比混淆；请结合[应用指标定义](../operations/observability.md#2-指标)和当前告警实现核对来源。本次只记录差异，不改值班手册或另定处置规则。

## A4 补充审阅记录（2026-09-29）

本节对应 [A4 · Dataset 管理（界面）](../langfuse/developer-manuals/a4-dataset-management.md)。记录人 Codex，审阅人 @HXl；A4 为草稿。新增任务手册与目录入口，保留既有功能指南、自动同步说明和 ADR，未发布 Notion，未访问或修改平台数据。

### 核对结果

| 项目 | 依据与结论 |
|---|---|
| 版本 | 本次查询 Python 包元数据为 4.15.0；自托管 4.46.0 引用本报告 A1 的同日健康检查记录，本次未连接部署；不将 A3 的 Scores 页面版本当作 Dataset 实测版本 |
| 单向发布 | 核对 ADR 0029 D5、`upload_golden_to_langfuse.py` 的 `prepare_sync_files` / `sync_prepared_files` 及 `langfuse-dataset-sync.yml`。biz / intent 以已审阅 Git 文件为基线，自动同步检出 main；节点样本流程单独引用 ADR，不扩展成“平台所有数据集都禁止编辑” |
| 本地命令 | 已运行 `.venv` 中的 Python 执行 `upload_golden_to_langfuse.py --sync-all --dry-run`，退出码 0；本次快照为 10 个文件、782 条用例。未初始化 Langfuse 客户端、未上传、未归档，也未运行评测；数量只记作本次证据，不作为手册固定验收值 |
| 来源追溯 | `fixture_path` 相对于 `tests/datasets/`，`source_line` 为源文件行号；A4 提醒按原始编号复核，避免文件变动后错用旧行号 |
| 截图 | 复用仅含导航的 `00-evaluation-nav.png`；新增 `45-a4-datasets-official.png`，来源为官方 [Datasets](https://langfuse.com/docs/evaluation/experiments/datasets) 的[公开示例图片](https://langfuse.com/images/docs/datasets-overview.png)。已目视核对其为 docs-examples 的国家与首都测试数据，无客户名、证券、金额、群名、凭据或内网地址 |
| 图片与版本范围 | 官方示例使用旧版 Runs 名称，只用于辨认列表列名。仓库 `27-dataset-item-detail.png` 显示 v4.38.0，含证券与登录信息，未复制到 A4 或外部平台；仅据它核对 Search、Filters、Columns、Items 等可见入口 |
| 官方资料 | 查阅 Datasets、Experiments Data Model、Access Control；Filter search bar 官方正文面向 Observations / Traces，不能据此宣称 Dataset 支持全部同名语法。A4 提醒依本页提示查询，保留浏览与翻页核对路径 |
| 文档布局 | 本次全仓布局检查仍有既有临时目录的 307 项失效引用（`.pytest-tmp` 64、`.tmp` 242、`tmp` 1）；`docs/` 内零发现。未修改检查器或清理用户临时目录 |
| 专项检查 | A4 七节结构、禁用措辞检查、21 个本地链接及标题锚点、PowerShell 命令语法通过；ADR 引用、生成文档同步和 `git diff --check` 通过。检查脚本使用 Python `-X utf8` 避免 Windows 控制台编码影响输出 |

### 资料差异与交审事项

| 原资料位置 | 发现的问题 | 审阅建议 |
|---|---|---|
| [workflow-guide.md §3.1](../langfuse/workflow-guide.md#31-metadata-字段) | `overview` 仍描述为给本地 Judge 使用的题目 | 按 ADR 0005 和当前评测入口复核用途；A4 只把 Metadata 用作查看说明与追溯，不复制 Judge 说法 |
| [workflow-guide.md §4.1](../langfuse/workflow-guide.md#41-上传-dataset) | Windows CMD 单文件上传示例仍引用已退役的 `tests/fixtures/biz` 路径 | 对照现役 `tests/datasets/biz` 与脚本入口更新真源；A4 仅提供已实际执行的批量 dry-run 命令 |
| [WebUI 手册 §3.3](../langfuse/web-ui-operation-manual.md#33-维护测试集和测试用例) | 通用教程直接引导新增、编辑、归档、删除及从 Trace 加入 Dataset，缺少本项目 biz / intent 基线的适用边界 | 建议审阅时补充 ADR 0029 D5 的 Git 单向发布约束，区分通用平台能力、候选标注与正式基线 |
| 同手册 §3.3.3 的图片说明 | 文件名和图注写“详情”，实际展示 Items 列表，且版本为 v4.38.0 | 建议更正图注，并用脱敏沙箱数据补拍实际详情与筛选控件；不要将旧图当成当前版本的完整操作验证 |

### 发布前仍需验证

1. 由 @HXl 指定沙箱 Dataset、完整 Item ID 和一条可核对的已发布修改记录，确认所有展示数据可用于手册。
2. 实机核对当前版本的 Status、Search、Metadata 筛选和版本选择入口，完成查找、清除条件、翻页及 Item 查看；尤其确认含 `/`、`:` 的完整 ID 搜索是否命中。
3. 用已脱敏的沙箱数据补充筛选及单条用例详情截图；核对 Git 来源与发布结果，不为验证而触发正式项目同步或交易执行。
4. 根据 A4 第 4 节填写结果，实际验证人更新页面属性；未完成项继续记待验证，不把本地预览成功写成远端发布或实验通过。

## A5 补充审阅记录（2026-09-29）

对应 [A5 · Experiment 结果对比](../langfuse/developer-manuals/a5-experiment-comparison.md)。记录人 Codex，审阅人 @HXl；状态为草稿。本次新增任务手册、目录入口及官方测试截图，未改原功能指南、契约或 ADR，未发布 Notion，未连接项目查询数据或执行评测。

### 核对结果

| 项目 | 依据与结论 |
|---|---|
| 版本 | Python 包元数据为 4.15.0；自托管 4.46.0 引用本报告 A1 的同日只读记录。本次未连接部署，不将其他页面版本或官方图片作为 Experiment 实机版本证明 |
| 操作流程 | 查阅官方 Compare experiments、Experiments Data Model、RBAC，并核对仓库既有对比页的 Compare、Baseline、Columns、Boolean Scores、Numeric Scores 和详情 Scores 入口；筛选条件及点击结果仍待指定沙箱验证 |
| 当前评分链路 | `langfuse_eval.py::_run_items()` 提交运行结果，JS Evaluation Rule 异步评分；`run_local()` 同样调用该函数。`local_eval.py` 另经 `record_business_score()` 将业务评分关联到用例 Trace，两种入口不可混称 |
| 分数与报告 | 核对 `harness/evaluators/*.js`、评分定义、`http_evaluation.py` 和 `evaluation.py`；A5 说明单项分数、执行报告状态与完整业务验收的区别，并要求核对 Comment、字段差异和断言覆盖 |
| 命令 | 已执行 `.venv` Python 的 `-m scripts.langfuse.langfuse_eval --local tests/datasets/intent/option.jsonl --dry-run --limit 3`，退出码 0，返回三个用例编号及轮数；该分支只读取本地文件，不初始化 Langfuse 客户端或调用模型、后端 |
| 图片 | 新增 46–48 三张官方 Compare experiments 页面公开图片，均已目视检查：Langfuse 文档问答测试数据，无客户交易信息、凭据或内网地址。图片中的模型、评分、费用仅用于界面示意；旧 `30-experiment-results.png`、`32-experiment-item-detail.png` 含证券和登录信息，未复制到 A5 |
| 文档检查 | 文档布局检查的 307 项失效引用仍全部来自既有 `.pytest-tmp`、`.tmp`、`tmp` 目录；`docs/` 内零发现。ADR 引用、生成文档同步和 `git diff --check` 通过；未清理用户临时目录或改检查器 |

图片原始来源：[运行选择](https://langfuse.com/images/docs/experiment-comparison-selection.png)、[结果对比](https://langfuse.com/images/docs/experiment-comparison.png)、[用例详情](https://langfuse.com/images/docs/experiment-comparison-peek-view.png)。

### 资料差异与交审事项

| 原资料位置 | 问题与核对依据 | 交审建议 |
|---|---|---|
| [workflow-guide.md §5](../langfuse/workflow-guide.md#5-执行-experiment) | 同节同时写 Score 由 JS Rule 自动生成和 SDK 直接保存业务确定性 Scores；当前 `_run_items()` 没有传入业务评分器 | 请区分 SDK Experiment 的异步规则评分与 `local_eval.py` 的业务评分写入，不把文本 Score 当作完整业务验收 |
| 同文 §5.1、§5.2、§6 | `--local` 不创建 Experiment、Judge 和 ticker 子图等旧说明仍存在，沿用本报告 A1 的差异记录 | 按当前脚本及 ADR 0005、0025 统一修订真源；A5 仅链接并注明已交审 |
| 文本评分覆盖 | 三个文本 JS 评分器在没有适用断言时也可能返回 true，Metadata 中 `assertion_count` 为零 | 审阅时核对覆盖含义；A5 提醒不能将该分数当作有效覆盖或整批 PASS，本次未修改评分实现或配置 |
| 意图实验报告状态 | `http_evaluation.py` 在意图套件传入空的字段差异，正式意图比较由 JS Rule 完成；Output 中 `status` / `passed` 不能代替意图 Score | A5 引导读最终意图 Score 与 Comment，避免只看报告状态；不另立评分口径 |
| 本地命令启动方式 | 直接运行脚本路径在本机出现 `ModuleNotFoundError: app`；仓库根目录使用 `-m` 方式成功 | A5 使用已验证的模块命令；请维护人复核旧文档直接脚本路径示例的环境要求 |

### 发布前仍需验证

1. 由 @HXl 指定沙箱中的两次可比较运行、已审阅基线、数据与评分版本，并确认展示内容可用于手册。
2. 实机完成勾选、Compare、Baseline 选择、评分筛选与清除、翻页和 Trace / Scores 跳转；缺少控件时记录实际版本，不升级部署。
3. 核对至少一条失败或缺失项的 Comment、轮次和关联对象；无失败数据时如实记录，不为补截图重跑交易。
4. 按 A5 第 4 节填写结果，由实际验证人更新页面属性，再交 @HXl 审阅发布；官方图片与本地预览不充当实机或业务验收证据。

## A6 补充审阅记录（2026-09-29）

对应 [A6 · 人工标注与业务复核](../langfuse/developer-manuals/a6-human-annotation.md)。记录人 Codex，审阅人 @HXl；状态为草稿。本次新增任务手册、目录入口和两张官方测试截图；未改已有契约、业务代码、fixture 或平台配置，未发布 Notion。

### 核对结果

| 项目 | 依据与结论 |
|---|---|
| 版本 | 本机包元数据确认 Python SDK 4.15.0；自托管 4.46.0 沿用本报告 A1 的同日记录，本次未连接部署，不认定标注和导出页面已通过实机验证 |
| 人工评分 | 核对 `definitions/score-configs.json`、`annotation-queues.json`、`upload_score_configs.py`；现有评分为 `human_business_verdict`，队列为 `业务人工复核`。手册链接定义，不另维护分类与数值映射表 |
| 配置预览 | 已运行 `upload_score_configs.py --help`，退出码 0；`--dry-run` 会读取 `.env` 并访问远端，未执行该联网预览或 `--apply` |
| 本地检查 | 已执行 `check_fixture_consistency.py --verbose`，退出码 0，本次为 10 文件、782 用例；仅证明现有数据文件一致性，不代表新增样本或业务验收通过 |
| 标注回流 | 按 ADR 0005 D2 与 ADR 0029 D5 编写业务复核、导出、Git fixture 审阅及单向发布流程；核对 `tests/datasets/README.md`，不恢复退役节点目录，不声称存在人工 Score 到 fixture 的自动导入 |
| 官方资料 | 查阅 Annotation Queues、Scores via UI、Scores Data Model、Export from UI 与 RBAC；明确队列分配不授予访问权、Viewer 不能标注、导出沿用筛选但包含隐藏列 |
| 图片 | 新增 `49-a6-add-to-queue-official.png` 与 `50-a6-score-comment-official.png`，目视核对为官方文档问答与通用评分测试；无客户交易信息、真实凭据或内网地址。既有 `36-annotate-panel.png` 含证券与登录信息，仅用于核对控件，未在 A6 复用 |
| 文档检查 | A6 七节模板、禁用措辞、敏感值模式、26 个本地链接及锚点和三个 PowerShell 命令块语法检查通过；ADR 引用、生成文档同步与 `git diff --check` 通过。首次布局检查有既有临时目录的 307 项失效引用；最终检查时工作区另有 A1–A5 移入 `developer-manuals/` 的目录调整，产生 114 项 `docs/` 链接问题。已适配 A6 的三处跨手册引用，A6 无布局发现；其他目录调整的链接由该项工作继续处理，未覆盖或撤销这些改动 |

图片来源：[加入队列](https://langfuse.com/images/docs/add_to_queue.png)、[评分评论](https://langfuse.com/images/docs/scores_comment.png)。

### 资料差异与交审事项

| 原资料位置 | 问题与核对依据 | 交审建议 |
|---|---|---|
| [WebUI 手册 §3.9.2](../langfuse/web-ui-operation-manual.md#392-使用-human-annotation-queue-批量复核) | 正文写完成快捷键为 `Ctrl+E`；既有图片显示 `Ctrl` 加回车符号，当前官方文档也列 `Ctrl/Cmd + Enter` | 请按部署实机核对后改真源；A6 使用按钮名称，不复制该快捷键 |
| 同节关于 `New queue` 不可用的处理 | 原文直接建议升级套餐或更换实例；权限、实际部署能力和套餐提示需要分开核对 | A6 请管理员核对原因，不安排升级；本次未改原文或部署 |
| [功能指南 §4.3](../langfuse/workflow-guide.md#43-配置人工评分口径)、[脚本说明](../../scripts/langfuse/README.md#upload_evaluatorspy--upload_score_configspy) | 预览示例未强调 `--dry-run` 仍访问平台；`_public_api.py::load_dotenv` 会让仓库 `.env` 覆盖进程同名变量 | 请补充预览的连接范围与项目切换注意事项；A6 已按现有代码说明执行前置条件，未修改环境加载实现 |
| Score Config 的修改能力 | 官方数据模型与 WebUI 手册称配置不可变；仓库脚本对同类型配置调用 update，类型变更则归档并新建 | 由维护人对照部署 API 核对哪些字段允许修改；A6 只解释计划 Action，不保证拟修改一定成功，也未更改同步实现 |
| 导出与合入 | 现有材料未提供可直接把人工 Score 自动转换为 biz / intent fixture 的入口；Scores 文件本身不足以重建完整用例 | 保持人工复核与工程整理，按关联 ID 补齐上下文、预期和来源；若今后实现导入工具，契约应先在仓库审阅 |

### 发布前仍需验证

1. 由 @HXl 指定沙箱、队列、样本和有标注及导出权限的验证人；核对实际部署版本，不修改正式项目权限。
2. 实机完成单条入队、分类与评论保存、重新打开、修正建议和队列完成；确认本版本的控件名称及保存提示。
3. 在 Scores 限定人工来源与本批对象，实际导出一份测试文件，核对关联 ID、评论、分类标签、完整列和覆盖数量；补拍脱敏导出截图。
4. 用一条业务方确认的合成样本核对交接材料与对应 fixture 修改，区分“标注完成”“待审阅”“已合入”“已发布”和“回归结果”；本次未执行合入、发布或评测。
5. 完成 A6 第 4 节后由实际验证人更新页面属性，再交 @HXl 决定是否发布。
