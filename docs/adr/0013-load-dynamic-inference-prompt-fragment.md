# ADR 0013 · 加载后端动态 prompt 片段（swap_instrument_inference_prompt）

- 状态：**已撤销**（2026-08-28 DSL v2 迁移 a5d0c15 把 `inferencePrompt` 收编为静态 prompt，~~`app/subgraphs/ticker/tools.py`~~（2026-09-20 标的识别委托 Java 后端，ticker 子图 / 提示词 / 测试随 commit `2f9ce65` 整体删除，见 `docs/backend-instrument-boundary.md`） 不再运行时拉取；`TickerClient.get_inference_prompt` 为遗留死代码，清理见 [ADR 0022](./0022-prompt-governance-after-code-migration.md)）。以下为历史原文。
- 日期：2026-05-10
- 修订：2026-08-27 深度改写为现状口径（wayfinder map #138 / 核查 #141）
- 作者：图灵科技 + Tony

## 决策

Dify 工作流通过后端接口拉取一段**运维可热改的 prompt 片段**（全局配置 `swap_instrument_inference_prompt`）注入标的推断 LLM 节点。LangGraph 若只用静态 `infer_code.md`，业务方/运维临时调整推断规则（加新约束、新字典）就必须发版。决定补上：ticker 推断前先拉取动态片段，与静态文件拼接后喂给 LLM。

## 落地现状（2026-08-27，原两条行内 Status update 已吸收）

**Endpoint**：`GET /admin-api/counterparty/info/instrument-inference-prompt`，返回 `CommonResult<String>`（包裹纯字符串）。Java 侧 `CounterpartyInfoController.java:32`（`@GetMapping`）/ `:36`（方法签名）——原修订注的 `:33` 是行号偏移，`docs/api-contracts/java-backend.md` 同处偏移待一并修正。`/admin-api` 前缀由 `WebProperties.adminApi` 框架级注入。

**实现链路**：

1. 客户端：`app/tools/ticker_client.py` 的 `TickerClient.get_inference_prompt()`（普通 GET → `result.data` 为 `str`；ADR 0001 D2 三 Protocol 拆分后的归属，原文的 `OtcBackendClient` 已不存在）。
2. 缓存：~~`app/subgraphs/ticker/tools.py`~~ 的 `_get_dynamic_prompt_cached()` —— **模块级单 key 缓存 + 300s 绝对过期 + 进程重启清空**（非 `functools.lru_cache`；`infer_code` 工具入口调用）。多副本部署时各副本缓存独立，热改后最长 5 分钟不一致，可接受。
3. 拼接：静态 ~~`app/prompts/ticker/infer_code.md`~~（2026-09-20 标的识别委托 Java 后端，ticker 子图 / 提示词 / 测试随 commit `2f9ce65` 整体删除，见 `docs/backend-instrument-boundary.md`） 作框架（输出格式、调用规范），动态片段以 `## 后端动态片段（实时拼接）` 追加到 system 末尾。
4. 净化：`_sanitize_dynamic_prompt`（**实现于调用侧** `tools.py`，非原文说的 client 侧；行为等价）——strip + 控制字符剔除 + 4096 字符截断。⚠️ 超限当前是**静默截断**，非原文的"落警并降级"。
5. 降级：后端不可达 → warning + 空片段（仅静态文件），metrics 计数 `otc_agent_dynamic_prompt_total{status=cache_hit|cache_miss_ok|fallback}`，不让 ticker 崩。

## 实现偏离（#156 裁决：追认 metrics 方案 + 轻修）

| 偏离 | 现状 |
|---|---|
| 拼接后完整 prompt 摘要未落 trace | #156 裁决：**降级为结构化日志**——`_get_dynamic_prompt_cached` 命中/拉取时以 warning/info 记录片段长度（现有 logger 已含），完整还原依赖后端 config 的变更审计；不再作为 trace 硬要求 |
| 降级标记落 metrics 不落 trace | #156 裁决：**追认 metrics 方案**（`otc_agent_dynamic_prompt_total{status=fallback}` 为正式载体）；会话级定位可用 #156 落地的 trace_id 关联 LangFuse warning 日志 |

## 备选方案

- **不补，保留静态文件**：失去运维热改能力。
- **按 counterparty 拉取**：后端返回的是全局配置，过度设计。
- **拼接策略反向**：动态片段是规则补充非框架，反向风险高。
- **拉取 + 拼接 + 降级（已选）**：3 步恢复等价行为。

## 后果（现状口径）

- 热改后最长 5 分钟生效；即时生效的缓存清除接口暂不做。
- 推断 prompt 不再"完全静态可读"：读 `infer_code.md` 只见框架，完整提示词 = 框架 + 后端 config；排错依赖后端配置变更审计、结构化日志和 metrics。
- 同样模式（热配 prompt 片段）暂不抽象通用框架——当前仅 ticker `infer_code` 一处使用，按需求出现再做。
