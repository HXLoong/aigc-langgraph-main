# ADR 0013 · 加载后端动态 prompt 片段（swap_instrument_inference_prompt）

- 状态：已采纳（主链路已落地；两处 trace 护栏未实现，见"实现偏离"）
- 日期：2026-05-10
- 修订：2026-08-27 深度改写为现状口径（wayfinder map #138 / 核查 #141）
- 作者：图灵科技 + Tony

## 决策

Dify 工作流通过后端接口拉取一段**运维可热改的 prompt 片段**（全局配置 `swap_instrument_inference_prompt`）注入标的推断 LLM 节点。LangGraph 若只用静态 `infer_code.md`，业务方/运维临时调整推断规则（加新约束、新字典）就必须发版。决定补上：ticker 推断前先拉取动态片段，与静态文件拼接后喂给 LLM。

## 落地现状（2026-08-27，原两条行内 Status update 已吸收）

**Endpoint**：`GET /admin-api/counterparty/info/instrument-inference-prompt`，返回 `CommonResult<String>`（包裹纯字符串）。Java 侧 `CounterpartyInfoController.java:32`（`@GetMapping`）/ `:36`（方法签名）——原修订注的 `:33` 是行号偏移，`docs/api-contracts/java-backend.md` 同处偏移待一并修正。`/admin-api` 前缀由 `WebProperties.adminApi` 框架级注入。

**实现链路**：

1. 客户端：`app/tools/ticker_client.py` 的 `TickerClient.get_inference_prompt()`（普通 GET → `result.data` 为 `str`；ADR 0001 D2 三 Protocol 拆分后的归属，原文的 `OtcBackendClient` 已不存在）。
2. 缓存：`app/subgraphs/ticker/tools.py` 的 `_get_dynamic_prompt_cached()` —— **模块级单 key 缓存 + 300s 绝对过期 + 进程重启清空**（非 `functools.lru_cache`；`infer_code` 工具入口调用）。多副本部署时各副本缓存独立，热改后最长 5 分钟不一致，可接受。
3. 拼接：静态 `app/prompts/ticker/infer_code.md` 作框架（输出格式、调用规范），动态片段以 `## 后端动态片段（实时拼接）` 追加到 system 末尾。
4. 净化：`_sanitize_dynamic_prompt`（**实现于调用侧** `tools.py`，非原文说的 client 侧；行为等价）——strip + 控制字符剔除 + 4096 字符截断。⚠️ 超限当前是**静默截断**，非原文的"落警并降级"。
5. 降级：后端不可达 → warning + 空片段（仅静态文件），metrics 计数 `otc_agent_dynamic_prompt_total{status=cache_hit|cache_miss_ok|fallback}`，不让 ticker 崩。

## 实现偏离（裁决见 [#156](https://github.com/GZTL-AI/aigc-langgraph/issues/156)）

| 偏离 | 现状 |
|---|---|
| **拼接后完整 prompt 摘要未落 trace（中）** | 原文把它写成硬要求（"否则线上排错失去依据"）：动态片段被运维热改后，无法从 trace 还原当时实际生效的完整提示词。可降级实现为"记录动态片段哈希 + 长度"。注意原文的"前 500 字符"引用了 [ADR 0004](./0004-trace-granularity-node-level-with-langsmith.md) 旧约定，现行截断长度为 2048 |
| **降级标记落 metrics 不落 trace（轻）** | 原设计 trace `dynamic_prompt_fallback=true`；实际只有计数器——能看到"降级了多少次"，定位不到"哪条会话降级了"，与 ADR 0004 的节点级排错路径不衔接 |

## 备选方案

- **不补，保留静态文件**：失去运维热改能力。
- **按 counterparty 拉取**：后端返回的是全局配置，过度设计。
- **拼接策略反向**：动态片段是规则补充非框架，反向风险高。
- **拉取 + 拼接 + 降级（已选）**：3 步恢复等价行为。

## 后果（现状口径）

- 热改后最长 5 分钟生效；即时生效的缓存清除接口暂不做。
- 推断 prompt 不再"完全静态可读"：读 `infer_code.md` 只见框架，完整提示词 = 框架 + 后端 config（排错依赖上表第一项护栏补齐）。
- 同样模式（热配 prompt 片段）暂不抽象通用框架——当前仅 ticker `infer_code` 一处使用，按需求出现再做。
