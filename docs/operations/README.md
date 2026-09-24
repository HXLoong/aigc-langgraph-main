# 运维 · 上线后的监控、值班与生产排障

本目录回答"系统上线后怎么看状态、出事了怎么处理"。部署前的准备见 [../deploy/](../deploy/README.md)，
开发期本地报错见 [../development/troubleshooting.md](../development/troubleshooting.md)。

| 文档 | 用途 | 何时读 |
|---|---|---|
| [observability.md](./observability.md) | LangFuse / Prometheus `/metrics` / 告警接线，三层可观测 | 接监控、配告警、看指标 |
| [on-call-runbook.md](./on-call-runbook.md) | 值班手册：严重等级、回切 / 降级决策、故障 playbook | **值班**、需要快速决策时 |
| [troubleshooting-sop.md](./troubleshooting-sop.md) | 生产故障根因诊断与修复手册 | 止血后定位**根因** |

严重等级阈值以 [ADR 0019](../adr/0019-incident-severity-thresholds.md) 为准，`scripts/check_alert_threshold_consistency.py`
守护 `alerts.py` ↔ ADR 0019 ↔ runbook 三处一致。
