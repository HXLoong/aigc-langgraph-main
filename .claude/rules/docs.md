# 文档存放规则

> 完整目录表与判定表见 `docs/README.md`「存放规则」；`scripts/check_docs_layout.py` 在 CI fast job 强制检查。
> 本文件只写 agent 写文档时必须遵守的"怎么做"。

## 写之前先判定归属

| 文档回答的问题 | 放到 |
|---|---|
| 系统现在长什么样 / 职责边界 | `docs/architecture/` |
| 为什么这样决定 | `docs/adr/NNNN-<topic>.md`（只写现行结论） |
| 外部接口契约 | `docs/api-contracts/` |
| 本地开发、调试、开发期报错 | `docs/development/` |
| 测试分层、数据集、测试环境 | `docs/testing/` |
| LangFuse 与评测链路 | `docs/langfuse/` |
| 客户环境调研、部署、上线前对照 | `docs/deploy/` |
| 上线后监控、值班、生产排障 | `docs/operations/` |
| 培训材料 | `docs/training/` |
| agent 协作约定 | `docs/agents/` |
| 某次评估 / 审阅 / 调研 / 复盘的结论 | `docs/reports/YYYY-MM-DD-<topic>.md` |
| 现状与待办 | 更新 `docs/work-plan.md`，不另建计划文件 |

优先并入已有文档的一节；只有确属新主题时才新建文件。

## 硬性约束

- `docs/` 根目录只允许 `README.md`、`work-plan.md`；主题目录只用上表，新增目录须先改 `docs/README.md` 与 lint 白名单
- 文件名小写 kebab-case（`README.md` 例外），不用大写、下划线、空格、中文文件名
- 带日期的文档只进 `docs/reports/`，且以日期开头；其他目录的文档写现状，不带日期
- 新建文档同时登记到所在目录的 `README.md` 索引
- 移动 / 改名文档时全仓更新引用（代码注释、脚本、CI、`CLAUDE.md`），跑 `python scripts/check_docs_layout.py` 零违规

## 禁止

- 在仓库根目录或 `docs/` 根散落分析、计划、方案类 `.md`（这类内容进 `reports/` 或并入 `work-plan.md`）
- 生成物（测试报告、评测输出、导出数据）进 `docs/`——写 `.harness-runs/` 或 `tmp/`
- 同一事实多处维护、"v2 / 新版 / 备份"文件并存；过时内容直接改或删，历史从 git 找回
- 在 `docs/` 复述 `CLAUDE.md` / `.claude/rules/` 的纪律，链接过去即可
