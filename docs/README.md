# docs · 文档地图与存放规则

一页看懂文档在哪、读什么、何时读，以及**新文档该放哪**。存放规则由 `scripts/check_docs_layout.py`
在 CI fast job 中强制检查；人和 AI agent（Claude Code / Codex）写文档都按本页执行。

## 新人阅读路径

1. 根 `CLAUDE.md` —— 项目现状、命令、核心原则、排查 SOP
2. [architecture/](./architecture/README.md) —— 单页导览 + 分层说明
3. 根 `CONTEXT.md` —— 领域语言（业务术语）
4. [adr/](./adr/README.md) —— 架构决策索引，按需查

## 目录总览

| 目录 | 放什么 | 典型读者 |
|---|---|---|
| [architecture/](./architecture/README.md) | 系统全貌、分层、跨系统职责边界（现行设计的**事实描述**） | 所有人 |
| [adr/](./adr/README.md) | 架构决策记录：为什么这样设计（`NNNN-<topic>.md`） | 开发、评审 |
| [api-contracts/](./api-contracts/README.md) | 外部系统（Java 后端）真实 API 契约 | 开发 |
| [development/](./development/README.md) | 本地开发环境、日常工作流、开发期排错、调试接口 | 开发 |
| [testing/](./testing/README.md) | 测试分层与命令、数据集、本地种子数据 | 开发、测试 |
| [langfuse/](./langfuse/README.md) | LangFuse 评测链路、Web UI 操作、同步与自托管部署 | 开发、业务方 |
| [deploy/](./deploy/README.md) | 客户环境调研、私有化部署、上线前 shadow 对照 | 实施、运维 |
| [operations/](./operations/README.md) | 上线后运维：可观测性、值班手册、生产故障 SOP | 值班、运维 |
| [training/](./training/README.md) | 培训材料（新人入门、交互课程、业务方培训） | 新成员、业务方 |
| [agents/](./agents/README.md) | AI agent 协作约定（issue tracker / triage 标签 / 领域文档布局） | AI agent |
| [reports/](./reports/README.md) | 一次性报告快照：评估、审阅、调研（带日期，不再维护） | 按需 |
| [work-plan.md](./work-plan.md) | 三条主线的现状与待办（唯一的动态计划文档） | 所有人 |

排障文档按场景分三层：开发期 Q&A 在 [development/troubleshooting.md](./development/troubleshooting.md)，
生产根因诊断在 [operations/troubleshooting-sop.md](./operations/troubleshooting-sop.md)，
值班应急决策在 [operations/on-call-runbook.md](./operations/on-call-runbook.md)。

## 存放规则

### 1. 新文档放哪：按「这份文档回答什么问题」判定

| 文档回答的问题 | 放到 |
|---|---|
| 系统现在长什么样、某段逻辑住在哪、谁负责什么 | `architecture/` |
| 为什么做这个技术决定、有哪些取舍 | `adr/`（编号递增，只写现行结论） |
| 外部接口的字段、路径、错误码是什么 | `api-contracts/` |
| 我在本地怎么跑起来、怎么调试、开发时报错怎么办 | `development/` |
| 怎么测、测试数据怎么准备、数据集怎么组织 | `testing/` |
| LangFuse 怎么用、评测怎么跑 | `langfuse/` |
| 怎么部署到客户环境、上线前怎么对照 | `deploy/` |
| 上线后怎么监控、出事了怎么处理 | `operations/` |
| 怎么教会新人 / 业务方 | `training/` |
| AI agent 读的协作约定 | `agents/` |
| 某一天做的评估、审阅、调研、复盘结论（写完即冻结） | `reports/YYYY-MM-DD-<topic>.md` |
| 接下来做什么、现状如何 | 更新 `work-plan.md`，不另建计划文件 |

判定不了时优先并入已有文档的一节，而不是新建文件；确需新主题目录，先改本页与 lint 白名单再建。

### 2. 硬性约束（lint 强制）

- `docs/` 根目录只放 `README.md` 与 `work-plan.md`，其余文档一律进主题目录
- 主题目录只用上表白名单；每个主题目录必须有 `README.md` 作索引，新增文档同时登记到该索引
- 文件与目录名一律小写 kebab-case（`on-call-runbook.md`），`README.md` 例外；不用大写、下划线、空格或中文文件名
- 文件名带日期的文档只能进 `reports/`，且必须以日期开头：`reports/2026-09-24-intent-dataset-assessment.md`
- 链接必须有效：`docs/` 内的 Markdown / HTML 相对链接，以及全仓代码、脚本、配置里写的 `docs/...` 路径
- 图片等附件放在所属主题目录的 `images/` 或 `assets/` 下，与引用它的文档同目录树

### 3. 约定（评审把关）

- **现行文档只写现状**：过时内容直接改或删，历史从 git 找回；不保留"旧版 / v2 / 备份"并存文件
- **报告是快照**：`reports/` 里的文档写完不再维护；结论要长期生效时，提炼进 ADR、`architecture/` 或 `work-plan.md`，
  报告可在结论被吸收后删除
- **不放生成物**：测试报告、评测输出、导出数据写到 `.harness-runs/` 或 `tmp/`（已 gitignore），不进 `docs/`
- **单一真源**：同一事实只在一处维护，别处链接过去；纪律类规则写在 `CLAUDE.md` / `.claude/rules/`，`docs/` 不复述
- 移动或改名文档时全仓更新引用，跑 `python scripts/check_docs_layout.py` 确认零违规

## 不在 docs/ 里的重要文档

- 项目纪律：根 `CLAUDE.md` + `.claude/rules/`（Codex 读生成的 `AGENTS.md`）
- 领域语言：根 `CONTEXT.md`
- 提示词资产：`app/prompts/**/*.md`（git 唯一真源，见 `.claude/rules/prompt-management.md`）
- 测试数据集：`tests/fixtures/`（说明见 `tests/fixtures/README.md`）
- 脚本目录页：`scripts/CLAUDE.md`；基础设施：`infra/langfuse/README.md`
- 子目录陷阱页：`app/prompts/CLAUDE.md`、`tests/CLAUDE.md`、`scripts/CLAUDE.md`
