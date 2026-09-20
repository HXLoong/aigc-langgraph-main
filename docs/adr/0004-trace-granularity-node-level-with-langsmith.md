# ADR 0004 · Trace 颗粒度：节点级元数据入库 + LangFuse 关联完整 LLM I/O

- 状态：已采纳（trace 后台部分被 [ADR 0014](./0014-langfuse-as-harness-backend.md) 修订：LangSmith → LangFuse）
- 日期：2026-05-10
- 修订：2026-08-27 深度改写为现状口径（wayfinder map #138 / 核查 #140）
- 作者：图灵科技 + Tony

## 决策

每次 graph 调用经过 5-10 个节点，trace 颗粒度决定可观测性 vs. 存储成本的平衡。采用**节点级中粒度**落 MySQL（`node_trace` 表），完整 LLM I/O 由 **LangFuse**（ADR 0014）承载，两边职责清晰不重复：自有 SQL 跑业务统计（"swap 子图近 7 天 P95"），LangFuse 负责调试完整 prompt。

## 落地现状（2026-08-27）

**`node_trace` 写入契约字段**（写入方 `app/nodes/persist.py`）：

`id / message_id / thread_id（= conversation_id）/ node_name / step_index / input_preview / output_preview / status / error / duration_ms / created_at`

⚠️ 当前仓库没有原文引用的 `sql/init.sql`，也找不到 `CREATE TABLE node_trace` 的迁移资产；上述字段是代码期待的契约，不代表部署库一定已初始化。实测未建表时 `persist` 记录 warning 并按“不阻塞业务”策略继续，因此 SQL 统计和 SQL ↔ LangFuse 关联能力在补齐 schema 前不可用。

与原设计的差异：

- **摘要截断长度：input/output 2048、error 4096 字符**（原设计 500；加长未走 ADR 变更程序，追认/回退待裁决 [#156](https://github.com/GZTL-AI/aigc-langgraph/issues/156)。原文"查全文走 trace 后台"的分工原则不变）
- **状态枚举：`success` / `error` 二值**（原设计 OK/ERROR/SKIP，SKIP 未实现）
- **无 token 数列**：token 只在进程级 Prometheus counter（`otc_agent_llm_tokens_total`）与 harness 侧 `token_tracker.py`
- 索引 `(thread_id, created_at)` ✅（语义即原设计的 conversation_id 复合索引）
- 写库失败不阻塞业务（try/except + warning）✅
- 完整 prompt/response 不入 MySQL ✅（swap 下单提示词 ≈126K 字符）

**LangFuse 侧**：`ENABLE_LANGFUSE` 开关（`app/config.py`），`app/graph/main.py` 注入 CallbackHandler。

## 实现偏离（#156 裁决落地，2026-08-27）

| 偏离 | 现状 |
|---|---|
| ~~`trace_id` 贯穿从未实现~~ | ✅ **已实现（#156）**：routes 入口生成（ingest 兜底覆盖 eval 路径）→ state → `node_trace.trace_id` 列（含存量迁移 SQL）→ LangFuse config metadata 同源；`tests/nodes/test_trace_id.py` 覆盖 |
| ~~摘要长度擅自加长~~ | ✅ 追认（#156 裁决）：2048/4096 为现行约定，本 ADR 即变更记录 |
| ~~LangFuse 静默软依赖~~ | ✅ 已升 warning（随 #155 批次落地）：注入/拉取失败均有日志信号 |

## 备选方案

- **粗粒度（每次调用一行）**：定位不到节点级问题。
- **中粒度 + trace 后台关联（已选）**：SQL 业务统计 + 后台完整 I/O，职责分离。
- **细粒度（完整 prompt/response 入 MySQL）**：存储爆炸、查询性能差、与 trace 后台重复；仅作后台不可用时的降级选项。

## 后果（现状口径）

- SQL ↔ LangFuse 的 `trace_id` 关联字段与写入代码已就位（#156）；补齐并部署 `node_trace` schema 后，E3.4 才能从 SQL 行关联对应 LangFuse trace（按 metadata.trace_id 过滤）。
- 文档残留（LangSmith 字样）已随 #151 引用修正清理完毕。
