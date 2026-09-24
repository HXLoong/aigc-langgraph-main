## 概述

<!-- 一句话说明本 PR 做了什么、为什么 -->

## 变更内容

-

## 子图归属判定（新增业务场景必填，ADR 0007）

- [ ] 本 PR 不新增业务场景（跳过本节）
- [ ] 已按四条触发规则判定（后端 API 重叠 <30% / 独立前置查询 / 业务方独立产品线 / 预计意图 ≥4）：命中任一 → 独立子图，否则归现有子图新意图，判定结论写在概述里

## 边界判定（Code vs Prompt，改动 LLM 节点 / 提示词必填；ADR 0027）

- [ ] 本 PR 不涉及 LLM 节点 / 提示词（跳过本节）
- [ ] 三问均为"否"才归 LLM，结论写进概述；归 LLM 的节点只产原文候选，最终值由 Code 归一化：
  1. 能否用正则 / 字典 / 枚举映射 / 规则表 100% 覆盖？（能 → Code）
  2. 输出是否为客户可见文本（回复 / 追问 / 确认卡片）？（是 → Code 模板）
  3. 是否涉及金额 / 数量 / 日期 / 方向 / 标的代码等交易关键字段的最终取值？（是 → Code，后端权威校验）

## 验证

<!-- 写明实际跑了哪些检查、结果如何；按轻量验证约定未运行的项（全量 pytest / 真实业务回归）也要写明 -->

## 提交检查清单

- [ ] 受影响测试通过（`USE_MYSQL_CHECKPOINTER=false REQUEST_IDEMPOTENCY=false ENABLE_LANGFUSE=false pytest <路径> -q`）；CI 全量 pytest 绿
- [ ] `ruff check app/ tests/` 零警告；`mypy app/` 无错
- [ ] 改了提示词：`prompt(<scope>)` commit；已跑对应数据集评估，PASS 率不低于上一版
- [ ] 新增节点 / 意图：子图 `_INTENT_TO_NODE` 已登记（条件边由 `add_intent_dispatch` 自动生成）；`app/node_execution/catalog.py` 已登记；categories 每意图 ≥ 2 条
- [ ] 改了 State：`app/api/turn_state.py::inputs_to_state` 与 `app/nodes/ingest.py` 的 per-turn 重置同步；改业务参数字段时同步 `app/graph/business_params.py`
- [ ] 改了告警阈值：按 ADR 0019 §5 五步同步
- [ ] 改了 `CLAUDE.md` / `.claude/**`：已跑 `python scripts/sync_agents_md.py` 并提交生成物
- [ ] 改了 `docs/`：`python scripts/check_docs_layout.py` 零违规
- [ ] 改了 `pyproject.toml` 依赖：已说明原因
- [ ] 无硬编码 secret / 业务数据字典（CLAUDE.md 红线）

## 关联

<!-- Closes #xx / ADR 编号 -->
