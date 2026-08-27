# ADR 0009 · 数据库选型：MySQL 协议 + TDSQL for MySQL 生产环境

- 状态：已采纳（checkpointer 接线部分未落地，见"实现偏离"）
- 日期：2026-05-10
- 修订：2026-08-27 深度改写为现状口径（wayfinder map #138 / 核查 #141）
- 作者：图灵科技 + Tony

## 决策

生产环境使用 **TDSQL for MySQL**（腾讯云分布式 MySQL 协议数据库）。这是数据库技术栈的**外部约束**，非内部偏好：

1. 全栈使用 **MySQL 协议**：业务表 SQL、`AIOMySQLSaver` checkpointer 都按 MySQL 8.0.19+ 编写。
2. 开发用**原生 MySQL（8.0.19 ≤ v < 9.6.0）**：本地 `docker-compose.yml` 用 `mysql:8.0.36`。
3. **禁止 PostgreSQL** 或其他非 MySQL 协议数据库——**作用域限业务/checkpoint 数据栈**；`infra/langfuse/` 自托管观测栈自带 `postgres:16` 不在此列（[ADR 0014](./0014-langfuse-as-harness-backend.md) 边界）。

**版本上下界依据**（证据锚点，升包时机械复核）：

- **下界 8.0.19**：`langgraph-checkpoint-mysql` 3.0.0 METADATA 明示 "features that require MySQL >= 8.0.19 or MariaDB >= 10.7.1"（`pyproject.toml` 约束 `>=3.0.0`，lock 解析 3.0.0）。
- **上界 < 9.6.0**：MySQL 9.6 废弃生成列中的 MD5，`AIOMySQLSaver` schema 用到（`base.py:103` `ADD COLUMN checkpoint_ns_hash BINARY(16) AS (UNHEX(MD5(checkpoint_ns))) STORED`）。

**生产 TDSQL 版本口径修正**：原文的 `8.0.24-v24-txsq1-22.1.4-20230224` **无法由 `aigc/api` 的 `application-prod.yaml` 印证**（该 yaml 只有 jdbc 地址 + `tdsql_test_2025` 密码默认值，全仓无版本号字样）——版本号来源应视为运维口头确认，落在上下界内的结论待现场 `SELECT VERSION()` 实测回填。⚠️ 顺带记录疑点：该 prod profile 连的库名是 `goats_ai_trading_dev`（prod 指向 dev 库，Java 侧配置问题，不属本 ADR 范围，建议单独反馈）。

## 实现偏离（已随 [ADR 0021](./0021-text-confirm-replaces-interrupt.md) / #153 修复）

~~**AIOMySQLSaver checkpointer 从未接线（严重）**~~ ✅ 2026-08-27 已接线（`use_mysql_checkpointer` 配置，生产 fail-fast，`tests/test_checkpointer_wiring.py`）。原偏离记录：`app/checkpointer/factory.py` 实现完整但全仓无调用点；`app/main.py` 以 `checkpointer=None` 编译主图（注释停留在"M1 阶段不强制"）；测试只用 InMemorySaver。后果：

- 本 ADR 声称在管理的风险（TDSQL 生成列/JSON 函数兼容性、`.setup()` 建表验证、升包回归）**从未被真实暴露**——checkpoint 库实际未启用；
- 多轮对话状态没有持久化（跨进程/重启即失忆）；
- 连带 [ADR 0006](./0006-hitl-interrupt-boundary.md)（HITL interrupt 依赖 checkpointer）落空。

"在 TDSQL 上跑通 `.setup()`"验收已列入现场部署 checklist（ADR 0021 §2）。

## 备选方案

- **PostgreSQL + 官方 checkpointer**：生产无 PostgreSQL，不可部署。
- **SQLite checkpointer**：无法横向扩展。
- **MySQL 协议 + TDSQL（已选）**：与生产基础设施兼容的唯一路径。

## 后果（现状口径）

- **TDSQL SQL 兼容性是隐藏风险**：协议兼容 ≠ 100% SQL 特性兼容；每次升级 `langgraph-checkpoint-mysql` 后需在 TDSQL 上回归（前提是 checkpointer 先接线）。
- **CI 现状**：`.github/workflows/ci.yml` **无 MySQL service**，且 2026-05-12 起仅保留 `workflow_dispatch` 手动触发——原文"CI 用原生 MySQL"不成立。技术债的下一步应先恢复 CI 的 MySQL service，再谈 TDSQL 容器。
- **checkpoint URI**：`AIOMySQLSaver.parse_conn_string` 实际忽略 scheme（`mysql://` 与 `mysql+aiomysql://` 均可连），`app/config.py` 注释的格式约束比实际严，无功能风险。
- **数据库版本升级前必须 review**：DBA 升级 TDSQL 前先在测试环境跑 checkpointer setup + 业务表迁移验证。
- 早期文档曾误称 "GoldenDB"，统一理解为 TDSQL 旧称。
