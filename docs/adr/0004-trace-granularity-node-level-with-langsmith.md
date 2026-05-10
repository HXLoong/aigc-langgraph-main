# Trace 颗粒度：节点级元数据入库 + LangSmith 关联完整 LLM I/O

> **Status update (2026-05-10)**：本 ADR 中 **LangSmith 的部分被 ADR 0014 取代**——trace 后台改为 LangFuse self-hosted（金融数据合规要求）。
> 仍然有效：节点级中粒度落 MySQL `node_trace` 表 + trace_id 贯穿 + 摘要长度 500 字符约定。
> 阅读时把下文出现的"LangSmith"读作"LangFuse"即可，结构性约束不变。

每次 graph 调用经过 5-10 个节点，trace 颗粒度直接决定可观测性 vs. 存储成本的平衡。我们决定采用 **节点级中粒度** 落 MySQL（`node_trace` 表），同时通过共享 `trace_id` 关联 LangSmith 中的完整 LLM 请求/响应。

**MySQL `node_trace` 字段**：节点名、输入摘要（前 500 字符截断）、输出摘要（前 500 字符截断）、延迟、LLM token 数、状态（OK / ERROR / SKIP）、trace_id、conversation_id、created_at。

**LangSmith**：完整 prompt + 完整 response + 中间 tool call 全部入库，按 `ENABLE_LANGSMITH` 开关启用，生产环境必开。

## Considered Options

- **粗粒度（每次 graph 调用一行）**：定位不到节点级问题，放弃。
- **中粒度 + LangSmith 关联（已选）**：自有 SQL 能跑业务统计（"swap 子图近 7 天 P95"、"close 子图错误率 Top10"），LangSmith 负责调试完整 prompt，两边职责清晰不重复。
- **细粒度（节点级 + 完整 prompt/response 入 MySQL）**：存储爆炸（swap 下单提示词 133K 字符），查询性能差，且功能与 LangSmith 重复。仅在 LangSmith 不可用时考虑降级。

## Consequences

- 必须在 graph 入口生成 `trace_id`（推荐 `uuid7` 或基于时间的 ULID）并贯穿所有节点，否则 SQL ↔ LangSmith 关联失效。
- LangSmith 是运行时硬依赖（生产环境）。如果 LangSmith 不可用或被裁撤，需要新增 ADR 评估是否升级到细粒度自闭环。
- "前 500 字符截断"是约定俗成的摘要长度，不能为了排查个别 case 临时加长——查全文走 LangSmith。
- `node_trace` 表必须有 `(conversation_id, created_at)` 复合索引，否则会话级回放查询会变慢。
