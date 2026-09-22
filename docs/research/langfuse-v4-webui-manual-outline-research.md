# Langfuse v4 WebUI 非开发人员操作手册：大纲研究笔记

> 调研日期：2026-09-21  
> 范围：仅核对 Langfuse 官方文档、官网与官方 GitHub 仓库；本文是手册大纲的证据底稿，不是完整操作手册。

## 1. 当前 WebUI 导航基线

官方仓库当前 `main` 分支的项目侧栏路由依次包含：`Home`、`Dashboards`；`Observability` 组下的 `Tracing`、`Sessions`、`Users`、`Alerts`；`Prompt Management` 组下的 `Prompts`、`Playground`；`Evaluation` 组下的 `Scores`、`Evaluators`、`Human Annotation`、`Datasets`、`Experiments`；底部还有 `Settings`。组织上下文另有 `Projects` 与组织级 `Settings`。[官方路由源码](https://github.com/langfuse/langfuse/blob/main/web/src/components/layouts/routes.tsx)

需要在手册开头明确三点：

- v4 的核心列表入口当前显示为 **Tracing**，其数据主体是统一的 **Observations table**。一次 trace 是共享同一 `trace_id` 的 observations 集合，而不是必须把每一行理解为一个完整会话。[v4 observations table FAQ](https://langfuse.com/faq/all/explore-observations-in-v4)｜[Observability data model](https://langfuse.com/docs/observability/data-model)
- 菜单会因 v4 开关、部署写入模式、功能模块定制、RBAC 权限和套餐而隐藏或改名。例如 `Experiments` 受 `experimentsV4Enabled` 控制，`Alerts` 只在非 legacy v4 写入模式显示，`Evaluators` 仍保留 legacy 路径。[官方路由源码](https://github.com/langfuse/langfuse/blob/main/web/src/components/layouts/routes.tsx)
- 因此正式手册宜采用“英文菜单名 + 中文解释”，并提示读者：若看不到入口，先确认项目、角色、v4 状态和部署版本，不要直接判断为系统故障。

## 2. 建议写入手册的主要用户工作流

### 2.0 Evaluation 优先交付：纯 WebUI 操作链路

以下内容应作为第一版手册主体。正式手册不出现 SDK、API、命令行或代码操作；只有“找管理员配置连接/权限”这类必要前置说明。

#### A. 创建、编辑 Dataset 和测试项

创建 Dataset：

1. 左侧进入 `Datasets`。
2. 点击 `+ New dataset`。
3. 填写项目内唯一的名称，以及可选 description、metadata/schema；名称含 `/` 时，UI 会自动按虚拟文件夹展示。
4. 保存后进入 Dataset 详情的 `Items` 页签。

维护测试项：

1. 在 `Items` 页签用 `Add item` 新增单条，填写 `Input`、可选 `Expected output` 和 metadata；也可用 `Import CSV` 批量导入。
2. 点击 item ID 打开并编辑。
3. 点击 item 行旁的 `…`，选择 `Archive` 或 `Delete`；Archive 后不再进入后续 experiment。
4. 每次 add、update、archive、delete 都会形成新的 dataset version；在 `Items` 页签切换 Version view 查看历史状态。
5. 若从生产数据沉淀用例，可在 observation 详情点 `+ Add to dataset`；批量方式是 `Tracing`/Observations table 勾选记录 → `Actions` → `Add to dataset` → 选择新建或已有 dataset → 配置字段映射 → 预览并确认。

官方按钮及路径依据：[Datasets 官方文档](https://langfuse.com/docs/evaluation/experiments/datasets)。需在目标部署截图确认 Dataset 创建弹窗中 description、metadata、schema 的实际折叠位置；官方文档明确了这些字段能力，但没有逐项给出当前弹窗顺序。

#### B. 创建、测试、编辑 Evaluator 与 Evaluation Rule

先向非开发读者解释：Evaluator 决定“如何评分”，Rule 决定“对哪些新 observations 自动评分”。一个 evaluator 可被多个 rules 复用。[Evaluation concepts](https://langfuse.com/docs/evaluation/core-concepts)

创建 LLM-as-a-Judge evaluator：

1. 左侧 `Evaluators` → `New evaluator`。
2. 从模板库选择 `LLM-as-a-Judge`，可从空白开始，也可复制官方模板后修改；使用前项目必须已有 LLM connection。
3. 选择模型，编辑 judge prompt；动态字段写为 `{{variable}}`。
4. 选择 Score 类型：Numeric、Categorical 或 Boolean；Categorical 需定义可选值。
5. 将 prompt variables 映射到 observation 的 Input、Output、Metadata、Tool calls；用于 prompt experiment 时，还要按需要映射 Expected Output 和 Experiment Item Metadata。
6. 在右侧过滤并选择有代表性的 sample observation，运行测试；检查 score 和 reasoning，必要时继续调整。
7. 保存 evaluator。定义被修改时应视为新 evaluator version；运行中的 rules 会使用该 evaluator 的最新版本。官方稳定资源模型明确 evaluator 支持版本历史。[LLM-as-a-Judge 官方文档](https://langfuse.com/docs/evaluation/evaluation-methods/llm-as-a-judge)｜[Evaluator API 发布说明（用于确认版本语义）](https://langfuse.com/changelog/2026-08-27-stable-evaluator-api)

创建/调整 rule：

1. 保存 evaluator 后，选择从刚才的 sample filters 创建新 rule，或把 evaluator attach 到已有 rule。
2. 配置 filters、sampling rate 和一个或多个 evaluators；检查过去 7 天预计匹配量。LLM-as-a-Judge 还要核对 estimated cost，必要时降低 sampling rate。
3. 如需补评近期历史数据，启用 `Also run on past observations`，选择时间范围；一次性抽样复核则应在 Tracing 列表使用 batch evaluation。
4. 保存/启用后，rule 只对匹配的新 observations 持续打分；从 observation 的 score 打开可查看值与 judge reasoning。

依据：[Evaluate Production Traffic](https://langfuse.com/docs/evaluation/get-started/online)｜[Evaluation concepts](https://langfuse.com/docs/evaluation/core-concepts)。官方公开文档没有稳定列出“打开既有 evaluator/rule 后的编辑按钮”当前文案；手册截图阶段应实测它是 `Edit`、行菜单还是版本操作，不应现在臆写。可确认的产品语义是：更新 evaluator 定义产生新版本，rule 使用最新版本；rule 可更新 filters、sampling、status 和 evaluator assignments。[官方发布说明](https://langfuse.com/changelog/2026-08-27-stable-evaluator-api)

#### C. 从 UI 运行 Prompt Experiment

前置条件：Dataset item 的 Input 必须是 JSON object，并包含所选 prompt 的变量键；项目中已有可用 prompt 和 LLM connection。Evaluator 可选。[Experiments via UI](https://langfuse.com/docs/evaluation/experiments/experiments-via-ui)

1. `Datasets` → 打开目标 Dataset。
2. 点击 `Start Experiment`。
3. 在 setup 页面选择 prompt experiment，并点其下方 `Create`。
4. 填 Experiment name，选择 prompt、LLM connection、dataset/dataset version。
5. 可选开启 structured output 并选择或新建 schema；可选选择 evaluator。
6. 点击 `Create` 触发运行；系统跳转到 `Experiments`，等待状态完成。

官方文档同时出现另一条入口文案：`Experiments` → `Run Experiment` → Dataset Selection → `Dataset Version`。这可能是新版独立 Experiments 入口与 dataset 详情入口并存，正式手册须在目标 v4 小版本实测后选定主路径，另一条写成“可选入口”。[Datasets：versioned experiments](https://langfuse.com/docs/evaluation/experiments/datasets)｜[Experiments via UI](https://langfuse.com/docs/evaluation/experiments/experiments-via-ui)

#### D. 人工评分与 Annotation Queue

单条人工评分：

1. 先由有权限人员准备 Score Config。
2. 打开 trace、observation 或 session 详情，点击 `Annotate`。
3. 选择 score dimension，填写值和可选 comment。
4. 在详情的 `Scores` 页签核对已保存结果。Experiment compare view 也可直接 annotate，汇总指标会随人工分数更新。[Scores via UI](https://langfuse.com/docs/evaluation/evaluation-methods/scores-via-ui)

批量协作复核：

1. 左侧 `Human Annotation` → `New Queue`。
2. 选择 Score Configs，填写 `Queue name`、可选 Description，可选指派用户。
3. 在 Tracing/Sessions 表格勾选记录 → `Actions` → `Add to queue`；单条详情则用 `Annotate` 下拉选择队列。
4. 审核人进入队列，在 `Annotate` card 填 scores/comments/corrected output，点击 `Complete + next`。
5. Queue 的 corrected output 不会自动写回 Dataset，也不会自动批准 release；负责人仍需确认、更新 Dataset 并重跑实验。

依据：[Annotation Queues 官方文档](https://langfuse.com/docs/evaluation/evaluation-methods/annotation-queues)。

#### E. 查看、比较结果并下钻失败用例

推荐把以下路径做成手册中的主流程图：

```text
Experiments 汇总
→ 选择 baseline 与 candidate，点 Compare
→ 用 score 阈值/错误筛出退化项
→ 打开 Experiment Item
→ 对照 Input / Expected Output / 实际 Output / Scores 与 reasoning
→ 打开关联 Trace
→ 在 trace tree 中逐个查看 observations
→ 定位 retrieval、LLM generation、tool 或应用步骤
→ 记录人工 score/comment，必要时加入 Annotation Queue 或 Dataset
```

具体操作原则：

1. 在 `Experiments` 勾选待比较 runs，进入 comparison view，并把已审核的发布版本设为 baseline。
2. 发布判断必须使用相同 dataset version 和 evaluator definitions；平均分相同也可能有关键用例由 pass 退化为 fail。
3. 对退化项先并排检查 Input、Expected Output、baseline/candidate Output、score explanation、cost、latency。
4. 打开 failing item 的 trace；在相邻 trace 详情/trace tree 中继续展开 intermediate retrievals、model calls、tools/其他 observations，判断是应用错误还是 evaluator 误判。
5. 用人工 score/comment 记录复核结论；多人复核则把相关 experiment item observations 加入 Annotation Queue。
6. 修改 evaluator 后，应使用同一新版定义重新评分 baseline 与 candidate，不能只重评候选版本。

依据：[Compare experiments](https://langfuse.com/docs/evaluation/experiments/compare-experiments)｜[Experiments data model](https://langfuse.com/docs/evaluation/experiments/data-model)。官方数据模型明确每个 Experiment Item 关联 trace ID，trace 内再由 observations 构成；因此“Experiment Item → Trace → Observations”是 v4 的正确排错层级。[Observability data model](https://langfuse.com/docs/observability/data-model)

#### F. Evaluation 手册必须写入的边界提示

- UI Prompt Experiment 主要测试 prompt/version、model 和结构化输出；若要评测整套自定义应用/Agent 逻辑，官方指向 SDK experiment，不应让非开发人员误以为 WebUI 能运行任意业务代码。[Experiments via UI](https://langfuse.com/docs/evaluation/experiments/experiments-via-ui)
- v4 应使用 observation-level evaluators；旧 trace-level evaluator 属迁移期遗留。Cloud 在 2026-11-16 cutover 后停止旧 evaluator 产出，自托管进入 `events_only` 后也不再产出。[LLM-as-a-Judge 官方文档](https://langfuse.com/docs/evaluation/evaluation-methods/llm-as-a-judge)
- 自动 evaluator 分数可能异步出现；“实验已完成但暂时没分”不等同于用例通过。
- 删除 evaluator 时，如仍被运行中的 evaluator/rule 引用，UI 会阻止删除并显示依赖；应先解除关联。[官方删除保护说明](https://langfuse.com/changelog/2026-06-15-delete-evaluator-templates)
- Self-hosted code evaluator 只有管理员配置 dispatcher 后才可运行；非开发手册只写“联系管理员”，不写部署步骤。[Code evaluators](https://langfuse.com/docs/evaluation/evaluation-methods/code-evaluators)

### 2.1 首次进入与项目切换

建议说明登录后先在顶部切换 `Organization` 和 `Project`，再确认当前项目。Langfuse 权限模型为用户 → 组织 → 项目 → 角色；API Key 归属项目而非个人。默认角色包括 Owner、Admin、Member、Viewer、None。Viewer 主要是只读，Member 可查看指标并创建 scores，但不能配置项目。[RBAC 官方文档](https://langfuse.com/docs/administration/rbac)

### 2.2 Tracing：查找并定位一次异常调用

建议作为全手册最重要的操作章：

1. 进入 `Tracing`，先确认时间范围和 environment。
2. v4 默认优先展示 root observations；必要时移除 `Is Root Observation = true` 才能查看全部内部步骤。
3. 用过滤器或搜索栏按 observation name/type/model、trace ID、user ID、session ID、level、tags 等缩小范围，并保存常用视图。
4. 点击记录进入详情，查看 trace tree；依次核对 Input、Output、错误、耗时、模型、token/cost、metadata、scores。
5. 对多步骤 Agent 可切换/查看 agent graph；对延迟问题结合时间线判断耗时步骤。

官方建议的典型过滤法包括：`type = generation` 查 LLM 调用、`level = ERROR` 查错误、按 `total_cost` 降序查高成本调用、按 `trace_id` 查一次完整链路。[v4 observations table FAQ](https://langfuse.com/faq/all/explore-observations-in-v4) 一条良好 trace 在 UI 中可表现为 trace tree 和 agent graph。[Trace best practices](https://langfuse.com/docs/observability/best-practices)｜[Agent graphs](https://langfuse.com/docs/observability/features/agent-graphs)

### 2.3 Sessions：复盘多轮会话

进入 `Sessions`，搜索或筛选会话后打开详情，按时间顺序回放多条 traces。Session 适用于“一次会话跨多次请求”的场景；详情页支持回放、书签、公开分享和人工评分。应提醒业务人员：看不到 session 通常是应用没有上报 `sessionId`，不是 WebUI 手工创建失败。[Sessions 官方文档](https://langfuse.com/docs/observability/features/sessions)

### 2.4 Users：按终端用户聚合排查

`Users` 列表可按用户查看 token 使用量、trace 数量和用户反馈；单用户详情可查看聚合指标、该用户的 traces 与 feedback。这里的 Users 是业务应用的终端用户标识，不等同于可登录 Langfuse 的团队成员；后者在组织/项目权限设置中管理。[User Tracking 官方文档](https://langfuse.com/docs/observability/features/users)｜[RBAC 官方文档](https://langfuse.com/docs/administration/rbac)

### 2.5 Prompts / Playground：修改、测试与发布提示词

建议面向业务人员写成受控流程：

1. 在 `Prompts` 打开既有 prompt，核对名称、类型（text/chat）、当前版本和 labels。
2. 编辑内容或 config 并保存；同名保存会产生新版本，不覆盖历史版本。
3. 在 `Playground` 测试变量、模型与参数。
4. 用 dataset prompt experiment 做批量对比；确认后再移动 `production`/`staging` 等 label。
5. 在 prompt 的使用记录或关联 trace 中验证新版本是否生效；需要回滚时把生产 label 移回已验证版本。

官方定位是让非开发人员直接在 UI 更新 prompt；版本不可变，label 是应用获取某个发布版本的指针。Prompt 类型创建后不可更改；官方建议用 `production` label 明确生产版本。[Prompt Management](https://langfuse.com/docs/prompt-management/overview)｜[Get Started](https://langfuse.com/docs/prompt-management/get-started)｜[Prompt management at scale](https://langfuse.com/resources/engineering/prompt-management-at-scale)

### 2.6 Datasets / Experiments：维护测试集并比较版本

建议区分两个对象：Dataset 是输入及可选 expected output 的测试用例集合；Experiment 是把某个任务/提示词版本跑过这些用例后形成的一次结果。常见 UI 工作流：

1. `Datasets` → 新建或打开 dataset，在 `Items` 中维护用例；用 `/` 命名可形成虚拟文件夹。
2. 从 dataset 详情点击 `Start Experiment`，选择 Prompt Experiment，填写名称、prompt/version、模型及 evaluators。
3. 运行后在 `Experiments` 查看聚合 score、cost、latency 和 error。
4. 选择基线与候选 run → `Compare`，先看整体差异，再下钻到退化用例及其 trace。
5. 只有相同 dataset version 和 evaluator 定义的 runs 才适合直接做发布比较。

证据：[Datasets 官方文档](https://langfuse.com/docs/evaluation/experiments/datasets)｜[Experiments via UI](https://langfuse.com/docs/evaluation/experiments/experiments-via-ui)｜[Compare experiments](https://langfuse.com/docs/evaluation/experiments/compare-experiments)

### 2.7 Scores / Evaluators：读懂自动与人工评分

Score 是统一评价结果，可挂在 observation、trace、session 或 dataset run 上，类型包括 numeric、categorical、boolean、text；来源可能是 UI 人工标注、API/SDK 或自动 evaluator。[Score data model](https://langfuse.com/docs/evaluation/scores/data-model)

建议手册说明：

- `Scores` 用于集中筛选、查看和分析评分结果；详情页的 `Scores` tab 用于看单条记录的评分。
- 手工打分前要有 Score Config；在 trace/session/observation 详情点 `Annotate`，选维度、填值，可选填 comment。[Scores via UI](https://langfuse.com/docs/evaluation/evaluation-methods/scores-via-ui)
- `Evaluators` 定义“怎么评分”，rule 定义“哪些新 observation 要评分”；自动评分可能异步出现。
- Code evaluator 适合确定性规则；LLM-as-a-Judge 适合语义判断。自托管 code evaluator 只有配置 dispatcher 后才启用。[Code evaluators](https://langfuse.com/docs/evaluation/evaluation-methods/code-evaluators)｜[Evaluation concepts](https://langfuse.com/docs/evaluation/core-concepts)

### 2.8 Human Annotation：批量人工复核

建议使用当前菜单名 `Human Annotation`，正文解释对象叫 Annotation Queue：

1. `New Queue`，选择 Score Configs，填写 queue name/description，可选分配 reviewers。
2. 从 Tracing/Sessions 列表勾选多项 → `Actions` → `Add to queue`；单项可从 `Annotate` 下拉加入。
3. 审核人打开队列，按定义的维度评分、写 comment/纠正输出，点 `Complete + next`。
4. 队列审核不会自动更新 dataset 或批准发布，仍需负责人确认后纳入 dataset 并重跑实验。

证据：[Annotation Queues 官方文档](https://langfuse.com/docs/evaluation/evaluation-methods/annotation-queues)

### 2.9 Dashboards / Alerts：日常监控

`Dashboards` 包括可复用 Widgets 与 Dashboards。非开发人员可先用官方预置的 latency、cost、usage dashboard，再按 traces/observations/scores 选择指标、维度、过滤器和图表类型创建 widget；项目 `Home` 本身也是一个可选默认 dashboard。[Custom Dashboards 官方文档](https://langfuse.com/docs/metrics/features/custom-dashboards)

`Alerts` 用于在 cost 或 quality 指标越过阈值时通知 Slack、GitHub Actions 或 webhook。创建路径是项目 `Alerts` → `New Alert`，再选 data source、metric 和阈值。[Alerts 官方文档](https://langfuse.com/docs/observability/features/alerts)

### 2.10 Settings / Access：团队成员与项目配置

建议分成“项目设置”和“组织设置”两节：项目设置通常涵盖项目资料、API keys、模型/集成等项目资源；组织设置用于成员邀请和组织级角色。只有具备相应权限的角色才会看到管理项。细粒度 project-level roles 仅 Cloud Pro + Teams Add-on、Cloud Enterprise，以及 Self-hosted Enterprise Edition 可用。[RBAC 官方文档](https://langfuse.com/docs/administration/rbac) API public/secret keys 位于项目 settings。[Public API 官方文档](https://langfuse.com/docs/api-and-data-platform/features/public-api)

## 3. Cloud、自托管与套餐差异

正式手册应增加醒目标注，避免把“入口缺失”误写成通用故障：

| 能力 | Langfuse Cloud | Self-hosted |
|---|---|---|
| 核心 observability、prompt、dataset、experiment、score、dashboard | 各套餐普遍提供，但历史数据、吞吐量和部分用量有限制 | OSS 提供核心平台功能；运维、升级、容量和备份由部署方负责 |
| Alerts | 各套餐可用，但上限分别为 Hobby 2、Core 20、Pro 50、Enterprise 100 | v4+ 可用且官方说明无数量上限 |
| Human Annotation Queues | Hobby 1、Core 3、Pro/Enterprise 更多/不限（以当期价格页为准） | 核心功能可用 |
| Project-level RBAC | Pro 需 Teams Add-on；Enterprise 可用 | Enterprise Edition |
| 数据保留策略、UI 审计日志 | Pro/Enterprise 或 Enterprise（按功能） | Enterprise Edition；OSS 不应假设 UI 中存在这些入口 |
| Code evaluators | 可用 | 可用，但必须由管理员配置 code evaluator dispatcher；否则功能禁用 |
| Langfuse Assistant | Cloud 计划提供不同用量 | 官方迁移文档明确部分自托管场景不可用，不应在通用手册中作为必经步骤 |

来源：[Cloud Pricing](https://langfuse.com/pricing)｜[Self-hosted Pricing](https://langfuse.com/pricing-self-host)｜[Alerts](https://langfuse.com/docs/observability/features/alerts)｜[RBAC](https://langfuse.com/docs/administration/rbac)｜[Self-hosted hardening](https://langfuse.com/self-hosting/configuration/hardening)｜[Code evaluators](https://langfuse.com/docs/evaluation/evaluation-methods/code-evaluators)

价格页和功能边界会变化，正式手册不宜把套餐数字写成永久规则；应注明“以当前部署和管理员授权为准”，并记录手册对应的 Langfuse 小版本。

## 4. 推荐手册大纲（供用户确认）

1. 手册说明：适用对象、Langfuse 版本、Cloud/自托管范围、名词约定
2. 快速认识界面：组织、项目、侧栏、时间范围、environment、过滤与保存视图
3. 五分钟上手：找到一次调用 → 打开详情 → 定位异常步骤 → 留下评分/评论
4. Tracing 操作：列表、筛选、trace tree、timeline/graph、输入输出、错误、成本
5. Sessions 与 Users：多轮会话复盘、终端用户聚合、两类“用户”的区别
6. 人工质量检查：Scores、Annotate、Human Annotation 队列
7. 数据集与实验：Dataset Items、启动实验、查看结果、Compare、退化用例下钻
8. 提示词协作：Prompts、版本、labels、Playground、实验、发布与回滚
9. 自动评价：Evaluators、Rules、异步 scores（业务人员以查看和复核为主）
10. 日常监控：Home、Dashboards、Widgets、Alerts
11. 团队与权限：项目/组织切换、成员角色、Settings、看不到入口的排查
12. 常见问题：无数据、数据延迟、找不到 session/user/score、权限不足、v3/v4 文案差异
13. 附录：业务术语表、角色权限速查、截图清单、Cloud/自托管差异

## 5. 待确认与截图阶段核验项

- 本项目目标部署的准确 Langfuse v4 小版本、Cloud 还是 self-hosted，以及是否启用完整 v4 数据路径。
- 实际侧栏是否显示 `Experiments`、`Alerts`、`Human Annotation`，以及 `Tracing` 页面是否仍混有迁移期提示。
- 目标读者权限：Viewer、Member、Admin 还是混合；这会决定是否写创建/删除/配置操作。
- 手册是否聚焦本项目的业务验收流程，还是覆盖 Langfuse 通用全部能力。
- Prompt 的发布 label、score config、dataset、environment 命名应以本项目实际约定为准。
- UI 截图应从目标部署实拍；官方文档截图可能来自 Cloud 或不同小版本，不宜直接当成本项目界面。

### 易变或不确定的 UI 文案

- `Tracing` 在旧资料中常写作 `Traces`；v4 当前路由标题是 `Tracing`。
- `Human Annotation` 是当前侧栏标题，对象和官方功能页仍称 `Annotation Queues`。
- `Experiments` 当前为受 feature flag 控制的独立入口，但 UI Prompt Experiment 仍可从 dataset 详情的 `Start Experiment` 发起。
- `Evaluators` 在迁移期存在 v4/legacy 路径差异；不应把旧版 `Templates / Configs / Log` 写进 v4 主流程。
- trace detail 中的 tree、timeline、agent graph 具体标签会随 observation 类型与小版本变化，截图后再锁定中文指引。

## 6. 侧栏页面与官方截图源映射（2026-09-21 核验）

本节只采用 Langfuse 官方文档站和 `langfuse/langfuse-docs` 官方仓库。图片可通过 `https://langfuse.com` 下的公开路径下载；括号内同时记录仓库路径，便于后续核对来源。可靠性分为：

- **v4 可直接使用**：截图中可见 v4 版本号或 2026-08 v4 上线后的页面形态/数据日期。
- **官方参考图，需目标部署实拍替换**：官方当前文档仍引用该图，但画面可确认来自 v3，或没有足够证据证明是 v4；可临时说明概念，不应作为最终 v4 操作定位图。

### 6.1 可观测性

| 页面 | 页面用途 | 面向非开发人员的核心 UI 工作流 | 官方截图或素材源 | v4 可靠性 |
|---|---|---|---|---|
| `Tracing` | 查看应用每一步 observation，并按共同 `trace_id` 还原一次完整请求；用于查错误、慢调用、高成本调用和链路中间步骤。 | 选择时间和环境 → 用搜索/过滤器按 `level`、`type`、`name`、`trace_id`、用户或会话缩小范围 → 打开记录 → 在 trace tree/graph 中核对输入、输出、错误、耗时、成本和 scores → 对异常步骤评论、评分或加入数据集。[v4 observations FAQ](https://langfuse.com/faq/all/explore-observations-in-v4)｜[Observability overview](https://langfuse.com/docs/observability/overview) | [Tracing 页面与详情](https://langfuse.com/images/docs/tracing-overview.png)（仓库：`public/images/docs/tracing-overview.png`）；[v4 Tracing 操作视频](https://static.langfuse.com/docs-videos/2026-03-10-demo-saved-views.mp4) | **v4 可直接使用**。图片显示 2026-08 数据、v4 observation 表、`Is Root Observation` 过滤器和新详情树。 |
| `Sessions` | 把同一多轮会话的多条 traces 聚合并按时间回放，适合复盘完整对话而非单次请求。 | 搜索/筛选 session → 打开详情 → 顺序阅读每轮 input/output 和 scores → 需要时收藏、公开分享或人工评分。[Sessions](https://langfuse.com/docs/observability/features/sessions) | [Session view](https://langfuse.com/images/docs/session.png)（仓库：`public/images/docs/session.png`）；[Sessions 列表示例](https://langfuse.com/images/docs/faq/good-trace-sessions-view.png)（仓库：`public/images/docs/faq/good-trace-sessions-view.png`） | **官方参考图，需实拍替换**。详情图中数据日期为 2024-11，且未显示 v4 版本号；当前功能说明可靠，但不能证明界面为 v4。 |
| `Users` | 按业务应用中的终端 `userId` 聚合事件、token、成本和反馈；这里不是 Langfuse 团队成员管理页。 | 按 User ID、时间、环境筛选 → 查看事件数、token 和成本 → 打开单个用户 → 检查该用户的 traces、反馈及聚合指标。[User Tracking](https://langfuse.com/docs/observability/features/users) | [Users 列表](https://langfuse.com/images/docs/users-list.png)（仓库：`public/images/docs/users-list.png`）；[User 详情](https://langfuse.com/images/docs/user-detail-view.png)（仓库：`public/images/docs/user-detail-view.png`） | **官方参考图，需实拍替换**。列表数据日期为 2025，早于 v4 正式上线；未发现可可靠确认的 v4 Users 截图。 |
| `Alerts` | 按 observation 或 score 指标监控成本、延迟与质量，越过 warning/alert 阈值时通过 automation 通知。 | `New Alert` → 选择 data source、metric、filters 和时间窗口 → 设置 warning/alert 阈值及 no-data/renotify 行为 → 连接 Slack、Webhook 或 GitHub Actions automation → 保存后在列表查看状态，必要时暂停、恢复或删除。[Alerts](https://langfuse.com/docs/observability/features/alerts) | [官方 Alerts 文档当前引用的列表图](https://langfuse.com/images/docs/monitors-list.png)（仓库：`public/images/docs/monitors-list.png`） | **不能用作 v4 定位图**。素材明确显示 `v3.194.0`、`Monitors`、`New Monitor`，而 v4 侧栏和文档称 `Alerts`、`New Alert`；官方未提供可靠的 v4 静态截图。 |

### 6.2 提示词管理

| 页面 | 页面用途 | 面向非开发人员的核心 UI 工作流 | 官方截图或素材源 | v4 可靠性 |
|---|---|---|---|---|
| `Prompts` | 集中管理 text/chat prompt、不可变版本、配置和发布 labels，让业务人员无需改代码即可协作迭代。 | 查找并打开 prompt → 对照历史版本和 labels → 点 `New` 编辑内容/config 并保存成新版本 → 进 Playground 小范围测试 → 用 Experiment 批量验证 → 验收后把 `production`/`staging` label 移到已验证版本；回滚时把 label 移回旧版本。[Prompt Management](https://langfuse.com/docs/prompt-management/overview)｜[Get Started](https://langfuse.com/docs/prompt-management/get-started) | [Prompt 版本详情](https://langfuse.com/images/docs/prompt-management.png)（仓库：`public/images/docs/prompt-management.png`） | **官方参考图，需实拍替换**。画面版本数据为 2025，早于 v4 正式上线；prompt 版本/label 概念仍可参考。 |
| `Playground` | 无代码试跑和并排比较 prompt、模型、参数、变量、工具调用及结构化输出。 | 从空白 Playground、Prompt 页或 generation 详情进入 → 选择模型连接 → 填消息和变量 → 调整参数/工具/JSON schema → `Submit` 或 `Run All` → 并排比较输出 → 满意后保存为 Prompt 版本；正式发布前再跑 dataset experiment。[LLM Playground](https://langfuse.com/docs/prompt-management/features/playground) | [Playground 总览](https://langfuse.com/images/docs/playground-overview.png)（仓库：`public/images/docs/playground-overview.png`）；[并排比较视频](https://static.langfuse.com/docs-videos/playground-side-by-side-comparison.mp4)；[打开 Prompt 视频](https://static.langfuse.com/docs-videos/playground-open-prompt.mp4)；[保存 Prompt 视频](https://static.langfuse.com/docs-videos/playground-save-prompt.mp4) | **官方参考图，需实拍替换**。当前文档素材能准确展示并排比较流程，但截图没有 v4 版本证据，模型和页面来自 v4 上线前的 UI。 |

### 6.3 评测

| 页面 | 页面用途 | 面向非开发人员的核心 UI 工作流 | 官方截图或素材源 | v4 可靠性 |
|---|---|---|---|---|
| `Scores` | 集中查看所有人工、自动 evaluator、SDK/API 评分，并用 Analytics 看分布、趋势及两个评分的一致性。 | 在 Scores 表按名称、来源、对象类型、时间筛选 → 打开关联 trace/observation 复核 → 切到 `Analytics` 选择一个分数看统计、分布和趋势，或选第二个同类型分数看相关性/一致性。[Scores](https://langfuse.com/docs/evaluation/scores/overview)｜[Score Analytics](https://langfuse.com/docs/evaluation/scores/score-analytics) | [Score Analytics 总览](https://langfuse.com/images/docs/score-analytics-full-dashboard.png)（仓库：`public/images/docs/score-analytics-full-dashboard.png`）；[Boolean 单评分](https://langfuse.com/images/docs/score-analytics-boolean-single.png)；[Boolean 双评分比较](https://langfuse.com/images/docs/score-analytics-boolean-compare.png) | **官方参考图，建议实拍替换**。当前文档图片与侧栏结构接近 v4，但画面没有版本号或 v4 上线后的日期，不能可靠确认。 |
| `Evaluators` | 创建“如何评分”的 LLM-as-a-Judge 或 Code evaluator，并通过 Rules 定义哪些新 observations 自动评分。 | `New evaluator` → 选模板或从空白创建 → 设置输入字段、评价标准、输出分数和模型/代码 → 在右侧选择真实 observations 测跑并迭代 → 保存 → 新建/关联 Rule，设置 filters、sampling 和 evaluators → 查看异步 scores；失败时打开 evaluator 执行 trace。[Evaluate Production Traffic](https://langfuse.com/docs/evaluation/get-started/online)｜[Core Concepts](https://langfuse.com/docs/evaluation/core-concepts) | [Evaluators 首页](https://langfuse.com/images/docs/evaluation/create-evaluator.png)（仓库：`public/images/docs/evaluation/create-evaluator.png`）；[测试 LLM evaluator](https://langfuse.com/images/docs/evaluation/test-llm-evaluator.png)；[2026-08 新评测流程视频](https://static.langfuse.com/docs-videos/2026-08-22-new-eval-experience.mp4) | **v4 可直接使用**。首页截图明确显示 `v4.15.0`，且视频发布时间和页面流均为 v4。 |
| `Human Annotation` | 用 Annotation Queues 将 traces、observations 或 sessions 分配给领域专家，按统一 Score Config 批量人工打分、评论和填写 corrected output。 | `New Queue` → 选 Score Config、填写名称/说明并可分配审核人 → 从 Tracing/Sessions 勾选记录后 `Actions` → `Add to queue` → 审核人进入队列评分、评论/纠正 → `Complete + next`；结果不会自动写回 Dataset 或批准发布。[Annotation Queues](https://langfuse.com/docs/evaluation/evaluation-methods/annotation-queues)｜[Scores via UI](https://langfuse.com/docs/evaluation/evaluation-methods/scores-via-ui) | [批量加入队列](https://langfuse.com/images/docs/add_multiple_items_to_queue.png)（仓库：`public/images/docs/add_multiple_items_to_queue.png`）；[单条加入队列](https://langfuse.com/images/docs/add_to_queue.png)；单条人工评分步骤：[打开 Annotate](https://langfuse.com/images/docs/trigger_annotation.png)、[选择 Score Config](https://langfuse.com/images/docs/select_score_configs.png)、[填写分值](https://langfuse.com/images/docs/set_score_values.png)、[填写评论](https://langfuse.com/images/docs/scores_comment.png)、[查看已建 Scores](https://langfuse.com/images/docs/see_created_scores.png)；[人工评分视频](https://static.langfuse.com/docs-videos/2025-12-19-manual-scoring.mp4)；[完整队列流程视频](https://static.langfuse.com/docs-videos/2025-12-19-annotation-queues.mp4) | **官方参考图，需实拍队列页**。静态图覆盖加入队列和单条评分，但没有 `Human Annotation` 首页/队列处理页，且素材早于 v4；未发现可靠的 v4 队列主页静态截图。 |
| `Datasets` | 管理可复用测试用例集合；每条 item 包含 input、可选 expected output 和 metadata，并支持版本化、CSV 导入及从生产 trace 收集案例。 | 新建/打开 dataset → `Items` 中新增或编辑 input、expected output、metadata → 批量导入、归档/删除或从 trace 加入 → 检查 dataset version → 从 dataset 发起 Experiment。[Datasets](https://langfuse.com/docs/evaluation/experiments/datasets) | [Dataset Items 页面](https://langfuse.com/images/docs/datasets-overview.png)（仓库：`public/images/docs/datasets-overview.png`）；[新建 Dataset](https://langfuse.com/images/docs/create_dataset.png)；[版本化 Items](https://langfuse.com/images/docs/dataset-versioned-items.png)；[从 Trace 加入 Dataset 视频](https://static.langfuse.com/docs-videos/datasets-add-from-trace.mp4) | **官方参考图，需实拍替换**。主图数据日期为 2024，早于 v4；未发现可靠的 v4 Dataset 列表/Items 静态截图。 |
| `Experiments` | 查看一次任务或 Prompt 在固定 Dataset 上运行所得的结果集合，比较版本并从失败 item 下钻到 Trace/Observations。 | 从 Dataset `Start Experiment` 配置 Prompt/模型/变量映射/evaluators 并运行，或查看外部触发的 custom experiment → 在 Experiments 看 score、cost、latency、error → 选择可比 runs 点 `Compare` → 用 score 阈值筛退化 item → 打开 item 及关联 trace → 沿 observations 定位 retrieval、LLM、tool 或应用步骤 → 人工评分并决定修 prompt、evaluator 或测试数据。[Experiments via UI](https://langfuse.com/docs/evaluation/experiments/experiments-via-ui)｜[Compare experiments](https://langfuse.com/docs/evaluation/experiments/compare-experiments) | [Experiments 多选与 Compare](https://langfuse.com/images/docs/experiment-comparison-selection.png)（仓库：`public/images/docs/experiment-comparison-selection.png`）；[结果比较](https://langfuse.com/images/docs/experiment-comparison.png)；[失败 item 与 Trace peek](https://langfuse.com/images/docs/experiment-comparison-peek-view.png)；[UI Prompt Experiment 视频](https://static.langfuse.com/docs-videos/prompt-experiments.mp4) | **v4 可直接使用**。Compare 图中数据日期为 2026-09；与 v4 独立 `Experiments` 入口、`Run Evaluator` 和比较流程一致。 |

### 6.4 截图落地建议

1. 最终手册优先直接采用三组可确认的 v4 官方图：`Tracing`、`Evaluators`、`Experiments`。
2. `Alerts` 官方静态图明确是 v3，不应下载进最终手册冒充 v4；应从目标 self-hosted v4 实拍 `Alerts` 列表、新建表单和详情状态。
3. `Sessions`、`Users`、`Prompts`、`Playground`、`Scores`、`Human Annotation`、`Datasets` 的官方图可作为拍摄构图参考，但最终定位图应从目标部署实拍，以确保中文手册中的按钮名、侧栏和权限入口一致。
4. 若使用官方图片，应在图片说明中标注“官方示例界面，数据与本项目无关”；若实拍目标部署，必须先脱敏 user ID、session ID、trace 内容、业务输入输出、模型密钥和客户数据。
