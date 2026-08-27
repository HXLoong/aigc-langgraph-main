# ADR 0004 · Trace 颗粒度：节点级元数据入库 + LangFuse 关联完整 LLM I/O

- 状态：已采纳（trace 后台部分被 [ADR 0014](./0014-langfuse-as-harness-backend.md) 修订：LangSmith → LangFuse）
- 日期：2026-05-10
- 修订：2026-08-27 深度改写为现状口径（wayfinder map #138 / 核查 #140）
- 作者：图灵科技 + Tony

## 决策

每次 graph 调用经过 5-10 个节点，trace 颗粒度决定可观测性 vs. 存储成本的平衡。采用**节点级中粒度**落 MySQL（`node_trace` 表），完整 LLM I/O 由 **LangFuse**（ADR 0014）承载，两边职责清晰不重复：自有 SQL 跑业务统计（"swap 子图近 7 天 P95"），LangFuse 负责调试完整 prompt。

## 落地现状（2026-08-27）

**`node_trace` 实际字段**（`sql/schema.sql`，写入方 `app/nodes/persist.py`）：

`id / message_id / thread_id（= conversation_id）/ node_name / step_index / input_preview / output_preview / status / error / duration_ms / created_at`

与原设计的差异：

- **摘要截断长度：input/output 2048、error 4096 字符**（原设计 500；加长未走 ADR 变更程序，追认/回退待裁决 [#156](https://github.com/GZTL-AI/aigc-langgraph/issues/156)。原文"查全文走 trace 后台"的分工原则不变）
- **状态枚举：`success` / `error` 二值**（原设计 OK/ERROR/SKIP，SKIP 未实现）
- **无 token 数列**：token 只在进程级 Prometheus counter（`otc_agent_llm_tokens_total`）与 harness 侧 `token_tracker.py`
- 索引 `(thread_id, created_at)` ✅（语义即原设计的 conversation_id 复合索引）
- 写库失败不阻塞业务（try/except + warning）✅
- 完整 prompt/response 不入 MySQL ✅（swap 下单提示词 ≈126K 字符）

**LangFuse 侧**：`ENABLE_LANGFUSE` 开关（`app/config.py`），`app/graph/main.py` 注入 CallbackHandler。

## 实现偏离（裁决见 [#156](https://github.com/GZTL-AI/aigc-langgraph/issues/156)）

| 偏离 | 现状 |
|---|---|
| **`trace_id` 贯穿从未实现** | 原决策要求 graph 入口生成 uuid7/ULID 并贯穿所有节点作为 SQL↔LangFuse 关联键；全仓零命中、表无该列。现状只能靠 `thread_id + message_id` 粗关联，定位不到单次 graph 调用 |
| **摘要长度擅自加长** | 500 → 2048/4096，且原文明文禁止"为排查临时加长"；连带 [ADR 0013](./0013-load-dynamic-inference-prompt-fragment.md) 的"500 字符"引用失效 |
| **LangFuse 从"生产硬依赖"降级为静默软依赖** | 原决策"不可用需新增 ADR 评估"；实际 `_attach_langfuse_callbacks` 捕获所有异常静默返回未包装图——生产 LangFuse 挂掉无任何信号 |

## 备选方案

- **粗粒度（每次调用一行）**：定位不到节点级问题。
- **中粒度 + trace 后台关联（已选）**：SQL 业务统计 + 后台完整 I/O，职责分离。
- **细粒度（完整 prompt/response 入 MySQL）**：存储爆炸、查询性能差、与 trace 后台重复；仅作后台不可用时的降级选项。

## 后果（现状口径）

- SQL ↔ LangFuse 的调用级关联依赖 trace_id 补实现（[#156](https://github.com/GZTL-AI/aigc-langgraph/issues/156)），在此之前 E3.4 错例追溯只能按会话 + message 粗定位。
- 文档残留：`.claude/rules/langgraph-patterns.md` 等 5 处仍写 `ENABLE_LANGSMITH`/LangSmith，随外部引用修正票清理。
