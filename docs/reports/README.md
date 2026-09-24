# 报告 · 一次性评估、审阅与调研快照

本目录存放**某一时点**产出的报告：数据集评估、代码审阅导读、专项调研、事故复盘等。报告写完即冻结，不随代码更新；
需要长期生效的结论提炼进 ADR、`architecture/` 或 `work-plan.md`，结论被吸收后报告可删除（历史从 git 找回）。

命名：`YYYY-MM-DD-<topic>.md`，日期为报告完成日；lint 拒绝在其他目录放带日期的文档。

| 报告 | 摘要 |
|---|---|
| [2026-09-24-intent-dataset-assessment.md](./2026-09-24-intent-dataset-assessment.md) | 期权 / 互换意图识别数据集评估：意图集只调 LLM 的可行性与改造建议 |
| [2026-09-24-option-open-close-review-guide.md](./2026-09-24-option-open-close-review-guide.md) | 期权开仓 / 平仓重构代码的人工审阅导读与问题清单 |
