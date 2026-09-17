# docs/archive · 过程文档归档

历史里程碑的过程性文档(评审记录、状态报告、交接稿、点位设计)。**只读参考,不再维护**;
内容反映写作时点的状态,与当前代码可能不一致——现行约定以根 `CLAUDE.md`、`docs/adr/` 与
`docs/` 根下的活文档为准。

| 目录 | 内容 | 时段 |
|---|---|---|
| `m2/` | M2 里程碑过程文档:业务种子评审、真 LLM 评估报告与跑法、g008 灰度、提示词 A/B、ticker 子图状态、LLM 生成 case、种子收集模板(`m2-golden-seeds/`) | 2026-04~05 |
| `m3/` | M3 里程碑过程文档:测试基线清理、路由歧义决策、on-call 演练、业务交接邮件、shadow 双跑设计、真后端样本、现场 API 接入、团队分工 | 2026-05 |
| `reports/` | 日期型状态报告与已行动完毕的评估:测试与连通性状态、YAML 覆盖、测试大扫除、全模块测试报告(`tests/test_case.md` 迁入)、架构评估(FastMCP/A2A 决策)、架构成熟度体检(3 改进项已落地)、意图识别评估(#167 已修复) | 2026-05 / 2026-08 |
| `history/` | 历史叙事与被取代的手册:Dify 迁移记(v1)、ticker 图重构记、ticker 操作手册(ReAct 版,已被 DSL v2 resolver 管线取代)、高质量 LangGraph 项目复盘 | 2026-03~05 |
| `business-cases/` | 业务方测试用例原始资料(xlsx + csv 导出),已消化进 golden 三桶,golden 为唯一现行口径 | 2026-04~05 |
| ~~`dify-originals/`~~ | 业务方交付的 Dify 工作流 YAML 原始快照，已随 ADR 0024 D1 移出仓库（连同 dify/ 同步工具）；需要时 `git checkout dify-assets-frozen-20260917 -- docs/archive/dify-originals dify` | 2026-05~08，2026-09-17 移除 |

归档纪律:新的过程文档完成使命后移入对应目录;移动时用 `git mv` 并全仓修复引用
(链接检查方式见本次归档 commit)。活文档(roadmap / runbook / SOP / 架构 / 评估报告)留在 `docs/` 根。
