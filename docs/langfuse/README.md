# Langfuse 文档

本目录集中存放 Langfuse 的功能说明、评测链路和日常操作文档。可观测性指标与告警接线见
[../operations/observability.md](../operations/observability.md)，决策背景见
[ADR 0014](../adr/0014-langfuse-as-harness-backend.md)，基础设施快速启动见
[infra/langfuse/README.md](../../infra/langfuse/README.md)。

## 按任务照做的手册

任务手册补充具体操作，已有概念说明、契约和 ADR 通过链接复用。可作为 Notion 页面内容；
页面包含负责人、状态、SDK 与自托管版本、最后验证日期和验证人，正文统一为：适用人群与场景、
前置条件、操作步骤、验证、常见问题、本项目不用的功能及原因、参考。

| 编号 | 手册 | 负责人 | 状态 | 做完能得到什么 |
|---|---|---|---|---|
| A1 | [Trace 查看与排障](./developer-manuals/a1-trace-troubleshooting.md) | @HXl | 草稿 | 按运行名、会话 ID 或消息 ID 找到请求，读 span 树与 turns，定位出错节点 |
| A2 | [Session、User、Tag 与过滤](./developer-manuals/a2-sessions-users-tags-filters.md) | @HXl | 草稿 | 串起多轮会话，按业务用户和标签查记录，组合筛选并保存常用视图 |
| A3 | [Dashboard 与指标分析](./developer-manuals/a3-dashboard-and-metrics.md) | @HXl | 草稿 | 按实际 Home Dashboard 查看延迟、token、成本、错误占比及评分趋势，查阅项目告警阈值与处理规则 |
| A4 | [Dataset 管理（界面）](./developer-manuals/a4-dataset-management.md) | @HXl | 草稿 | 浏览和筛选用例，追溯 Git 来源，理解单向发布并核对发布结果 |
| A5 | [Experiment 结果对比](./developer-manuals/a5-experiment-comparison.md) | @HXl | 草稿 | 对比两次运行，找新增失败用例，阅读确定性 Scores、Comment 和字段差异 |
| A6 | [人工标注与业务复核](./developer-manuals/a6-human-annotation.md) | @HXl | 草稿 | 使用标注队列记录结论与依据，导出复核材料，经业务确认后合入 fixture |

练习只查沙箱测试记录；截图须使用测试数据或先脱敏，不在手册中填写密钥、密码、API Key 或内网地址。
不改正式项目配置，不升级 SDK 或部署。发现资料差异时记录给审阅人，见
[资料审阅记录](../reports/2026-09-29-langfuse-manual-source-review.md)。

## 一、推荐阅读顺序

| # | 文档 | 读完能做什么 |
|---|---|---|
| 1 | [功能与评测链路使用指南](./workflow-guide.md) | 建立对象模型：Dataset / Experiment / Evaluator / Score 的关系，以及本项目怎么用 |
| 2 | [WebUI 操作手册（面向非开发人员）](./web-ui-operation-manual.md) | 同一批对象在 Langfuse v4 界面上长什么样、点哪里（含侧栏导航截图） |
| 3 | [Git 文件同步到 Langfuse](./auto-sync.md) | 自动触发范围、更新规则、GitHub 网页操作和本地验证 |
| 4 | [Agent Skill 与 CLI](./agent-skill-and-cli.md) | 把手动点击换成智能体或命令行：两条自动化路径的作用、关系、安装与使用 |
| 5 | [Langfuse Workshop 学习指南](./langfuse-workshop-intro.md) | 系统补方法论：从 tracing 走到 evaluation |
| 6 | [私有化部署](./self-hosted-deployment.md) | 在客户内网部署、备份、升级和排查自托管 Langfuse |

第 1、2 份是**同一件事的两个视角**（对象 vs 界面），建议配对读：先懂对象，再看界面怎么操作。

## 二、按目的直接找

| 我想… | 看 |
|---|---|
| 搞清 Dataset 的字段怎么设计 | `workflow-guide.md` § 3 |
| 上传用例、配自动评分、配人工评分口径 | `workflow-guide.md` § 4；界面操作见 WebUI 手册 § 3 |
| 跑一次 Experiment、查看失败用例 | `workflow-guide.md` § 5–6 |
| 知道有哪些脚本可用 | `workflow-guide.md` § 7 与 [`scripts/langfuse/README.md`](../../scripts/langfuse/README.md) |
| 分清意图集与业务集两套件 | `workflow-guide.md` § 8 |
| 从 Langfuse 界面点 Run 触发本机跑实验 | [`remote-experiment-webhook.md`](./remote-experiment-webhook.md) |
| 让智能体或命令行替我操作 Langfuse | [`agent-skill-and-cli.md`](./agent-skill-and-cli.md) |
| 从零学 Langfuse 方法论 | [`langfuse-workshop-intro.md`](./langfuse-workshop-intro.md) |
| 在客户内网部署 | [`self-hosted-deployment.md`](./self-hosted-deployment.md) |

## 三、两条边界

- **Workshop 学习指南是外部课程**（约 1000 行），讲通用方法论、跑的是官方的玩具应用。它测不到本项目的链路，不要当项目文档用。
- **私有化部署与其余几份互不依赖** —— 先把部署做完，再回头看前面几份。

截图统一放 [images/](./images/)，按 `NN-<topic>.png` 命名。
