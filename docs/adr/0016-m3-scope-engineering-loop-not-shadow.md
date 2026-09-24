# ADR 0016 · 迁移验收改为工程联调闭环，而非 Shadow 双跑（历史存根）

- 状态：**已被 [ADR 0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md) 取代**（2026-09-22 里程碑口径退役）
- 日期：2026-05-11
- 作者：图灵科技 + Tony

## 原决策

早期计划以"LangGraph 与 Dify 对同一流量双跑、比 diff 率"作为迁移验收门。本 ADR 改为"工程联调闭环 + 数据集 PASS 率"：

1. **Dify 不是标准答案**——迁移动机恰恰是 Dify 的标的不准、参数 bug、缺少评估；
2. **目标是工程上线**，生产链路中已没有 Dify；
3. **验收应基于数据集**，标准答案 = 数据集的 `expected`。

## 为何被取代

里程碑分段已完成或退役；"以数据集 PASS 率作门"的论点被 ADR 0030 D3 统一评测门吸收。Shadow 对照工具（`scripts/shadow_compare.py`）保留为可选对照，不进任何门。

## 仍有效的事实

- HTTP 客户端统一 `trust_env=False`（避免系统代理拦截）。
- 禁止在测试 `conftest.py` 用 autouse fixture 全局绕过真实业务路径（曾出现过全局标的白名单，已回退）。
