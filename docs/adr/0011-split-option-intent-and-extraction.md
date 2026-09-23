# ADR 0011 · option 子图拆分意图识别与分意图参数提取

- 状态：已采纳（两阶段边界保持；DSL v2 已将第二阶段演进为 7 个意图与 7 个提取节点一一对应）
- 日期：2026-05-10
- 修订：2026-08-29 按 DSL v2 主分支现状更新
- 作者：图灵科技 + Tony

## 上下文与不变决策

Dify 旧主干把期权意图分类和完整参数抽取塞进一个 2870 行提示词，分类与抽取相互干扰。决定保持两个阶段：先识别业务意图，再按意图进入专用参数提取节点；期权平仓继续归独立 close 子图。

这个架构边界不依赖具体意图数量：新增、合并或删除期权意图时，可以调整第二阶段节点，而不把分类和所有 DTO 重新合回一个巨型提示词。

## 当前落地（DSL v2，2026-08-29）

`app/subgraphs/option/graph.py` 当前注册：

- 第一阶段：`option_intent`
- 第二阶段：`option_extract_inquiry`、`option_extract_place`、`option_extract_confirm_place`、`option_extract_cancel_place`、`option_extract_cancel`、`option_extract_confirm_cancel`、`option_extract_query`
- 兜底：`option_unknown`

7 个业务意图与 7 个提取节点一一对应：

| 意图 | 提取节点 |
|---|---|
| `new_inquiry` | `option_extract_inquiry` |
| `place_order_from_quote` | `option_extract_place` |
| `confirm_order` | `option_extract_confirm_place` |
| `cancel_order_request` | `option_extract_cancel_place` |
| `request_cancel_order` | `option_extract_cancel` |
| `confirm_cancel_order` | `option_extract_confirm_cancel` |
| `query_order_status` | `option_extract_query` |

DSL v2 删除了独立 `request_modify_order` / `confirm_modify_order`：已有订单的参数修改统一归 `place_order_from_quote`。这取代了旧版“9 个业务意图合并到 5 个 extract”的实现形态，但不改变“两阶段拆分”的核心决策。

2026-09-08 合并会话续接修复：保留 7 个提取节点，询价尚未完成时补期限仍归 `new_inquiry`；不恢复依据引用卡片关键词强制改为下单的后处理。`OptionOrderItem` 的可选 `orderId` 与 `tenor` 同时用于询价和下单分支，仅携带原单号及本轮新增参数，缺省参数由 Java 合并。旧 `extract_place_or_modify` 的补参约束迁入 `extract_place`。

2026-09-11 按用户明确要求，`option/intent.md`、`option/extract_inquiry.md`、`option/extract_place.md` 的 system/user 提示词重新完整同步为 dify/yaml/场外交易-test.yml（已移出仓库，tag dify-assets-frozen-20260917（指向 commit fddd94e；tag 仅存本地，远端拒绝 tag 推送，维护者可从该 sha 重建））对应节点原文；上述 2026-09-08 本地提示词增补不再单独保留，当前分类与提取规则以该 YAML 为准。两阶段和 1+7 节点结构不变，处置登记见 [ADR 0001 D5](./0001-rewrite-app-with-harness-first.md)。

2026-09-17（[ADR 0023](./0023-prompt-as-code-langgraph.md) D 批去 LLM 化）：`option_extract_cancel` / `option_extract_cancel_place` / `option_extract_confirm_cancel` / `option_extract_query` 四个 Q- 单号节点改为确定性提取（`app/subgraphs/option/order_id.py`），不再调用 LLM；`app/prompts/option/` 现役仅 `intent.md` 与 `extract_inquiry.md`。两阶段与 1+7 节点结构不变，只是 7 个提取节点中 4 个不再是 LLM 节点。2026-09-18 起 `extract_inquiry` 的输出为原文候选（[ADR 0027](./0027-field-evidence-contract.md)）。

## 历史偏离与裁决

- 旧版跳过 A/B 灰度直接硬切；该历史事实保留，不要求对已退役结构补做灰度。
- 旧版 `request_modify_order` / `confirm_modify_order` 的数据集缺口已随两个意图从 DSL v2 真值集删除而关闭。
- judge prompt 版本化与 Dify 同步防覆盖已于 2026-08-27 落地；不再把它们列为当前未解决偏离。

## 备选方案

- **保留单 LLM 巨型节点**：分类和参数 DTO 耦合，回归面与提示词规模不可控。
- **两阶段 + 分意图提取（已选）**：分类边界稳定，具体提取节点可随 DSL 演进。
- **三阶段（意图 → 草稿 → 校验）**：额外调用和状态复杂度暂不值得。

## 后果

- 每次业务调用比单节点方案多一次分类 LLM；端到端延迟埋点已接线，应通过实际 P95 观察成本。
- 意图枚举、`_INTENT_TO_NODE`、提示词和 golden 必须同步变更。
- close 子图保持独立，不能把平仓意图重新并回 option。
- 本决策属于 [ADR 0002](./0002-comprehensive-runtime-harness.md) 的提示词架构治理，并受 [ADR 0003](./0003-prompt-versioning-by-file-coexistence.md) 的版本纪律约束。
