# ADR 0009 · 数据库：MySQL 协议 + TDSQL for MySQL 生产环境

- 状态：已采纳（checkpointer 已接线；TDSQL 现场兼容性待首次部署实测）
- 日期：2026-05-10
- 作者：图灵科技 + Tony

## 决策

生产使用 **TDSQL for MySQL**（腾讯云 MySQL 协议分布式数据库），这是客户基础设施的外部约束：

1. 全栈使用 **MySQL 协议**：业务表与 LangGraph checkpoint（`AIOMySQLSaver`）均按 MySQL 8.0.19+ 编写。
2. 开发与 CI 使用原生 MySQL，版本范围 **8.0.19 ≤ v < 9.6.0**。
3. 业务 / checkpoint 数据栈**禁止**使用 PostgreSQL 等非 MySQL 协议数据库（LangFuse 自托管栈自带的 PostgreSQL 不在此列）。

版本边界依据（升级依赖时复核）：

- 下界 8.0.19：`langgraph-checkpoint-mysql` 3.0.0 声明的最低版本；
- 上界 < 9.6.0：MySQL 9.6 废弃生成列中的 MD5，而 checkpoint 表结构用到该特性。

## 建表口径（2026-09-18 起，与 Java 共库）

- 业务表与 checkpoint 表放入 Java 现有 MySQL 数据库，全部使用 `langgraph_` 前缀；新表使用 `utf8mb4_general_ci`，不改变 Java 现有表与服务器默认规则。
- `sql/init.sql` 是唯一初始化入口（由部署方选择数据库执行；脚本不建库、不授权）。应用启动只读校验表结构，缺表或版本不符即明确失败；不在运行期调用 `saver.setup()`。
- 固定社区 saver 3.0.0，由项目适配层覆盖表名与查询；升级依赖必须同步验证建表快照、读写与线程删除。旧库数据保留，不自动迁移。

## 备选方案

- **PostgreSQL + 官方 checkpointer**：生产无 PostgreSQL，不可部署。
- **SQLite**：无法横向扩展。
- **MySQL 协议 + TDSQL（已选）**：与生产基础设施兼容的唯一路径。

## 后果与风险

- **协议兼容 ≠ SQL 特性 100% 兼容**：TDSQL 上的首次真实验证点是"现场执行 `sql/init.sql` + 首次启动校验"，已列入部署 checklist；DBA 升级 TDSQL 或项目升级 checkpoint 依赖前，须在测试环境回归。
- CI 的 slow job 已包含 MySQL service 并运行真实数据库用例；本地开发的真实数据库用例通过 `RUN_LOCAL_MYSQL_TESTS=1` 显式开启。
- 生产 TDSQL 的确切版本待现场 `SELECT VERSION()` 实测确认落在上述区间内。
