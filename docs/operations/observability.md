# 可观测性

> 关联：ADR 0004（trace 颗粒度）/ ADR 0014（LangFuse 自托管）/ ADR 0019（故障升级阈值）/ ADR 0030 D3（上线观察）

## 1. 三层可观测

| 层 | 载体 | 用途 |
|---|---|---|
| 实时指标 | `/metrics`（Prometheus 兼容，`app/observability/metrics.py`） | 业务状态与告警依据 |
| 请求 trace | 自托管 LangFuse（`app/observability/tracing.py`） | 单条请求的节点执行细节与 LLM I/O |
| 长期审计 | MySQL `langgraph_node_trace` 表（`app/nodes/persist.py`） | 金融审计、订单追溯 |

三层通过 `trace_id` 关联：请求入口生成，写入 State、`langgraph_node_trace.trace_id` 与 LangFuse metadata。

## 2. 指标

| 指标 | 类型 | 标签 | 说明 |
|---|---|---|---|
| `otc_agent_http_total` | Counter | `path`, `status_class` | HTTP 响应计数；5xx 率与 cascade 率的分母为总请求数 |
| `otc_agent_intent_latency_ms` | Histogram | `product_type`, `intent` | `/v1/workflows/run` 端到端延迟，P95 取此直方图 |
| `otc_agent_node_total` | Counter | `node`, `status` | 节点执行结果（`ok` / `error` / `retry`） |
| `otc_agent_node_latency_ms` | Histogram | `node` | 节点级延迟（与端到端延迟分开统计） |
| `otc_agent_fallback_total` | Counter | `reason` | 降级回复原因，如 `cascade_fail`、`backend_unreachable`、`*_backend_missing_context`、`*_backend_empty_result` |
| `otc_agent_llm_total` | Counter | `model`, `status` | LLM 调用结果（由 callback 自动采集，`app/observability/llm_metrics.py`） |
| `otc_agent_llm_tokens_total` | Counter | `model`, `direction` | token 消耗（prompt / completion），用于成本统计 |
| `otc_agent_llm_cache_tokens_total` / `otc_agent_llm_cache_usage_total` | Counter | `model` | 模型侧缓存命中统计 |
| `otc_agent_canary_traffic_total` | Counter | `is_canary` | 灰度白名单内外的请求计数 |
| `otc_agent_dry_run_intercept_total` | Counter | — | `DRY_RUN_BACKEND` 模式下被拦截的写类调用 |
| `otc_agent_health_check_total` | Counter | `target`, `status` | `/ready` 上游探测结果 |
| `otc_agent_option_backend_missing_context_total` / `otc_agent_option_backend_empty_result_total` | Counter | — | 期权后端缺上下文 / 空结果 |

指标为进程内存储，进程重启清零；趋势数据以 LangFuse 与 Prometheus 抓取为准。指标模块自身故障不影响业务主流程。

## 3. 告警

阈值定义在 `app/observability/alerts.py` 的 `THRESHOLDS`，与 ADR 0019 §1、`docs/operations/on-call-runbook.md` §3 由 CI 校验一致。

| 告警 | 级别 | 条件 |
|---|---|---|
| `http_5xx_spike` | P0 | 5xx 率 ≥ 1%，持续 5 分钟 |
| `non_canary_traffic` | P0 | 灰度白名单外出现任何流量 |
| `cascade_fail_high` | P1 | cascade 降级率 ≥ 5%，持续 10 分钟 |
| `llm_failure_high` | P1 | LLM 失败率 ≥ 10%，持续 5 分钟 |
| `p95_latency_degraded` | P1 | 端到端 P95 ≥ 基线 × 3，持续 10 分钟（基线由 `M2_BASELINE_P95_MS` 配置） |

`scripts/run_alerts.py` 周期评估并推送企微告警群；告警状态持久化在本地状态文件，用于"持续 N 分钟"判定与去重。

## 4. LangFuse trace

- 只允许自托管部署（`infra/langfuse/`，ADR 0014）；`ENABLE_LANGFUSE` 控制开关，地址取 `LANGFUSE_BASE_URL`。
- 请求入口统一注入 CallbackHandler，子图自然继承；metadata 携带 `trace_id`、`langfuse_session_id`（= conversation_id）、`langfuse_user_id` 与环境标签。
- 节点在 LangFuse 中的中文展示名由 `app/observability/node_labels.py` 统一维护。
- 字段脱敏由 `app/observability/privacy.py` 提供，默认关闭；开启后只作用于 LangFuse 与日志，不改业务 State。

## 5. 结构化日志

`app/observability/logs.py` 用 structlog 接管标准 logging：`LOG_FORMAT=json` 时每条日志一行 JSON，自动带 `trace_id` / `conversation_id` / `message_id`。业务代码使用 `logging.getLogger(__name__)`，不在模块内自行配置 handler。

## 6. 审计表 `langgraph_node_trace`

每个节点一行元数据：`message_id`、`thread_id`、`trace_id`、`node_name`、`step_index`、输入输出摘要、`status`、`duration_ms`。完整 prompt / response 不入库，按 `trace_id` 到 LangFuse 查看。写库失败只告警，不阻塞业务。

## 7. 常用排查入口

| 场景 | 去哪看 |
|---|---|
| 当前是否有故障 | `/metrics` + 告警群；`python scripts/metrics_snapshot.py` 输出快照 |
| 某条消息为什么这样回复 | LangFuse 按 `trace_id` 或会话过滤 |
| 历史订单追溯 | `langgraph_node_trace` 按 `message_id` / `trace_id` 查询 |
| 灰度状态 | `python scripts/canary_status.py` |

故障定级与处置见 `docs/operations/on-call-runbook.md`，根因诊断见 `docs/operations/troubleshooting-sop.md`。
