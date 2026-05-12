# 加载后端动态 prompt 片段（swap_instrument_inference_prompt）

> **Status update (2026-05-10)**：审计后核实 endpoint 路径正确——`GET /admin-api/counterparty/info/instrument-inference-prompt`，由 `CounterpartyInfoController.java:33` 实现。返回类型为 `CommonResult<String>`（包裹一个纯字符串），不是 JSON 对象。`/admin-api` 前缀由 `WebProperties.adminApi` 框架级配置自动注入。
> 客户端实现：`await client.get(url)` → 解析 `result.data` 为 `str`。

> **Status update (2026-05-13)**：客户端归属修正。ADR 0001 D2 修订版把单一 OtcBackendClient 拆成 3 个 Protocol（option / swap / ticker），`get_inference_prompt` 实际落在 `app/tools/ticker_client.py:TickerClient.get_inference_prompt`（不是本 ADR 原文写的 otc_backend.py）。下方"实现要点 1"已过期，以代码现状为准。

Dify 工作流通过 `GET /admin-api/counterparty/info/instrument-inference-prompt`（实际返回全局配置 `configApi.getConfigValueByKey("swap_instrument_inference_prompt")`）拉取一段**运维可热改的 prompt 片段**，注入到标的推断 LLM 节点。LangGraph 当前用静态 `app/prompts/ticker/infer_code.md`，这一热改能力被丢失：业务方/运维想临时调整标的推断规则（加新约束、新字典）就必须发版。

我们决定补上这条能力：在 LangGraph 的 ticker 子图调用推断 LLM 前，先调 `OtcBackendClient` 拉取 `swap_instrument_inference_prompt` 配置值，与静态文件 `infer_code.md` 拼接后再喂给 LLM。

**实现要点**：
1. ~~在 `app/tools/otc_backend.py` 新增 `async def get_inference_prompt() -> str`，对应 endpoint Y。~~（已过期，见上方 2026-05-13 Status update：实际落在 `app/tools/ticker_client.py`）
2. 在 ticker 子图推断节点入口，先获取该片段（带 5 分钟 LRU 缓存，降低 HTTP 往返成本）。
3. 拼接策略：静态 `infer_code.md` 作为基础提示词框架（包含输出格式、工具调用规范），动态片段作为 **业务规则补充**追加到 `system` 部分末尾。
4. 后端不可达时降级为仅用静态文件，记录 warning + trace `dynamic_prompt_fallback=true`，不让 ticker 子图崩。

## Considered Options

- **不补，保留静态文件**：失去运维热改能力，业务方反馈会变多，违背 ADR-0001 列的"业务逻辑可见 + 可调"目标。
- **改为按 counterparty 拉取**（实现 URL 路径暗示的语义）：后端目前返回的是全局配置，与按 counterparty 定制不一致；过度设计，等真出现按客户定制需求再说。
- **拼接策略反向**（动态片段作为基础，静态文件作为补充）：动态片段是规则补充而非框架，静态文件包含的输出格式 / 工具调用约束更基础，反过来风险高。
- **本 ADR 的方案（已选）**：拉取 + 拼接 + 降级，3 步即可恢复等价行为。

## Consequences

- 缓存 5 分钟意味着热改后最长 5 分钟生效，业务方可接受。如需即时生效，可暴露管理端清除缓存接口（暂不做）。
- 推断 prompt 不再"完全静态可读"——读 `infer_code.md` 只能看到框架，必须配合后端 config 才能看完整提示词。trace（ADR-0004）必须记录拼接后的完整 prompt 摘要（前 500 字符），否则线上排错失去依据。
- 动态片段是字符串，没有类型/格式约束，运维错误配置（如 YAML 注入、非 UTF-8）可能让 LLM 直接崩溃。需要在 `get_inference_prompt()` 加基础净化：trim、长度上限（如 4096 字符）、字符集校验，超限或异常时落警并降级。
- 缓存失效策略需要写明：5 分钟绝对过期 + 进程重启清空。如果未来上多副本，缓存独立，最长 5 分钟内不同副本响应可能不一致——可接受。
- 同样模式可推广到其他需要热配的 LLM 提示词节点（如未来若 swap/option 也需要按客户定制规则），但当前不预先抽象通用框架，按出现需求再做。
