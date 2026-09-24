# ADR 0028 · 会话保护入口分流与单动作多订单

- 状态：已采纳（入口分流沿用；2026-09-22 按用户裁决退役多指令拆分编排）
- 日期：2026-09-21
- 关系：修订 [ADR 0015](./0015-intent-route-rules-first-llm-fallback.md)（一级路由之前新增入口层）
- 作者：图灵科技 + Tony

## 背景

原主图入口是"快速询价 / 存量兼容 / 普通智能指令"三分支，但会话过期检查、入口异常与业务分流混在同一段条件路由里，难以测试与追溯。另曾实现"一条消息多条指令"的拆分、依赖编排与批量提交，复杂度与风险超出收益，已退役。

## 决策

### D1 · 会话保护与三类入口

```text
START → ingest（本轮边界 + 会话活动检查）
  ├─ error 或会话已过期 → render
  └─ entry_route
      ├─ quick_inquiry（快速询价）→ render
      ├─ existing_command_query（存量兼容）→ render
      └─ pre_route → intent_route → swap | option | option_close | fallback
           → persist_intent → render
render → remember_confirmed_params → record_history → persist → END
```

- 会话空闲超过 `conversation_idle_timeout_seconds`（默认 30 分钟）直接返回会话过期提示。
- 入口选择由纯函数 `app/nodes/entry_route.py::select_entry_branch` 决定，图边与 trace 共用。
- 仅 `fast_query=1` 进入快速询价；普通询价固定走"抽取 → 归一化 → 提交"，产品关键词不改变入口。

### D2 · 单动作多订单

- 每条消息按既有产品与意图优先级执行**一个**业务动作，该动作可携带多笔订单（例如识别为撤单申请后，A、B 两笔都按撤单处理）。
- 多动作拆分、依赖编排、批量调度已删除；节点执行接口与评测目录不暴露退役节点。
- 逐单的身份、状态与最终确认校验保持不变；七条最终确认仍要求明确口令与当前订单引用，不从记忆补足授权（[ADR 0027](./0027-field-evidence-contract.md) D5）。
- 历史幂等回执可原样重放，不重新执行业务（[ADR 0026](./0026-request-idempotency-uncertain-receipts-reconciliation.md)）。

## 备选方案

- **会话检查与业务分流混在一处**：不可单测、trace 无法区分拒绝原因。
- **多指令拆分 + 并行准备 + 批量提交**（曾实现，已退役）：依赖绑定、条件指令（"成交后再…"）与后端去重语义都缺少权威契约，写路径风险高。实现记录见 [实施记录归档](../archive/history/adr-implementation-log-2026-09.md)。

## 后果

- 入口分流可单测、每个分支在 trace 中可辨识。
- 客户一条消息内的多个**不同**动作不会被拆开执行，按优先级只执行一个；需要时由客户分条发送。
