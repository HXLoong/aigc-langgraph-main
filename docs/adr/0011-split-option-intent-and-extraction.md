# option 子图拆分"意图识别"与"参数提取"为两阶段 LLM 调用

> **Status update (2026-05-10, 二次修订)**：grill-with-docs 复盘后定为 **5 个 extract**（去掉原列表中的 `extract_close`）。原 6-7 份方案错误地把 6 个 `close_order_*` 意图算进 option 子图——但 close 已是**独立子图**（`option_close/`，独立 product_type），一级路由判定 `product=close` 后根本不会进 option 子图。option 子图只处理基础 10 个意图（去掉 6 个 close_order_*）。

Dify 主干工作流中"期权-意图识别、参数提取"是单 LLM 节点同时承担分类 + 完整参数抽取，对应 LangGraph 的 `app/prompts/option/intent_extract.md` 高达 **2870 行**。这个"双任务巨型提示词"是当前用户体验差的最大单一根因，被 Dify 迁移按"原封保留"原则带进了 LangGraph，路由和 trace 问题虽已解，意图准确率仍未显著好转。

我们决定把 option 子图拆分为两阶段 LLM 调用，对齐 swap 子图已验证的模式：

1. **阶段一：意图分类**（新建 `app/prompts/option/intent.md`，目标 < 500 行）—— 仅输出 `stockOptionIntentionType` 中的一种值（小写下划线 type 字符串），使用 standard 模型 + structured output。
2. **阶段二：参数提取**（按意图分多份提示词文件 `option/extract_<intent>.md`）—— 在路由到具体意图后才加载对应抽取提示词，单文件聚焦、token 成本下降。

**真实意图枚举**（共 16 个，含 6 个平仓意图，按职责合并后实际需要约 7-8 份 extract 提示词）：

期权基础（6 类）：
- `new_inquiry` — 询价
- `place_order_from_quote` — 基于报价下单/纠正参数
- `confirm_order` — 确认下单
- `cancel_order_request` — 取消下单请求（订单作废）
- `request_cancel_order` — 请求撤单
- `confirm_cancel_order` — 确认撤单
- `request_modify_order` — 请求改单
- `confirm_modify_order` — 确认改单
- `query_order_status` — 查询订单状态

期权平仓（6 类，可独立子图也可合并到 option 内）：
- `close_order_query / close_order_request / close_order_confirm`
- `close_order_cancel_request / close_order_cancel_confirm / close_order_order_query`

`unknown_intent` 兜底。

按职责合并后的 extract 提示词（**5 份**，covered 10 个 option 基础意图，不含 close）：
1. `extract_inquiry.md` — 询价（new_inquiry）
2. `extract_place_or_modify.md` — 下单/改单参数（place_order_from_quote + request_modify_order）
3. `extract_cancel.md` — 撤单（cancel_order_request + request_cancel_order）
4. `extract_confirm.md` — 各种确认（confirm_order + confirm_cancel_order + confirm_modify_order）
5. `extract_query.md` — 查询（query_order_status）

`unknown_intent` 走兜底无需 extract。**6 个 `close_order_*` 意图归 close 子图（`option_close/`），不在 option 内**。

意图分类后的路由层与 ADR 0001 D5 的"互换 confirm 合并"原则一致：高度相似的"确认 X"用同一个 extract + 一个 expected_action 字段区分。

实施前提是 `option/intent_extract.md` 内部确无"必须同时拿到参数才能定意图"的耦合（与业务方确认无此约束）。

## Considered Options

- **保留单 LLM 节点**：与现状一致，准确率天花板已经触顶。
- **两阶段拆分（已选）**：参考 swap 的 `intent.md` + `place_order.md` 模式，已在生产验证可行。
- **三阶段（意图 → 参数草稿 → 校验）**：理论更稳，工程复杂度大幅增加，超出当前回报曲线。

## Consequences

- 单次请求多一次 LLM 调用，端到端延迟会增加（预估 +200~400ms）。需要在 ADR-0004 trace 里观察"option 子图 P95 延迟"作为反向指标，确认延迟代价 < 准确率收益。
- 5 份抽取提示词必须独立做 golden set 覆盖，否则拆开后某一意图无样本回归会被遗漏。
- 拆分按 ADR-0003 文件并存策略推进：先做 `option/intent_v2.md` + `option/extract_*.md`，与原 `intent_extract.md` 并存，灰度切流验证准确率；老版本满稳定期后下线。
- 此举是 Phase 1.5 的提示词架构清理，应纳入 ADR-0002 的路线图（在 Phase 2 trace 监测能力之上才能量化收益）。
- close 子图同样问题待评估：`option_close/place_close.md` 1036 行尚未拆分，是否走同样路径取决于本 ADR 实施后的收益数据。
