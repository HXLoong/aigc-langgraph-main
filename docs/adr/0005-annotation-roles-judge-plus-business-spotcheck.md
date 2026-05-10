# Phase 4 标注闭环：LLM judge 全量 + 业务方每周抽检关键 case

> **Status update (2026-05-10)**：标注平台从 LangSmith Annotation Queue **改为 LangFuse Annotation Queue**（见 ADR 0014）。
> 双层分工（LLM judge 全量 + 业务方周抽检关键 case）和业务标注权重 > judge 的核心决定保持不变。

ADR-0002 Phase 4 需要"线上 trace → 标注 → golden set 反哺"。我们决定采用 **LLM judge 自动评分 + 业务方关键 case 复核** 的双层分工：

1. **LLM judge（C）做日常自动评分**：每条线上 trace 由强模型（待选 Claude Opus / Qwen-Max 类）自动跑评分，输出 `confidence ∈ {high, medium, low}` 标签。覆盖 100% 流量。
2. **业务方（B）做关键 case 标注**：OTC desk 业务方每周花约 30 分钟，看 judge 打"low confidence"的 case 列表，做最终定性（对/错/业务等价），回流 `tests/fixtures/golden.jsonl`。
3. **工程师（A）不充当业务正确性裁判**：只负责 trace 抓取、judge 提示词调优、标注 UI 维护、回流脚本。

业务方标注权重 > judge：业务方一旦定性为"错"，无论 judge 评分如何，该 case 进入 golden 作为反例。

## Considered Options

- **仅工程师标注（A）**：工程师不懂业务正确性（互换 vs. 平仓的判定要专业经验），标注质量不达标。
- **仅业务方标注（B）**：标注规模上不去，时间成本失控。
- **仅 LLM judge（C）**：通用 LLM 对场外衍生品场景常识不足，judge 偏差累积进 golden 后污染评估基线。
- **B + C 混合（已选）**：把业务方时间花在 judge 最不确定的 case 上（高边际价值），平衡规模和权威性。

## Annotation 平台选型（待 Phase 4 MVP 前定）

由于 ADR-0004 已选用 LangSmith 承载完整 LLM I/O，**标注平台优先复用 LangSmith Annotation Queue**，而非自建 UI：

- **优先方案：LangSmith Annotation Queue**：直接基于已有 trace 创建标注队列，业务方在 LangSmith 界面打标，导出后回流 golden。零额外开发量，与 trace 数据天然关联。
- **备选方案：自建标注 UI**：仅当 LangSmith 不能满足业务方界面需求（中文支持、专属字段、SSO 集成等）时才考虑，明显增加运维成本。
- **决策时机**：Phase 4 立项时由业务方实际试用 LangSmith Annotation Queue 一周后决定，不在本 ADR 提前锁死。

## Consequences

- 优先复用 LangSmith Annotation Queue，避免重复造轮子。仅当 LangSmith 不能满足业务方界面需求时才自建 UI。
- 业务方每周 30 分钟是硬依赖。如果业务方实际投入达不到，Phase 4 闭环失效。需要在立项前与业务方明确承诺。
- judge 模型是软依赖：可替换、可升级。但 judge 提示词本身要纳入 ADR-0003 的版本化管理（judge 提示词改动 → 历史评分作废 → 需要重跑批次）。
- golden set 必须有"标注来源"字段（judge / business / engineer），便于追踪反例的权威性。
