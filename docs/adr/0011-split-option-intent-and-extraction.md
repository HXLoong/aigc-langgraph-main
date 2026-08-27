# ADR 0011 · option 子图拆分"意图识别"与"参数提取"为两阶段 LLM 调用

- 状态：已采纳（拆分已完成落地；灰度与 golden 覆盖两项前置纪律未兑现，见"实现偏离"）
- 日期：2026-05-10（含同日二次修订：extract 定为 5 份，close_order_* 归独立 close 子图）
- 修订：2026-08-27 深度改写为现状口径（wayfinder map #138 / 核查 #143）
- 作者：图灵科技 + Tony

## 上下文

Dify 主干中"期权-意图识别、参数提取"是单 LLM 节点同时承担分类 + 完整参数抽取（`intent_extract.md` 2870 行），"双任务巨型提示词"是用户体验差的最大单一根因。决定拆为两阶段，对齐 swap 已验证的 `intent.md` + 分意图提取模式。

二次修订要点（已吸收）：原方案错把 6 个 `close_order_*` 算进 option——close 是独立子图（`option_close/` 提示词目录 + `close/` 代码目录），一级路由判 `product=close` 后不进 option。option 只处理基础意图。

## 落地现状（2026-08-27，拆分已完成）

- **阶段一**：`app/prompts/option/intent.md`（71 行，远低于 500 行目标）——`get_qwen_structured()` + `with_structured_output(OptionIntentOutput)`（模型实体现为 deepseek-v4-pro，[ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md)）。
- **阶段二**：5 份 extract 齐备——`extract_inquiry`(108 行) / `extract_place_or_modify`(107) / `extract_cancel`(49) / `extract_confirm`(56) / `extract_query`(45)；节点与 `_INTENT_TO_NODE` 路由表与下方合并规则逐条一致（`option/graph.py` 注册 7 节点 = intent + 5 extract + unknown）。
- 原 `intent_extract.md` 仍为 2870 行，**已冻结为 diff 快照**（业务代码零加载，`app/prompts/CLAUDE.md` 登记）。
- **意图枚举真值 = 9 个业务意图 + `unknown_intent`**（原文"期权基础（6 类）"标题与其下 9 条列表自相矛盾，本次订正）：`new_inquiry` / `place_order_from_quote` / `confirm_order` / `cancel_order_request` / `request_cancel_order` / `confirm_cancel_order` / `request_modify_order` / `confirm_modify_order` / `query_order_status`。
- extract 合并规则（与代码一致）：inquiry ← new_inquiry；place_or_modify ← place_order_from_quote + request_modify_order；cancel ← cancel_order_request + request_cancel_order；confirm ← 3 种确认（expected_action 区分，同 ADR 0001 D5 swap confirm 合并原则）；query ← query_order_status。
- **原文未记录的新增逻辑（本次补录）**：`option/intent.py` 在 LLM 前有三条确定性快速路径（`-` 单字符 / "确认下单" / "撤单"），LLM 后有关键词改写规则。这层规则**无 ADR 锚点**（[ADR 0015](./0015-intent-route-rules-first-llm-fallback.md) 只覆盖一级 product 路由，不覆盖子图 intent）——登记为偏离待裁决。
- close 子图后续：close 已按同款模式完成 intent + 6 份分意图提示词拆分；遗留项收敛为 **`option_close/place_close.md` 1036 行单文件瘦身**（是否做取决于收益数据）。

## 实现偏离（裁决见 [#159](https://github.com/GZTL-AI/aigc-langgraph/issues/159)）

| 偏离 | 现状 |
|---|---|
| **跳过灰度直接硬切** | 原 Consequences 约定按 [ADR 0003](./0003-prompt-versioning-by-file-coexistence.md) 走 `intent_v2.md` 并存 + 灰度切流验证；实际直接新建 `intent.md` 一次性切换，`_versions.yaml` 仅有 swap.intent 一条 override，option 从未进灰度。需追认"为何跳过"或补灰度 |
| **golden 覆盖前置未满足** | 原文明写"5 份 extract 必须独立 golden 覆盖，否则某意图无样本回归会被遗漏"；现状 option 侧 `request_modify_order` / `confirm_modify_order` **零覆盖**、`query_order_status` 仅 1 条（对照：new_inquiry 99 / place_order_from_quote 68）。可并入 Issue #113 fixture 质量修复 |
| **intent.py 确定性规则层无 ADR 锚点** | 决策形态是"两阶段纯 LLM"，实际带前置/后处理规则——需补锚点（本 ADR 追认或另开 ADR）|

## 备选方案（历史论证）

- **保留单 LLM 节点**：准确率天花板已触顶。
- **两阶段拆分（已选）**：swap 模式已在生产验证。
- **三阶段（意图 → 草稿 → 校验）**：工程复杂度超出回报曲线。

## 后果（现状口径）

- 多一次 LLM 调用的延迟代价（预估 +200~400ms）需在 trace 观察"option 子图 P95"作反向指标——注意端到端 P95 采集本身尚未接线（[ADR 0017](./0017-m4-canary-quantitative-exit-gate.md) 偏离，#157）。
- 拆分是 Phase 1.5 提示词架构清理，隶属 [ADR 0002](./0002-comprehensive-runtime-harness.md) 路线。
- 实施前提（"intent_extract 内无'必须同时拿参数才能定意图'的耦合"）已与业务方确认并被落地结果验证。
