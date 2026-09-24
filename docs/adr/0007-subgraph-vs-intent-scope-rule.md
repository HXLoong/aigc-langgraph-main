# ADR 0007 · 新业务场景的归属：独立子图 vs 现有子图新意图

- 状态：已采纳
- 日期：2026-05-10
- 作者：图灵科技 + Tony

## 决策

产品线扩张（结构化产品、雪球、收益凭证、债券等）时，用四条规则避免"主图越来越胖"或"子图越来越乱"。**任一命中 → 新建独立子图；否则归入现有子图作为新意图**：

1. 后端 API 集合与现有子图无重叠，或重叠 < 30%；
2. 有独立的"前置查询"流程（如平仓的持仓查询）；
3. 业务方在 PRD 中把它作为独立产品线介绍；
4. 意图数量预计 ≥ 4 个。

现有划分与规则自洽：互换（swap）、期权（option）、期权平仓（close，因规则 2 独立成子图）。

## 执行清单

**归入现有子图（新意图）**：

- 在 `app/subgraphs/<product>/models.py` 的 `<Product>IntentType` 加枚举值，更新本轮联合解析契约与提示词；遵循 [ADR 0031](./0031-single-model-request-per-message.md)，不得新增独立的第二次参数模型请求；
- 新增意图节点，并在子图 `graph.py` 的 `_INTENT_TO_NODE` 路由表登记（条件边由 `app/subgraphs/common.py` 的 `add_intent_dispatch` 从该表生成；未登记的意图落 `<product>_unknown` 兜底）；
- 在 `tests/fixtures/categories/` 至少补 2 条用例（`scripts/check_fixture_consistency.py` 守护）。

**新建独立子图（额外）**：

- 新建 `app/subgraphs/<name>/` 包目录（`graph.py` / `models.py` / `intent.py` / 每意图一个节点文件）；
- 在 `app/graph/state.py` 的 `ProductType` 加值，并更新一级路由（`app/nodes/route_rules.py` / `app/nodes/intent_route.py`，见 [ADR 0031](./0031-single-model-request-per-message.md)）与主图注册；
- 注意既有命名不对称：提示词目录 `app/prompts/option_close/` 对应子图目录 `app/subgraphs/close/`。

PR 模板（`.github/pull_request_template.md`）含"是否触发独立子图条件"的判定项。

## 备选方案

完全跟随业务方分类（概念变化频繁）/ 工程师独立判断（业务方看不懂）/ **四条规则触发制（已选）**：业务直觉 + 技术内聚 + 复杂度阈值，可机械执行。

## 后果

- 30% 为经验阈值，每年回顾一次；上线后超阈值却归入现有子图的，下次重构窗口拆出。
- 业务方对"产品线"分类拥有否决权（规则 3）。
