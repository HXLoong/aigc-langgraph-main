# ADR 0019 · 故障升级阈值（P0 / P1 / P2 量化判定）

- 状态：已采纳（阈值表与 `app/observability/alerts.py` 一致，由 CI lint 守护）
- 日期：2026-05-12
- 关系：与 [ADR 0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md) D3 上线观察层互补
- 作者：图灵科技 + Tony

## 背景

ADR 0030 D3 的上线观察层回答"是否已经稳定"；本 ADR 回答"正在出问题，多快介入"。两组阈值方向相反且刻意拉开：例如 5xx 率 < 0.1% 才算稳定，≥ 1% 持续 5 分钟才算 P0，中间是"亚健康、可观察"区间，不打扰值班。

## 决策

### 1. 自动告警（`app/observability/alerts.py`）

| name | severity | 阈值 | 持续 | 触发动作 | 测量现状 |
|---|---|---|---|---|---|
| `http_5xx_spike` | P0 | 5xx 率 ≥ 1% | 5 分钟 | 立即介入 + 评估回切 | ✅ |
| `cascade_fail_high` | P1 | fallback{cascade_fail} 率 ≥ 5% | 10 分钟 | 15 分钟介入 | ✅ 分母 = `http_total`（总请求数，与 0030 D3 口径统一） |
| `llm_failure_high` | P1 | llm_total{status≠ok} 率 ≥ 10% | 5 分钟 | 15 分钟介入 | ✅ |
| `non_canary_traffic` | P0 | is_canary=false 计数 ≥ 1 | 即时 | 立即回切 Webhook | ✅ runbook §3 已补条目，lint 校验 5/5/5 |
| `p95_latency_degraded` | P1 | P95 端到端 ≥ 25662ms（8554 × 3，`M2_BASELINE_P95_MS` 可调） | 10 分钟 | 15 分钟介入 | ✅ 端到端埋点已接线且 P95 剔除节点级样本；默认值取 DeepSeek dry-run 参考值，生产需覆盖 |

P95 基准：当前模型（[ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md)）本地 dry-run 实测 P95 8554ms（截至 2026-09-24），作为参考基线。生产启用前须按相同部署拓扑测量，并通过 `M2_BASELINE_P95_MS` 覆盖；采样口径与边界见 `docs/operations/on-call-runbook.md` §3。

### 2. 人工升级判定（与 `docs/operations/on-call-runbook.md` §3 对应）

- **P0 · 5 分钟介入**：Java 后端不可达 ≥ 3 分钟（`/ready` 持续失败）；进程崩溃且重启失败 ≥ 2 次；业务方反馈"系统完全不工作"。
- **P1 · 15 分钟介入**：P95 ≥ 基线 × 3 持续 10 分钟；LangFuse 不可达 ≥ 10 分钟（监控盲区）。
- **P2 · 24 小时响应**：单条严重错例（标的错 / 参数错 / 意图大类错）；指标偶发越线但未达持续阈值。多条同类错例视为系统性问题，升 P1。

### 3. 取值理由

- 5xx 1% / 5 分钟，与退出门 0.1% 拉开十倍：故障升级关心突发，退出门关心稳态。
- cascade 5% / 10 分钟定为 P1：降级路径给用户友好回复，不是服务崩溃。
- LLM 失败 ≥ 10% / 5 分钟：大模型是外部依赖，失败冲高通常是上游故障；10% 约为重试后仍不通的水位。图片 / Excel 链路已接入独立视觉模型，形成第二个模型依赖，按模型拆分阈值为待办，重估前沿用本阈值。
- 非白名单流量 ≥ 1 即时 P0：切流白名单外的任何流量意味着企微 Webhook 配错，单条即可造成损失。
- P95 × 3 / 10 分钟定为 P1：慢但未崩，10 分钟窗口区分抖动与卡死。
- 单条错例定为 P2：不阻塞其他流量，避免值班被告警淹没。

### 4. 与 ADR 0030 D3 上线观察层的关系

| 维度 | ADR 0030 D3（上线观察 / 退出门） | 本 ADR（故障升级） |
|---|---|---|
| 问题域 | 是否已经稳定 | 正在出问题，多快介入 |
| 阈值方向 | 越好越绿（如 5xx < 0.1%） | 越糟越红（如 5xx ≥ 1%） |
| 时间窗口 | 7 天累积 | 5-10 分钟滚动 |
| 决策方 | 项目负责人 + 业务方负责人 | 值班（P0 / P1）/ 周报（P2） |

### 5. 阈值变更程序

1. 改 `app/observability/alerts.py` 的 `THRESHOLDS`；
2. 改本 ADR §1 / §2；
3. 改 `docs/operations/on-call-runbook.md` §3 及 §8 回切演练中引用阈值的场景。

`scripts/check_alert_threshold_consistency.py`（CI fast job）校验 alerts.py、本 ADR §1 与 runbook §3 三处一致。

## 备选方案

合并进退出门（语义对立）/ 只维护代码与 runbook 不写 ADR（不够权威）/ 更严阈值（告警疲劳）/ 更松阈值（信任崩塌）。
