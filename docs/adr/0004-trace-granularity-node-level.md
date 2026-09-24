# ADR 0004 · Trace 颗粒度：节点级元数据入库 + LangFuse 关联完整 LLM I/O

- 状态：已采纳
- 日期：2026-05-10
- 关系：trace 后台为自托管 LangFuse（[ADR 0014](./0014-langfuse-as-harness-backend.md)）
- 作者：图灵科技 + Tony

## 决策

采用**节点级中粒度**：每个节点一行元数据写入 MySQL 表 `langgraph_node_trace`，完整 LLM 输入输出由 LangFuse 承载。两边职责不重叠——自有 SQL 做业务统计（如"互换子图近 7 天 P95"），LangFuse 负责查看完整 prompt 调试。

## 契约

- 写入方：`app/nodes/persist.py`；建表：`sql/init.sql`（与 Java 共库，`langgraph_` 前缀，见 [ADR 0009](./0009-mysql-version-and-tdsql-compatibility.md)）；应用启动只读校验表结构。
- 字段：`message_id` / `thread_id`（= conversation_id）/ `trace_id` / `node_name` / `step_index` / 输入输出摘要（2048 字符）/ 错误（4096 字符）/ `status`（success / error）/ `duration_ms`。
- `trace_id` 由请求入口生成并贯穿 State → `langgraph_node_trace` → LangFuse metadata，错例可从 SQL 行直接跳转对应 LangFuse trace。
- 完整 prompt / response 不入 MySQL；写库失败只告警，不阻塞业务。
- token 用量不入此表，由 Prometheus 指标与 `harness/token_tracker.py` 统计。

## 备选方案

- **粗粒度（每次调用一行）**：定位不到节点。
- **中粒度 + trace 后台关联（已选）**：业务统计与调试分离。
- **细粒度（完整 I/O 入 MySQL）**：存储膨胀、查询慢、与 trace 后台重复。
