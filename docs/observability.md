# 可观测性指标手册

> **版本**：v1.0（2026-05-12）
> **关联**：ADR 0004（trace 粒度）/ ADR 0014（LangFuse 后端）/ ADR 0017（M4 量化退出门）
> **代码**：`app/observability/metrics.py` / `app/observability/tracing.py`

本文档定义 otc-agent 在生产期对外暴露的所有指标 + 查询方式 + 告警阈值依据。

---

## 1. 指标分层

| 层 | 工具 | 用途 |
|---|---|---|
| **L1 实时指标** | `/metrics` Prometheus endpoint（C1.5 #50）| 即时业务状态，告警依据 |
| **L2 trace 时序** | LangFuse self-hosted（C1.11）| 单条请求执行细节，故障诊断 |
| **L3 长期审计** | MySQL `node_trace` 表（C1.8 #57）| 金融审计 / 业务订单追溯 |

三层互补——L1 告诉你"出问题了"，L2 告诉你"哪个节点出问题"，L3 告诉你"半年前那笔单到底怎么处理的"。

---

## 2. 核心指标清单（L1 实时）

### 2.1 `otc_agent_node_total{node, status}` — Counter

节点级完成计数。每个 `@safe_node` 装饰的函数完成时 +1。

| label | 取值 |
|---|---|
| `node` | 节点函数名，如 `swap.intent` / `option.extract_inquiry` / `render` |
| `status` | `ok`（节点正常完成）/ `error`（节点抛异常被 safe_node 捕获）|

**衍生指标**：
- 节点错误率 = `status="error"` / 总数
- 高错误率节点 = 错误率 ≥ 1% 持续 5 分钟 → 升 P1

### 2.2 `otc_agent_intent_latency_ms{product_type, intent}` — Histogram

每意图响应延迟（毫秒）。Bucket 边界：100 / 250 / 500 / 1000 / 2000 / 5000 / 10000 / 30000 / 60000 / +Inf。

| label | 取值 |
|---|---|
| `product_type` | `swap` / `option` / `close` / `ticker` / `unknown` |
| `intent` | `place_order` / `cancel` / `confirm` / `query` 等二级意图 |

**衍生指标**：
- P50 = `histogram_quantile(0.5, otc_agent_intent_latency_ms_bucket)`
- P95 = `histogram_quantile(0.95, otc_agent_intent_latency_ms_bucket)` ← ADR 0017 监控
- P99 = `histogram_quantile(0.99, ...)`

**ADR 0017 阈值**：P95 ≤ M2 baseline × 1.5。

### 2.3 `otc_agent_fallback_total{reason}` — Counter

Fallback render 触发计数。用户看到"我没完全理解..."或"抱歉无法识别..."时 +1。

| label | 取值 | 触发条件 |
|---|---|---|
| `reason` | `cascade_fail` | 节点抛异常被 `safe_node` 兜底，`state["error"]` 非空 |
| `reason` | `zero_match` | 业务节点正常完成但 `tickers == []`（标的 0 命中）|
| `reason` | `hitl_card` | ticker 多命中触发消歧卡片，`ticker_hitl_candidates` 非空 |
| `reason` | `unknown_product_type` | 一级路由未识别出 swap/option/close 任一 |

**衍生指标**：
- Cascade fail 率 = `reason="cascade_fail"` / 总请求数
- **ADR 0017 阈值**：cascade fail 率 < 1%

### 2.4 `otc_agent_hitl_total{node}` — Counter

HITL interrupt 触发计数。节点判定无法独立完成需用户消歧时 +1。

### 2.5 `otc_agent_llm_total{model, status}` — Counter

LLM 调用计数。

| label | 取值 |
|---|---|
| `model` | `qwen3-30b-a3b` / `qwen-max-latest` / `deepseek-v4-pro` 等具体模型名 |
| `status` | `ok` / `error` / `timeout` |

**衍生指标**：
- LLM 失败率 = `status != "ok"` / 总数
- **ADR 0017 阈值**：LLM 失败率 < 10% 持续 5 分钟 触发 P1

### 2.6 `otc_agent_llm_tokens_total{model, direction, node?}` — Counter（C1.7 #56）

LLM token 累计消耗。每次 LLM 调用结束后由业务代码 emit。

| label | 取值 |
|---|---|
| `model` | 与 `otc_agent_llm_total` 同（模型名）|
| `direction` | `prompt`（输入 token）/ `completion`（输出 token）|
| `node` | 可选，调用节点名（如 `swap.intent`），便于成本按节点拆 |

**衍生指标**：
- 日 token 累计 = 该指标 24h 增量
- 模型成本 = tokens × 单价（见 §6）
- 节点成本占比 = 按 `node` 标签聚合

---

## 3. `/metrics` Endpoint

应用启动后，访问：

```bash
curl http://<app-host>:8000/metrics
```

返回 Prometheus exposition 格式（text/plain v0.0.4）。

```
# TYPE otc_agent_node_total counter
otc_agent_node_total{node="swap.intent",status="ok"} 142
otc_agent_node_total{node="swap.intent",status="error"} 3
otc_agent_node_total{node="render",status="ok"} 145
# TYPE otc_agent_fallback_total counter
otc_agent_fallback_total{reason="cascade_fail"} 3
otc_agent_fallback_total{reason="zero_match"} 7
# TYPE otc_agent_intent_latency_ms histogram
otc_agent_intent_latency_ms_bucket{product_type="swap",intent="place_order",le="100"} 0
otc_agent_intent_latency_ms_bucket{product_type="swap",intent="place_order",le="250"} 1
...
otc_agent_intent_latency_ms_sum{product_type="swap",intent="place_order"} 4523.5
otc_agent_intent_latency_ms_count{product_type="swap",intent="place_order"} 23
```

---

## 4. 接入 Prometheus（可选）

`/metrics` 是 Prometheus 兼容格式，可接客户内网 Prometheus 抓取：

```yaml
# /etc/prometheus/prometheus.yml
scrape_configs:
  - job_name: 'otc-agent'
    scrape_interval: 15s
    static_configs:
      - targets: ['otc-agent.customer.internal:8000']
```

接 Grafana 后即可可视化 P95 延迟 / cascade fail 率 / LLM 错误率等核心指标。

> 客户内网若没有 Prometheus，可临时用 cron 脚本 `curl /metrics` 写文件，或仅依赖 LangFuse 的 dashboard 看 trace。

---

## 5. 告警接入（C1.6 已实现）

`/metrics` 暴露指标后，C1.6（#55 / PR 待 merge）评估器按 ADR 0017 阈值周期评估并推企微告警群。

**ADR 0017 量化退出门告警阈值（已实现 3 个，2 个 TODO）**：

| 告警 | 触发条件 | 严重级 | 实现状态 |
|---|---|---|---|
| HTTP 5xx 暴增 | 5xx 率 ≥ 1% 持续 5 分钟 | P0 | ⚠️ 阈值代码已写，5xx 计数依赖 nginx 日志或 HTTP 中间件接入（TODO） |
| Cascade fail 持续触发 | `fallback_total{reason="cascade_fail"}` 率 ≥ 5% 持续 10 分钟 | P1 | ✅ 完整实现 |
| LLM 失败率高 | `llm_total{status!="ok"}` 率 ≥ 10% 持续 5 分钟 | P1 | ✅ 完整实现 |
| HITL 长挂起 | 单会话 HITL ≥ 30 分钟未恢复 | P2 | 🔲 TODO：需 LangFuse trace 查询能力，与本期 cron 模型不匹配 |
| P95 延迟退化 | P95 ≥ M2 baseline × 1.5 持续 10 分钟 | P1 | 🔲 TODO：需 baseline 在线持久化 |

### 5.1 部署方式

cron 每分钟拉 `/metrics` → 评估 → 推企微：

```cron
# /etc/cron.d/otc-agent-alerts
* * * * * otc-agent cd /opt/otc-agent && python scripts/run_alerts.py >> /var/log/otc-agent-alerts.log 2>&1
```

环境变量：

- `OTC_AGENT_URL`：应用 base URL（默认 `http://localhost:8000`）
- `WECHAT_ALERT_WEBHOOK_URL`：企微告警群 webhook（不配则只打印日志不推送）
- `ALERT_STATE_FILE`：状态持久化路径（默认 `/tmp/otc_agent_alert_state.json`，跨调用记忆 firing 状态防轰炸）

### 5.2 状态机设计

每个告警是状态机：未触发 → (越线持续 N 分钟) → firing → (恢复) → 未触发。**只在状态转换时发消息**：

- "fire" 信号：未触发 → firing 切换瞬间
- "recover" 信号：firing → 未触发 切换瞬间

避免连续越线时每分钟轰炸告警群。

---

## 6. 成本监控（C1.7 已实现）

C1.7（#56 / PR 待 merge）通过两件事支持成本监控：

1. **新增指标** `otc_agent_llm_tokens_total{model, direction, node?}` 见 §2.6
2. **日报脚本** `scripts/llm_cost_report.py` cron 每日跑一次

### 6.1 日报脚本流程

```cron
# /etc/cron.d/otc-agent-cost
0 8 * * * otc-agent cd /opt/otc-agent && python scripts/llm_cost_report.py >> /var/log/otc-agent-cost.log 2>&1
```

工作流：
1. 拉 `/metrics` 解析 token 数据
2. 按 model / direction / node 聚合
3. 估算成本（默认价格表 + `LLM_PRICE_PER_M_TOKENS_JSON` env 覆盖）
4. 与昨天报表对比，**日同比 > 30% 推告警**
5. 报表归档到 `LLM_COST_REPORT_DIR`（默认 `/var/lib/otc-agent/cost-reports/`）

### 6.2 默认价格表（2026-05 公开定价，USD/百万 token）

| 模型 | prompt | completion |
|---|---|---|
| `deepseek-v4-pro` | $0.50 | $1.50 |
| `deepseek-chat` | $0.14 | $0.28 |
| `qwen3-30b-a3b` | $0.30 | $0.90 |
| `qwen-max-latest` | $2.00 | $6.00 |
| `qwen-vl-max-latest` | $3.00 | $9.00 |

**现场实际计费以客户合同为准**。通过 env 覆盖：

```bash
export LLM_PRICE_PER_M_TOKENS_JSON='{"deepseek-v4-pro":{"prompt":0.4,"completion":1.2}}'
```

### 6.3 异常告警

日同比增长 > 30% 触发告警（推 `WECHAT_ALERT_WEBHOOK_URL`）。可能原因：
- 业务量增长（OK 但需关注）
- 调试漏关 trace
- Cascade fail 循环 → 同一 prompt 反复触发 LLM

### 6.4 token 数据采集（业务代码集成）

业务节点调用 LLM 完成后需 emit：

```python
from app.observability.metrics import emit_llm_tokens

# 示例：LangChain callback 中拿到 response.usage_metadata
emit_llm_tokens(
    model="deepseek-v4-pro",
    prompt_tokens=usage.prompt_tokens,
    completion_tokens=usage.completion_tokens,
    node="swap.intent",  # 可选，便于按节点拆成本
)
```

**TODO**：当前 emit 需业务代码手工调；后续可挂到 LangChain 全局 callback handler 自动采集。

---

## 7. trace 双写（C1.8 #57）

`@safe_node` 装饰器已自动写 trace 到 state（M1 起）；C1.8 任务会补完：

- 把 `state["trace"]` 写到 MySQL `node_trace` 表
- LangFuse callback handler 同时写 LangFuse
- 双写互不阻塞（任一失败不影响业务）

DDL 已在 `sql/schema.sql:34`，写入路径在 `app/nodes/persist.py`（M1 占位）。

---

## 8. 故障诊断流程

| 现象 | 看哪个 |
|---|---|
| 业务方反馈"AI 总说听不懂" | `fallback_total{reason}` 拆分类别 → 定位是 cascade 还是 zero_match |
| AI 慢 | P95 latency 拆 `product_type × intent` → 看哪个意图最慢 → LangFuse 看 trace 哪个节点慢 |
| 个别 case 错 | LangFuse 按 conversation_id 查 trace |
| 半年前订单审计 | MySQL `node_trace` 表（C1.8 落地后）|

---

## 9. 性能开销

`MetricsCollector` 设计目标：单次 emit ≤ 10 μs，对 P95 延迟影响 ≤ 50 ms（远低于业务节点本身的耗时）。

实现细节：
- 内存 dict + threading.Lock，无 I/O
- Histogram bucket 计数 O(1)（线性扫 10 个 bucket）
- Prometheus render 是 O(总指标数)，仅在 `/metrics` 访问时触发

---

## 10. 相关任务

- **C1.5（#50）本任务** · 业务指标埋点
- **C1.6（#55）** · 告警接入（依赖本任务）
- **C1.7（#56）** · LLM 成本监控（依赖本任务）
- **C1.8（#57）** · trace 双写（依赖本任务）
- **D2.6** · `/health` `/ready` 健康检查端点（与 `/metrics` 并列）

---

## 关联资源

- ADR 0017 · M4 量化退出门
- `app/observability/metrics.py` 实现源码
- `app/observability/tracing.py` LangFuse 接入
- `docs/on-call-runbook.md` §3 严重等级判定（用本文档指标）
- `docs/troubleshooting-sop.md` §1 §2 §3（用本文档指标定位）
