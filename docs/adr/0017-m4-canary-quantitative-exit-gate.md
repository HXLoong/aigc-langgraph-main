# ADR 0017 · M4 金丝雀退出门量化指标

- 状态：已采纳（阈值体系有效；**三项测量基础存在实现偏离，退出门当前不可自动校验**，见对应小节）
- 日期：2026-05-12
- 起源：grill-with-docs（docs/m3-m4-roadmap.md F4.7）
- 修订：2026-08-27 深度改写为现状口径（wayfinder map #138 / 核查 #143）
- 作者：图灵科技 + Tony

## 上下文

M4 金丝雀走完 100% 切流后，需要明确退出门判定"是否可以下线 Dify"。路线图原文"稳定 7 天无 P0 + 业务方书面同意"两处模糊（P0 无量化、书面形式不明），不补齐会在金丝雀末期反复扯皮。

## 决策：量化退出门

### 系统层指标（自动测量）

| 指标 | 阈值 | 测量方式（现状口径） | 测量现状 |
|---|---|---|---|
| HTTP 5xx 率 | < 0.1%（7 天） | Prometheus `/metrics` 的 `otc_agent_http_total`（HTTPMetricsMiddleware，含 unhandled exception 补报；**非原文的 LangFuse**） | ✅ 埋点在；Grafana 无 5xx panel |
| Cascade fail 率 | < 1%（7 天） | `emit_fallback(reason="cascade_fail")` 计数 / **总请求数** | ⚠️ 代码实际分母是 `node_total`（节点执行数 ≈ 请求数 ×6-8），阈值被实际放宽近一个数量级，且与 [ADR 0019](./0019-incident-severity-thresholds.md) 同名指标口径不一致——裁决 [#157](https://github.com/GZTL-AI/aigc-langgraph/issues/157) |
| P95 回复延迟 | ≤ M2 baseline × 1.5 | 端到端延迟直方图 P95 | ⚠️ **端到端 P95 从未被采集**：`emit_intent_latency` 无生产调用方，`otc_agent_intent_latency_ms` 实际只装了单节点耗时（label 恒 unknown）——**该退出门项目前不可测**，F4 前置阻塞（[#157](https://github.com/GZTL-AI/aigc-langgraph/issues/157)） |

### 业务层指标（业务方人工标注）

| 指标 | 阈值 | 测量方式 |
|---|---|---|
| 业务方反馈"严重错例" | ≤ 5 次（7 天累计） | 企微群/周报反馈的标的错、参数错、意图大类错（非"AI 不够聪明"类主观感受——标准须在 E3.6 培训时与业务方对齐） |

### 书面同意形式

**邮件回复**："收到 LangGraph 上线运行 7 天报告，同意 Dify 工作流下线" + 业务方负责人姓名/职位。不接受口头/电话/微信（无法追溯）；不走合同 amendment（太重）。

## 阈值取值理由（保留原论证）

- **5xx < 0.1%**：服务器崩溃应近似零；万分之一给瞬时抖动留容差，再松即带病上线。
- **cascade < 1%**：M2 总失败 7.5% 大多是意图偏差非 cascade；1% 是"用户能感知但不至于觉得 AI 坏了"的临界值。
- **P95 而非平均**：chat UX 由尾部延迟决定，金融业务方耐心有限。
- **× 1.5**：给真后端网络往返 + LangFuse 上报 + checkpoint 写入留预算；2 倍即放任退化。
- **错例 ≤ 5 次而非 0**：7 天约 700-1400 条流量，5 次 ≈ 0.5%；0 次会造成"业务方挑刺永不签字"的扯皮。

⚠️ **baseline 注记**：上表 "M2 baseline" 为 Qwen 口径，已被 [ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) 作废。**Amendment 触发条件**：DeepSeek-V4-pro 上重跑 `scripts/langfuse_eval.py` + 重测 P95 后，回填本表数值。

## 替代方案

- **只看业务方主观满意**：会被无限期拖延签字。
- **全零阈值**：陷入"修最后一个 bug 出新 bug"死循环。
- **更松阈值**：金融场景容错低，信任崩塌。

## 后果（现状口径）

### 正面

- 团队与业务方在金丝雀末期有共同判定语言；阶段 5 起点清晰。

### 负面 / 当前缺口（原文预警"金丝雀末期才发现监控不到位"**已实际发生**，裁决 [#157](https://github.com/GZTL-AI/aigc-langgraph/issues/157)）

- "退出门可被监控仪表盘自动校验"**当前不成立**：Grafana 模板无 5xx panel、无 cascade 比率 panel、P95 panel 是节点级；`scripts/metrics_snapshot.py` 明确跳过 histogram、无 HTTP 段——运维 CLI 读不出 5xx 与 P95 两项。
- `scripts/canary_status.py` 只判定切流白名单合规（`otc_agent_canary_traffic_total`），**不覆盖本 ADR 任何指标**，不要当退出门校验工具混用。

### 后续行动（更新）

1. 端到端延迟埋点接线（`emit_intent_latency` 挂到请求出口）——F4 启动前置
2. cascade 分母统一（与 0019 一并，二选一：改代码对齐"总请求数"或改两份 ADR 追认 `node_total` 并重定阈值）
3. Grafana 补 5xx / cascade 比率 / 端到端 P95 三个 panel + 7 天退出门视图；metrics_snapshot 补 HTTP 与 histogram 段
4. E3.6 业务方培训含"严重错例标准对齐"议题（不变）
5. F4.7 报告模板按本 ADR 阈值表输出——**尚未落地**（无对应文件）

## 关联

- `docs/m3-m4-roadmap.md` 阶段 4（阈值表与本 ADR 逐行一致 ✅）
- [ADR 0016](./0016-m3-scope-engineering-loop-not-shadow.md) · 金丝雀是工程闭环的延续
- [ADR 0019](./0019-incident-severity-thresholds.md) · 故障升级阈值（互补：本 ADR 管"结束判定"，0019 管"期间定级"）
- [ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) · baseline 重建
