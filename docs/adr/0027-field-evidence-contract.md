# ADR 0027 · 字段证据契约：模型只产原文候选，Code 归一化并记录来源与锁定

- 状态：已采纳（追认，落地 commit `58e5650` / `9493cb9`）
- 日期：2026-09-18
- 关系：修订 [ADR 0023](./0023-prompt-as-code-langgraph.md) D2（模型不再直接输出最终值）、[ADR 0024](./0024-langgraph-native-rearchitecture.md) D2（新增 `field_records` 通道）；配合 [ADR 0025](./0025-instrument-resolution-delegated-to-backend.md)
- 作者：图灵科技 + Tony

## 背景

ADR 0023 让每个 LLM 节点的输出契约收敛为一个 Pydantic 模型，但模型输出的仍是**交易最终值**（数量、价格、期限、订单号）。真实回归暴露三类问题：模型会把授权对手前缀并入名称、把多期限展开后串错执行价、在确认回合把疑问句当确认；这些错误在 HTTP 回执之前没有任何机械可检的信号。金融写路径不能接受"模型说了算"的最终值。

## 决策

### D1 · 模型输出原文候选（`app/extraction/fields.py::FieldCandidate`）

每个可抽取字段的模型输出是 `FieldCandidate`：`value`（归一化前的完整原文，未提及为 `null`）、`evidence`（支持该值的原文**连续片段**，不得改写）、`confidence`（0-1，不能替代证据校验）、`origin`（`raw` / `quote` / `history` / `attachment`）、`reference`（历史消息 ID 或附件行列）。候选 schema 由规范模型经 `app/extraction/candidates.py` 自动生成；`CandidateDescription` 定义候选语义，业务 DTO 的 `Field(description=)` 继续定义最终值语义。

### D2 · Code 校验证据，失败即 E2

`FieldCandidate.verify(sources)`：`value ⊂ evidence ⊂ 对应来源文本`，数字候选还须在证据中是独立数值（不能是另一个数的一部分）。校验失败抛 `EvidenceError`（错误分类 E2，[ADR 0026](./0026-request-idempotency-uncertain-receipts-reconciliation.md) D6），由只读 IO 节点的 RetryPolicy 有限重试；耗尽后落 `state["error"]`，不降级为"取模型值"。

### D3 · 归一化与默认值归属

单位（万 / 亿 / w）、有限枚举、比例（平仓比例按 Java 契约为 (0, 1]）、时间补零等确定性换算由 Code 完成（`swap/normalize.py` / `option/normalize.py` / `option/place_params.py`）；缺失值保持空，**业务默认值由 Java 合并**，LangGraph 不补。

### D4 · 字段账本与锁定（`FieldRecord` / `field_records`）

- `FieldRecord`：`value`（Code 产出的规范值）、`source ∈ {user, inferred, goats, default}`、`evidence` / `origin`、`confidence`、`locked`、拒绝覆盖次数。
- `AgentState.field_records` 使用 `merge_fields` reducer：锁定值拒绝被后续更新覆盖；`app/extraction/locks.py::protect_orders` 在 **State 写入** 与 **后端提交前** 两处检查，锁定订单不得在当前指令内被删除或改写。
- 来源记录与锁定必须在实际后端请求边界生效（子图 `backend.py`），不是提示词承诺。

### D5 · 七条最终确认路径的统一校验（`app/domain/confirmation.py`）

swap 三确认、option 确认下单 / 确认撤单、close 确认平仓 / 确认撤销共七条最终确认路径统一要求：

1. 明确的动作口令（`确认下单` / `确认撤单` / `确认改单` / `确认平仓` 及别名）；
2. 引用当前订单（单号 `H-` / `Q-` / `CO-`、序号、或合约编号）且范围与业务对象一致；
3. 否定、疑问、条件句（"不确认" / "是否" / "吗" / "成交后"）与携带新参数的文本不触发写入。

`last_confirmed_params`（ADR 0024 会话记忆）与程序生成的引用**不能替代用户引用**，记忆仅作上下文。

## 备选方案

- **模型直接输出规范值 + 提示词约束**（ADR 0023 原形态）：错误不可机械检出，提示词规则越写越长。否决。
- **纯规则抽取不用 LLM**：口语化表达覆盖不了。否决。
- **模型原文候选 + Code 证据校验 / 归一化 / 账本（已选）**。

## 后果

- 正面：幻觉值在提交前可检；每个最终值有来源与证据可审计；锁定防止多轮间的静默覆盖；提示词 system 段大幅缩短（以期权询价与互换下单为例，均缩减 90% 以上）。
- 负面：候选 schema 嵌套增大 function-calling 输入；`history` / `attachment` 来源需要节点提供 `sources` 文本；已接入证据契约的节点与未接入节点并存期间口径不一。
- 未决：候选 schema 压缩；未接入节点清单（migration README 标"需逐项迁移 / 核对"）的完成时点；`inferred` 来源值是否允许进入写请求。

## 关联

- [ADR 0023](./0023-prompt-as-code-langgraph.md) · PromptSpec 与输出契约
- [ADR 0025](./0025-instrument-resolution-delegated-to-backend.md) · 标的原文透传
- [ADR 0026](./0026-request-idempotency-uncertain-receipts-reconciliation.md) · E1–E5 错误分类
- `.claude/rules/langgraph-patterns.md` · 操作口径（原文候选含 evidence / confidence / source；Code 验证）
