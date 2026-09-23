# ADR 0007 · 新业务场景的归属：独立子图 vs. 现有子图新意图

- 状态：已采纳
- 日期：2026-05-10
- 修订：2026-08-27 深度改写为现状口径（对照代码核查）
- 作者：图灵科技 + Tony

## 决策（规则本体，仍有效）

随着产品线扩张（结构化产品、雪球、收益凭证、债券等），需要一条规则避免"主图越来越胖"或"子图越来越乱"。**四条触发规则任一命中 → 独立子图，否则归入现有子图作为新意图**：

1. 后端 API 集合与现有子图无重叠或重叠 < 30%
2. 有独立的"前置查询"流程（如 close 的 `holding_query`）
3. 业务方在 PRD 中作为独立产品线介绍
4. 意图数量预计 ≥ 4 个

现状划分与规则自洽：swap 7 意图 / option 10 / close 7，close 因规则 2 独立成子图，option 已按 [ADR 0011](./0011-split-option-intent-and-extraction.md) 拆分 intent 与 extraction。

## 执行 checklist（按当前代码布局，2026-08-27 更新）

**归入现有子图（新意图）**：

- 意图枚举：在 `app/subgraphs/<product>/models.py` 的 `<Product>IntentType` Literal 加值（不是原文写的早期状态兼容模块——该 shim 已随 ADR 0024 删除；`app/graph/state.py` 的 `intent` 字段是裸 `str`）
- 更新 `app/prompts/<product>/intent.md` 提示词；新增对应 extract 提示词文件
- 子图加 `@safe_node` 节点函数 + **两处路由都要改**：`graph.py` 的 `_INTENT_TO_NODE` 路由表 **和** `add_conditional_edges` 的 path_map（漏一处会静默走 unknown 兜底）
- `tests/fixtures/unified_golden.jsonl`（历史 `old_typing/golden.jsonl` 已归档到 docs/archive/fixtures/） 至少 2 条 case（CI 的 `check_fixture_consistency.py` 会查）

**立独立子图**（额外）：

- 新建 `app/subgraphs/<name>/` **包目录**（`graph.py` / `models.py` / `intent.py` / 每意图一个节点文件——不是原文的单文件 `<name>.py` + `<name>_models.py`）
- 一级路由：`app/nodes/intent_route.py`（[ADR 0015](./0015-intent-route-rules-first-llm-fallback.md) 四层路由）+ 主图 `app/graph/main.py` 的 `_route_after_intent` 与节点注册（原文的 `route_product` 命名已消失）
- `app/graph/state.py` 的 `ProductType` Literal 加值
- ⚠️ 易错点：提示词目录与子图目录命名不对称的先例——`app/prompts/option_close/` 对应 `app/subgraphs/close/`（见 `app/prompts/CLAUDE.md`）

## 备选方案

- **完全跟随业务方分类**：业务概念变化频繁，不一定对应技术合理边界。
- **由工程师独立判断**：容易做出业务方看不懂的代码组织。
- **四条规则触发制（已选）**：业务直觉（3）+ 技术内聚（1、2）+ 复杂度阈值（4）合一，可机械执行。

## 实现偏离（2026-08-27 裁决落地）

- ~~"PR 模板强制 review 四条规则"无载体~~ ✅ 已创建 `.github/pull_request_template.md`（2026-08-27）：含"是否触发独立子图条件"判定项与提交检查清单。

## 后果（现状口径）

- 30% 是经验阈值，每年回顾一次；"预计 ≥ 4 个意图"是预测，上线后超阈值但归了现有子图的，下次重构窗口拆出。
- 业务方对"产品线"分类拥有否决权（条件 3）。
- ~~文档修正项：`.claude/skills/add-intent/SKILL.md` 与 `.claude/agents/subgraph-builder.md` 仍在教旧路径~~ ✅ 已修正（2026-09-22 复核：技能已改为包目录 `app/subgraphs/$1/` 布局）。
