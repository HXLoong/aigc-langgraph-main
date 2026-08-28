# Prompt 改进 Backlog（M2 阶段累积）

> 自动质量扫描 / 业务方 review / 真 LLM 跑 harness 中暴露出的 prompt 缺陷
> 不阻塞当前合入；M2 后期或 M3 shadow 阶段集中迭代 prompt v3+

## 已识别问题

### 1. swap.confirm_order / option.confirm_order 不支持口语确认

**触发 case**：g181 / g245
- raw=`"好的可以"` / `"嗯可以"` / `"OK"` 等口语化确认
- v1 prompt 严格要求 raw 必须含 `"确认下单"` 整体短语才触发 confirm_order

**现状处理**：
- 自动质量扫描已修订 g181 / g245 为 `unknown_intent`（接受 v1 限制）
- 业务方期望识别为 confirm_order，但保留 confirm_order 会拉低 business_seed PASS 率

**改进方向**（v3 prompt 候选）：
- 在 confirm_order 触发条件加白名单短语：`"好的可以"` / `"OK"` / `"嗯"` / `"是的"`（同时 quote 是订单确认上下文）
- 风险：模糊化标准，可能误触发其他场景；需配合 quote 上下文严格判定
- 评估：需先收集业务方"哪些口语等同确认"明确列表

**优先级**：P2（边角，正例 g004/g005 已 PASS，仅口语化 case 失败）

---

### 2. swap "改 X" 与"确认改单"边界（g008 已修）

**已处理**：v2 prompt 加冲突仲裁规则，5% 灰度上线（commit 0cbdef6）

---

## 待补充

业务方/工程师在评估 / shadow 阶段发现新缺陷时追加此处。
