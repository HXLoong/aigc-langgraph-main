# ADR 0016 · M3 范围重定义：工程联调闭环（非 shadow 双跑）

- 状态：**已被 [ADR 0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md) 取代**（2026-09-22 里程碑口径退役；本文压缩为历史存根）
- 日期：2026-05-11
- 修订：2026-09-22 改写为存根；此前 2026-08-27 改写为现状口径
- 作者：图灵科技 + Tony

## 原决策（历史）

早期计划把迁移的第三阶段定义为"Shadow 双跑"：LangGraph 与 Dify 对同一流量各跑一遍，以 diff 率（主要意图 < 5%、下单 / 平仓 < 1%）作退出门。本 ADR 把它改为"工程联调闭环"：mock 跑通 → 真后端联调 → 数据集回归与错例修复；Shadow 双跑降为切流期的第二意见，不再是合格性判定。

三条论点：

1. **Dify 不是 ground truth**——迁移动机正是 Dify 的标的不准、参数 bug、评估缺失；拿 Dify 比 diff 会冤枉 LangGraph 同时美化 Dify。
2. **实际目标是工程上线**，链路里没有 Dify。
3. **退出门应基于数据集 PASS 率**：ground truth = 数据集 `expected`。

## 为何被取代

M3.1 / M3.2 / M3.3 分段与对应的任务码、issue 已完成或退役；"用数据集 PASS 率作门"的论点被 [ADR 0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md) D1-2 / D3 吸收为统一评测门，不再依附于里程碑。Shadow 双跑（`scripts/shadow_compare.py`）保留为可选对照工具，不进任何门。

## 仍有效的历史事实

- httpx 全部 `trust_env=False`（避免系统代理拦截）仍是现行约定，内网网关走独立配置。
- `tests/conftest.py` 的全局 ticker 白名单曾被引入又回退——"禁止在 conftest 用 autouse 绕过真实业务路径"由此成为根纪律（`tests/CLAUDE.md`）。

## 关联

- [ADR 0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md) · 取代本 ADR
- [ADR 0000](./0000-migrate-from-dify-to-langgraph.md) · 迁移动机 / [ADR 0002](./0002-comprehensive-runtime-harness.md) · Harness
