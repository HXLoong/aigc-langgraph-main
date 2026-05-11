# 数据库选型：MySQL 协议 + TDSQL for MySQL 生产环境

生产环境使用 **TDSQL for MySQL**（腾讯云分布式 MySQL 协议数据库），版本 `8.0.24-v24-txsq1-22.1.4-20230224`，由 `aigc/api` 工程的 `application-prod.yaml` 配置印证。这是数据库技术栈的**外部约束**，非内部偏好。我们决定：

1. 全栈使用 **MySQL 协议**：业务表 SQL、`AIOMySQLSaver` checkpointer 都按 MySQL 8.0.19+ 编写。
2. 开发与 CI 使用 **原生 MySQL（8.0.19 ≤ v < 9.6.0）**，生产部署到 **TDSQL 8.0.24**。
3. **绝对禁止使用 PostgreSQL** 或其他非 MySQL 协议数据库——生产无法部署。

**MySQL 版本上下界依据**（针对原生 MySQL 开发环境）：
- **下界 8.0.19**：`langgraph-checkpoint-mysql` 依赖此版本以上的特性。
- **上界 < 9.6.0**：MySQL 9.6 废弃了生成列中的 MD5 函数，`AIOMySQLSaver` schema 用到，会破坏初始化。

生产端 TDSQL 8.0.24 落在该上下界之内，主版本号兼容。

## Considered Options

- **PostgreSQL + LangGraph PostgreSQL checkpointer**（更主流、官方文档更全）：生产环境无 PostgreSQL，部署不可行。
- **SQLite checkpointer**：单实例性能够用但无法横向扩展，生产场景不可接受。
- **MySQL 协议 + TDSQL（已选）**：与生产基础设施兼容的唯一路径，且 8.0.24 已经在企业级生产场景大规模验证。

## Consequences

- **TDSQL SQL 兼容性是隐藏风险**：协议兼容 ≠ 100% SQL 特性兼容。`AIOMySQLSaver` 用到的生成列、JSON 函数、CTE 等特性在 TDSQL 8.0.24 上需要在每次升级 `langgraph-checkpoint-mysql` 包后做兼容性回归（建议建立独立 TDSQL 集成测试环境）。
- **开发/生产数据库不一致是已知技术债**：CI 用原生 MySQL 通过不能保证生产 TDSQL 通过。中长期方案是在 CI 链路加 TDSQL 容器或远程实例。
- **升级 langgraph 包需要谨慎**：任一次 `langgraph-checkpoint-mysql` 升级都可能引入新的 SQL 特性依赖，需先在 TDSQL 验证再升级生产。
- **数据库版本升级前必须 review**：DBA 升级 TDSQL（即使是小版本）前，需要先在测试环境跑 checkpointer setup + 业务表迁移脚本验证。
- **不能将 PostgreSQL 作为"备选"或"双跑"方案**：哪怕开发体验更好，引入会让生产部署链路复杂化，违背单一数据库栈原则。
- **早期文档曾误称为 GoldenDB**：本 ADR 的 v1 基于早期对话误述，已统一更正为 TDSQL；review 历史变更或社区讨论时如遇 "GoldenDB" 字样，理解为对 TDSQL 的旧称呼。
