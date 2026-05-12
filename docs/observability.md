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

| label | 取值 |
|---|---|
| `reason` | `cascade_fail`（节点抛异常引发）/ `zero_match`（标的 0 命中）/ `hitl_card`（多命中消歧）/ `unknown_product_type`（产品类型识别失败）|

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

## 5. 告警接入（C1.6 #55 实施细节）

`/metrics` 暴露指标后，C1.6 任务负责接告警目标到客户企微告警群。

**ADR 0017 量化退出门告警阈值**：

| 告警 | 触发条件 | 严重级 |
|---|---|---|
| HTTP 5xx 暴增 | 5xx 率 ≥ 1% 持续 5 分钟 | P0 |
| Cascade fail 持续触发 | `fallback_total{reason="cascade_fail"}` 率 ≥ 5% 持续 10 分钟 | P1 |
| LLM 失败率高 | `llm_total{status!="ok"}` 率 ≥ 10% 持续 5 分钟 | P1 |
| HITL 长挂起 | 单会话 HITL 状态 ≥ 30 分钟未恢复 | P2 |
| P95 延迟退化 | P95 ≥ M2 baseline × 1.5 持续 10 分钟 | P1 |

告警实现路径详见 C1.6 (#55) 任务。

---

## 6. 成本监控（C1.7 #56）

`otc_agent_llm_total{model,status}` 已记录每次 LLM 调用，C1.7 会补充：

- Token 累计（按 LangFuse trace 字段聚合，本地暂不记 token）
- 按 model / 按 node 拆分（用 LangFuse trace 的 input/output token 字段）
- 异常成本增长告警（日 token 增长 > 30%）

实现路径详见 C1.7 (#56) 任务。

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
