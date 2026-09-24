# 阅读顺序

本目录 6 份文档。按下面的顺序读最省力；只想解决某个具体问题，直接跳第二节。

## 一、推荐顺序

| # | 文档 | 读完能做什么 |
|---|---|---|
| 1 | [功能与评测链路使用指南](./workflow-guide.md) | 建立对象模型：Dataset / Experiment / Evaluator / Score 的关系，以及本项目怎么用 |
| 2 | [WebUI 操作手册](./web-ui-operation-manual.md) | 同一批对象在 Langfuse v4 界面上长什么样、点哪里 |
| 3 | [Agent Skill 与 CLI](./agent-skill-and-cli.md) | 把手动点击换成智能体或命令行 |
| 4 | [Langfuse Workshop 学习指南](./langfuse-workshop-intro.md) | 系统补方法论：从 tracing 走到 evaluation |
| 5 | [私有化部署](./self-hosted-deployment.md) | 部署到客户内网（与前四份互不依赖） |

第 1、2 份是**同一件事的两个视角**（对象 vs 界面），建议配对读：先懂对象，再看界面怎么操作。

## 二、按目的直接找

| 我想… | 看 |
|---|---|
| 搞清 Dataset 的字段怎么设计 | `workflow-guide.md` § 3 |
| 上传用例、配自动评分、配人工评分口径 | `workflow-guide.md` § 4；界面操作见 WebUI 手册 § 3 |
| 跑一次 Experiment、查看失败用例 | `workflow-guide.md` § 5–6 |
| 知道有哪些脚本可用 | `workflow-guide.md` § 7 与 [`scripts/langfuse/README.md`](../../scripts/langfuse/README.md) |
| 分清意图集与业务集两套件 | `workflow-guide.md` § 8 |
| 让智能体或命令行替我操作 Langfuse | [`agent-skill-and-cli.md`](./agent-skill-and-cli.md) |
| 从零学 Langfuse 方法论 | [`langfuse-workshop-intro.md`](./langfuse-workshop-intro.md) |
| 在客户内网部署 | [`self-hosted-deployment.md`](./self-hosted-deployment.md) |

## 三、两条边界

- **Workshop 学习指南是外部课程**（约 1000 行），讲通用方法论、跑的是官方的玩具应用。它测不到本项目的链路，不要当项目文档用。
- **私有化部署与其余四份互不依赖** —— 先把部署做完，再回头看前面几份。
