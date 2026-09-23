# ADR 0028 · 会话保护入口分流与单动作多订单（多指令编排已退役）

- 状态：会话保护与入口分流继续沿用；多指令拆分、Send 编排与批次调度按用户裁决于 2026-09-22 退役（2026-09-23 合并同步）。原实现记录保留在历史章节。
- 日期：2026-09-21（记录：2026-09-22）
- 起源：[docs/langgraph-reconstruction-20260918.md](../langgraph-reconstruction-20260918.md) 计划项"多指令分发、依赖、批量提交与逐项结果"；2026-09-21 修复"会话保护与业务入口耦合"
- 修订：[ADR 0015](./0015-intent-route-rules-first-llm-fallback.md)（一级路由之前新增入口层）、[ADR 0024](./0024-langgraph-native-rearchitecture.md) D3（`Send` 并行的落点从 ticker 子图改为多指令编排）
- 作者：图灵科技 + Tony

## 上下文

DSL v2 迁移后主图入口是"快速询价 / 存量兼容 / 普通智能指令"三分支，但会话过期检查、入口异常与业务分流混在同一段条件路由里，且客户一条消息里带多条指令（"买入 A，然后撤销 B"）时只能整条当一个意图处理。ADR 0024 D3 把 `Send` 用在 ticker 子图上，该子图已随 [ADR 0025](./0025-instrument-resolution-delegated-to-backend.md) 删除；当时曾将 `Send` 用于多指令并行准备；该方案现已退役，当前行为见下文。

## 决策

### D1 · 会话保护与三类入口

```text
START → ingest（一轮边界 + 会话活动检查）
  ├─ error 或 session_status=expired → render
  └─ entry_route
      ├─ quick_inquiry → render
      ├─ existing_command_query → render
      └─ pre_route → intent_route → swap | option | option_close | fallback
           → persist_intent → render
render → remember_confirmed_params → record_history → persist → END
```

- 会话空闲超过 `conversation_idle_timeout_seconds`（默认 1800s）后，直接返回会话过期提示。
- `app/nodes/entry_route.py::select_entry_branch` 决定入口，图边与 trace 共用该函数。
- `fast_query=1` 才进入主图快速询价，以 `optionRfq` 提交；普通 `new_inquiry` 固定经过提取、归一化和 `orderList` 提交，产品关键词不改变入口。

### D2 · 单动作多订单

- 每条消息按既有产品与意图优先级执行一个业务动作，该动作允许携带多笔订单。
- 多动作拆分、依赖编排、操作捕获和批量调度已经删除，节点执行接口与 harness 目录不暴露退役节点。
- 保留既有逐单身份、状态与最终确认校验；历史幂等回执可原样重放，不重新执行业务。
- 每轮输入覆盖旧状态；七条最终确认仍要求明确口令与当前订单引用，不从记忆补足授权。

## 历史方案（已退役，仅保留实施记录）

以下 D2–D4、备选方案和后果记录 2026-09-18 的实现，不代表当前能力或待办。

### 历史 D2 · 多指令计划：确定性预筛 → LLM 拆分 → Code 定位与拒绝规则（~~`app/graph/instructions.py`~~）

- 预筛：无分隔符 / 连接词且动作词计数 ≤ 1 → `single_instruction`，不调 LLM；引用卡片的批量补参 → `quoted_batch_supplement`，不拆。
- LLM（PromptSpec `router/split_instructions`）只输出 `InstructionCandidate`：`text`（连续原文，不改写）、`evidence`（= text）、`confidence`、`depends_on`（只能引用前序）、`requires_result`（是否必须使用前序生成的订单身份）；最多 8 条。
- Code 定位每条的 `start` / `end`：相邻指令之间只允许分隔词与连接词，**不得遗漏原文**；定位失败 → `EvidenceError`（E2）。
- 拒绝拆分：含业务成功条件（"成交后再…"，HTTP `code=0` 不证明成交）→ 要求用户稍后显式确认；多指令携带附件（归属不明）→ 拒绝。

### 历史 D3 · `instructions` 子图：依赖分波、`Send` 并行准备、批量一次提交

```
initialize → schedule ─(Send 按就绪指令 fan-out)→ prepare_instruction ×N → submit_instruction_batches → schedule … → finish
```

- `schedule`：依赖未完成的指令等待；依赖失败 → `blocked(dependency_unavailable)`；`requires_result` 要求恰好一个依赖且能取到权威订单号，否则 `blocked(dependency_binding_ambiguous)`。
- `prepare_instruction`：以主图的 worker 形态（`build_main_graph(_instruction_worker=True)`，无 persist / 不递归编排）跑单条指令；`capture_operations` 在协议边界**捕获**已校验的 DTO 而不真提交；依赖结果以后端真实回复（非伪造卡片）追加进 `history_messages`；一条指令产出 0 / >1 个操作分别记 `needs_input` / `blocked`。
- `submit_instruction_batches`：`batch_operations` 把同一产品、可合并的列表型操作合成一批，`execute_batches` 每批提交一次；`dedup_window_seconds`（默认 10s）与 `blocked_keys` 防止同键重复提交。
- `finish`：逐条 / 逐批输出"第 N 条指令：<后端真实回复或状态文案>"；任一 `uncertain` → `ErrorInfo(BackendUnreachableError)` 触发对账语义（[ADR 0026](./0026-request-idempotency-uncertain-receipts-reconciliation.md)）；混合指令的 `product_type=unknown` / `intent=multi_instruction`，每条真实结果保留在 `instruction_results`，不写成单一 Java `productType`。

### 历史 D4 · 边界

- 子图 `compile(checkpointer=False)`，中间态 `_*` 不外泄（`InstructionsOutput`）。
- 写类操作仍不重试（ADR 0024 D3）；批内失败隔离，不回滚其它指令。

## 历史备选方案

- **串行逐条重跑主图**：第 N 条的依赖需要前序结果，串行实现简单但整体延迟随条数线性增长，且无法隔离 persist 副作用。否决。
- **LLM 一次输出多个 DTO**：违反 [ADR 0027](./0027-field-evidence-contract.md)（最终值由 Code 产生），且无法表达依赖与批量。否决。
- **预筛 + LLM 拆分 + Send 并行准备 + 批量提交（当时选择，现已退役）**。

## 历史方案后果

- 正面：单条指令路径零额外 LLM 调用（预筛短路）；多指令并行准备、按依赖分波提交；每条指令失败隔离并有独立结果；`Send` 在主链路有了真实用途。
- 负面：worker 形态的主图与正式主图必须保持拓扑同步（同一 `build_main_graph`，用 `_instruction_worker` 分叉）；`dedup_window` 与后端自身去重的关系需现场校准；多指令回复较长。
- 未决：跨产品依赖（期权成交后互换）的身份绑定；条件指令（"成交后"）的权威事件契约；set-intent 对 `multi_instruction` 的 Java 侧语义。

## 关联

- [ADR 0015](./0015-intent-route-rules-first-llm-fallback.md) · 一级路由（本 ADR 在其前增加入口层）
- [ADR 0024](./0024-langgraph-native-rearchitecture.md) D3 · 图即架构
- [ADR 0026](./0026-request-idempotency-uncertain-receipts-reconciliation.md) · 不确定回执
- [ADR 0027](./0027-field-evidence-contract.md) · 指令拆分同样受证据契约约束
- ~~`app/execution/operations.py`~~ · 操作捕获与批量提交
