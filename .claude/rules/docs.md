# 文档存放规则

> 唯一真源：`docs/README.md`「存放规则」（归属判定表 + 硬性约束 + 评审约定），CI 由 `scripts/check_docs_layout.py` 强制。

agent 新建或移动文档时：

1. **先读 `docs/README.md`「存放规则」判定归属**；能并入已有文档的一节就不新建文件
2. 一次性的评估 / 审阅 / 调研 / 复盘结论写 `docs/reports/YYYY-MM-DD-<topic>.md`；现状与待办更新 `docs/work-plan.md`
3. 不在仓库根目录或 `docs/` 根散落分析、计划、方案类 `.md`；生成物写 `.harness-runs/` 或 `tmp/`
4. 文件名小写 kebab-case；新文档登记到所在目录的 `README.md`
5. 移动 / 改名时全仓更新引用，跑 `python scripts/check_docs_layout.py` 零违规
