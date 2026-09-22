# docs · 文档地图

> 一页看懂文档在哪、读什么、何时读。纪律：**根目录只放"运行与交付这个系统必需的活文档"**；
> 过程性文档完成使命后进 `archive/`（见 [archive/README.md](./archive/README.md) 的归档纪律）。

## 新人阅读路径

1. 根 `CLAUDE.md` —— 项目现状、命令、核心原则、排查 SOP（唯一必读）
2. [ARCHITECTURE.md](./ARCHITECTURE.md) —— 单页导览 + 分层细节
3. 根 `CONTEXT.md` —— 领域语言（业务术语）
4. [adr/README.md](./adr/README.md) —— 24 篇架构决策索引，按需查

## 根目录活文档（9 个）

| 文档 | 读它的时机 |
|---|---|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | 理解系统全貌、找某段逻辑住在哪 |
| [DEVELOPMENT.md](./DEVELOPMENT.md) | 本地开发环境与日常工作流 |
| [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) | **开发期**遇错快查（Q&A 导向） |
| [troubleshooting-sop.md](./troubleshooting-sop.md) | **生产**故障根因诊断（SOP 导向） |
| [on-call-runbook.md](./on-call-runbook.md) | **值班**应急决策（回切/降级导向） |
| [observability.md](./observability.md) | LangFuse / Prometheus / 告警接线 |
| [m3-m4-roadmap.md](./m3-m4-roadmap.md) | 里程碑任务图与 owner 表 |
| [swap-prompt-slimming-assessment.md](./swap-prompt-slimming-assessment.md) | 提示词瘦身依据（#173/#174 进行中） |
| 本文件 | 找不到文档时 |

三份排障文档是**有意分层**（开发 Q&A / 生产 SOP / 值班手册），入口选错会绕路——按上表时机选。

## 主题目录

| 目录 | 职责 |
|---|---|
| [adr/](./adr/) | 架构决策记录（0000–0023），只增不改，被取代标 Superseded |
| [api-contracts/](./api-contracts/) | Java 后端真实 API 契约 |
| [deploy/](./deploy/) | 应用私有化部署和 shadow 双跑指南 |
| [langfuse/](./langfuse/) | Langfuse 功能、评测链路、配置上传、Experiment 执行与问题追踪 |
| [customer/](./customer/) | 客户环境评估 |
| [training/](./training/) | 团队培训材料（LangGraph 手册、课程、Windows 环境搭建） |
| [agents/](./agents/) | AI agent 协作约定（issue tracker / triage 标签 / 领域文档布局） |
| [archive/](./archive/) | **只读**历史：过程文档、日期型报告、业务用例原始资料、Dify YAML 快照 |

## 不在 docs/ 里的重要文档

- 提示词资产：`app/prompts/**/*.md`（生产资产，改动走灰度纪律，见 `.claude/rules/prompt-management.md`）
- 现行 Dify YAML：`dify/yaml/`（`python dify/sync.py` 拉取）
- golden 数据集：`tests/fixtures/*.jsonl`
- 子目录陷阱页：`app/prompts/CLAUDE.md`、`tests/CLAUDE.md`、`scripts/CLAUDE.md`
