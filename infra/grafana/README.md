# otc-agent LangGraph Grafana 面板

灰度上线与上线观察期间，开发 / 业务方 / on-call 共用的可视化观测台。
与 `scripts/metrics_snapshot.py`（CLI 文本快照）互补——CLI 适合定时巡检 / SSH 终端，Grafana 适合大屏值班 / 历史趋势对比。

## 内容

```
infra/grafana/
└── dashboards/
    └── otc-agent-overview.json   ← 18 个指标 panel（按 5 段分行）
```

## 5 段结构（与 metrics_snapshot.py 对齐）

| 行 | 段 | Panel | 用途 |
|---|---|---|---|
| 1 | 节点级 | 错误率时序 / P95 延迟 / TOP 错误节点表 | 定位是哪个节点崩了 |
| 2 | 业务指标 | Fallback / LLM 失败率 stat + token 速率 + Fallback reason 分布 | 成本观测 + 业务路径健康 |
| 3 | 金丝雀 | is_canary=true/false 计数 + 占比 | 切流核心面板 |
| 4 | 健康检查 | 4 个上游 1h 统计表 + fail 趋势 | 上游联通性（`/ready` + health_probes） |
| 5 | 上线观察退出门 | HTTP 5xx、Cascade fail、端到端 P95，各有 5m / 7d 视图 | 请求级质量与 7 天滚动门槛 |

退出门视图的 HTTP 5xx、cascade 比率分母均为 HTTP 请求数，阈值分别为 0.1%、1%。
端到端 P95 只使用无 `node` 标签的直方图，原节点 P95 面板只使用 `node` 非空的样本。
没有请求样本时不显示为零错误率通过。5m 面板用于短期趋势，7d 面板对应 ADR 0030 的滚动窗口。

仪表盘顶部 `baseline_p95_ms` 必须填写当前环境的实测值；初始 `0` 表示未配置，不绘制
P95 退出门线。配置后显示 `实测基线 × 1.5`，不再用历史 Qwen 的 4200ms 代替本次基线。
基线测量与回填由 #233 跟踪，添加面板不代表基线已测量或七天观察已完成。

CLI 快照新增 HTTP 累计请求/5xx/cascade 段，保留并渲染 histogram 的 `_sum`、`_count`、
`_bucket`（JSON 的 `counters` 键保持兼容）。单次累计快照不等于滚动错误率，不能独立作为
七天退出门的验收证据。

## Import 步骤

### 前提

服务已暴露 Prometheus exposition 格式的 metrics：
- `GET http://<host>:8000/metrics`

Prometheus 已在抓取，scrape config 示例：
```yaml
scrape_configs:
  - job_name: otc-agent
    metrics_path: /metrics
    scrape_interval: 15s
    static_configs:
      - targets: ['otc-agent-host:8000']
```

### 步骤

1. 登录 Grafana（一般 `http://<grafana-host>:3000`，admin 账号）
2. Dashboards → New → **Import**
3. **Upload JSON file** 选 `infra/grafana/dashboards/otc-agent-overview.json`
   - 或者粘贴文件内容到文本框
4. 数据源选择已注册的 Prometheus 数据源（变量 `${DS_PROMETHEUS}`）
5. 点击 **Import**

UID 是 `otc-agent-langgraph-overview`，后续如果改 JSON 重新 import 会自动覆盖同一 dashboard（不会创建副本）。

## 切流当天的"必看 panel"

如果只能看一个面板：**第 3 行的 `is_canary=false · 1h ❌`** —— 任何非零值都意味着有非白名单群的 `agentUrl` 被误切到了 LangGraph，对应 `alerts.py: non_canary_traffic` P0 即时告警。

第二必看：**第 4 行 `上游探测 1h 统计` 表**的 `fail` 列。`java_backend` fail > 0 → 真后端联通断了，立即降级回切。

## 与 CLI 工具的分工

| 场景 | 用哪个 |
|---|---|
| 值班大屏 / 团队同时看 | Grafana 本面板 |
| SSH 上去快速一查 | `python scripts/metrics_snapshot.py` |
| 灰度切流判定（合规 vs 误切） | `python scripts/canary_status.py`（带退出码，可用于 on-call 脚本判定） |
| 历史趋势比对（昨天 vs 今天 vs 上周） | Grafana time picker |

## 维护建议

- 加新指标时同步更新此 JSON（grep `otc_agent_*` 与 `app/observability/metrics.py` 保持一致）
- 阈值（红/黄）维持与 `app/observability/alerts.py` 同步——alerts 是机器判定，Grafana 是人眼判定，**口径不能不一致**：
  - LLM 错误率 ≥ 10% → 红（alerts P1）
  - Cascade fail 比率 ≥ 5% → 红（alerts `cascade_fail_high` P1）；节点错误率面板只作人眼参考，无对应告警
  - is_canary=false ≥ 1 → 红（alerts P0 即时）
- 默认时间窗 `now-6h`，refresh 30s。值班大屏建议改成 `now-1h` + refresh 15s。

## 关联

- ADR 0019：故障升级阈值；ADR 0030 D3：上线观察退出门
- `app/observability/canary.py`：金丝雀切流（`CANARY_ROOM_IDS`）
- `app/observability/health_probes.py`：`/ready` 上游探测
- `app/observability/metrics.py`：指标定义
- `app/observability/alerts.py`：告警阈值
- `scripts/metrics_snapshot.py`：CLI 全指标快照
- `scripts/canary_status.py`：金丝雀状态检查（带退出码）
