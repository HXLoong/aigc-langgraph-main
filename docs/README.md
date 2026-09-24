# docs · 文档地图

一页看懂文档在哪、读什么、何时读。本目录只放运行和交付这个系统所需的现行文档；一次性的报告与过程记录用完即删，历史从 git 找回。

## 新人阅读路径

1. 根 `CLAUDE.md` —— 项目现状、命令、核心原则、排查 SOP
2. [ARCHITECTURE.md](./ARCHITECTURE.md) —— 单页导览 + 分层说明
3. 根 `CONTEXT.md` —— 领域语言（业务术语）
4. [adr/README.md](./adr/README.md) —— 架构决策索引，按需查

## 根目录文档

| 文档 | 读它的时机 |
|---|---|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | 理解系统全貌、找某段逻辑住在哪 |
| [DEVELOPMENT.md](./DEVELOPMENT.md) | 本地开发环境与日常工作流 |
| [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) | **开发期**遇错快查（Q&A） |
| [troubleshooting-sop.md](./troubleshooting-sop.md) | **生产**故障根因诊断（SOP） |
| [on-call-runbook.md](./on-call-runbook.md) | **值班**应急决策（回切 / 降级） |
| [observability.md](./observability.md) | LangFuse / Prometheus / 告警接线 |
| [backend-instrument-boundary.md](./backend-instrument-boundary.md) | 标的识别的 LangGraph / Java 职责边界 |
| [nodes-run.md](./nodes-run.md) | 节点级调试接口与节点回归 |
| [work-plan.md](./work-plan.md) | 三条主线的现状与待办 |

三份排障文档按场景分层（开发 Q&A / 生产 SOP / 值班手册），按上表时机选择。

## 主题目录

| 目录 | 职责 |
|---|---|
| [adr/](./adr/) | 现行架构决策 |
| [api-contracts/](./api-contracts/) | Java 后端真实 API 契约 |
| [deploy/](./deploy/) | 客户私有化部署、shadow 对照工具指南 |
| [langfuse/](./langfuse/) | LangFuse 自托管部署、评测链路、配置上传与 Web UI 操作 |
| [testing/](./testing/) | 测试分层与命令、本地种子数据 |
| [customer/](./customer/) | 客户环境调研模板 |
| [training/](./training/) | 团队培训材料（入门、课程、业务方培训） |
| [agents/](./agents/) | AI agent 协作约定（issue tracker / triage 标签 / 领域文档布局） |

## 不在 docs/ 里的重要文档

- 提示词资产：`app/prompts/**/*.md`（git 唯一真源，见 `.claude/rules/prompt-management.md`）
- 测试数据集：`tests/fixtures/`（说明见 `tests/fixtures/README.md`）
- 子目录陷阱页：`app/prompts/CLAUDE.md`、`tests/CLAUDE.md`、`scripts/CLAUDE.md`
