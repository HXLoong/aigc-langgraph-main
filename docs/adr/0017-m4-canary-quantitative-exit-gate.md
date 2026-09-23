# ADR 0017 · M4 金丝雀退出门量化指标

- 状态：**已被 [ADR 0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md) 取代**（2026-09-22 里程碑口径退役；量化指标并入 0030 D3"上线观察"层，本文压缩为历史存根）
- 日期：2026-05-12
- 修订：2026-09-22 改写为存根；此前 2026-08-27 改写为现状口径
- 作者：图灵科技 + Tony

## 原决策（历史）

为"金丝雀切流走完 100% 后能否下线 Dify"定义量化退出门，避免末期扯皮：

| 层 | 指标 | 阈值 |
|---|---|---|
| 系统 | HTTP 5xx 率 | < 0.1%（7 天） |
| 系统 | Cascade fail 率（分母 = 总请求数） | < 1%（7 天） |
| 系统 | P95 回复延迟 | ≤ 基线 × 1.5 |
| 业务 | 业务方反馈"严重错例"（标的错 / 参数错 / 意图大类错） | ≤ 5 次（7 天累计） |
| 形式 | 书面同意 | 业务方负责人邮件回复 |

取值理由：服务器崩溃应近似零，万分之一留瞬时抖动容差；1% 是"用户能感知但不至于觉得 AI 坏了"的临界；chat 体验由尾部延迟决定，× 1.5 给真后端往返 + 上报 + checkpoint 写入留预算；错例阈值不取 0 以免"挑刺永不签字"。

## 为何被取代

Dify 已于 2026-09-17 退出上游地位（ADR 0024 D1），"下线 Dify"不再是待判定事项；金丝雀切流作为部署手段仍可用（`scripts/canary_status.py` / `scripts/rollback_canary.sh`），但它不再定义任何"阶段结束"。量化指标本身仍有效，已作为上线观察层写入 [ADR 0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md) D3；基线数值（原 Qwen 口径）作废，待当前模型口径重测。

## 仍有效的历史事实

- 测量口径：5xx 与 cascade 率来自 Prometheus `/metrics`（`otc_agent_http_total` / `emit_fallback(reason="cascade_fail")`，分母为总请求数）；P95 来自 `/v1/workflows/run` 出口的端到端延迟直方图，剔除节点级样本。
- `scripts/canary_status.py` 只判定切流白名单合规，不覆盖上表任何指标。
- 故障期间的定级与介入阈值由 [ADR 0019](./0019-incident-severity-thresholds.md) 定义，与本表方向相反、刻意拉开。

## 关联

- [ADR 0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md) · 取代本 ADR
- [ADR 0019](./0019-incident-severity-thresholds.md) · 故障升级阈值 / [ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) · 基线重测口径
