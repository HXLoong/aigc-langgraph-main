# ADR 0005 · Phase 4 标注闭环：LLM judge 全量 + 业务方每周抽检关键 case

- 状态：已采纳（标注平台随 [ADR 0014](./0014-langfuse-as-harness-backend.md) 定为 LangFuse Annotation Queue；Phase 4 运营尚未立项）
- 日期：2026-05-10
- 修订：2026-08-27 深度改写为现状口径（wayfinder map #138 / 核查 #140）
- 作者：图灵科技 + Tony

## 决策（角色分工，保持不变）

[ADR 0002](./0002-comprehensive-runtime-harness.md) Phase 4 需要"线上 trace → 标注 → golden set 反哺"。采用 **LLM judge 自动评分 + 业务方关键 case 复核**双层分工：

1. **LLM judge 做日常自动评分**，覆盖全量流量（Phase 4 目标态）。
2. **业务方做关键 case 标注**：每周约 30 分钟，看 judge 低置信 case 做最终定性（对/错/业务等价），回流 golden。
3. **工程师不充当业务正确性裁判**：只负责 trace 抓取、judge 提示词调优、回流脚本。

**业务方标注权重 > judge**：业务方定性为"错"的 case 无条件进 golden 作反例。

## judge 层落地现状（2026-08-27，先于 Phase 4 以离线形态落地）

- 载体：`scripts/langfuse/langfuse_eval.py`（M3 主用评估入口）——**覆盖面是离线 golden 批跑，不是线上流量**；"100% 线上流量"仍是 Phase 4 目标而非现状。
- judge 模型：经 DeepSeek 的 Anthropic 兼容端点调用，默认 **`deepseek-v4-flash`**（`ANTHROPIC_MODEL` 可覆盖；与 [ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) 业务侧的 v4-pro 不同型号，flash 为评估成本考量）。
- 输出契约：**`{pass: bool, score: 0.0-1.0, reason: str}`**（原设计的 `confidence ∈ {high, medium, low}` 三档未采用；Phase 4 若要驱动"业务方只看低置信"队列，需定义 score→confidence 映射阈值）。
- 曾存在双实现（`langfuse_eval_clean.py` 亦含 judge 逻辑），已删除；judge 逻辑单一入口（2026-09-22 复核）。

## 标注平台选型（已定）

**LangFuse Annotation Queue**（ADR 0014 四件套之一：trace / dataset / eval / annotation），零额外开发量、与 trace 数据天然关联。自建 UI 仅当业务方界面需求（中文/专属字段/SSO）不满足时再评估。标注队列的创建/拉取/回流脚本尚无——属 Phase 4 立项范围（二期 Issue #37 D 桶回流自动化）。

## 备选方案

- **仅工程师标注**：不懂业务正确性，质量不达标。
- **仅业务方标注**：规模上不去。
- **仅 LLM judge**：领域常识不足，偏差累积污染基线。
- **业务方 + judge 混合（已选）**：业务方时间花在 judge 最不确定的 case 上，平衡规模和权威性。

## 实现偏离与裁决（[#159](https://github.com/GZTL-AI/aigc-langgraph/issues/159)）

| 偏离 | 现状 |
|---|---|
| ~~judge 提示词硬编码在脚本里~~ | ✅ #159 已修复：正文迁至 `app/prompts/judge/option_judge.md`，评估脚本统一通过 `load_prompt("judge", "option_judge")` 加载；`tests/prompts/test_prompt_governance.py` 防回归 |
| **golden 的"标注来源"字段被占用** | `golden.jsonl` 的 `source` 字段 535/535 全是数据出处路径（`csv/…/rowN`）；本 ADR 要求的标注权威性维度（judge / business / engineer）无处可放，Phase 4 回流前需另起字段（如 `annotation_source`） |

## 后果

- 业务方每周 30 分钟是 Phase 4 硬依赖，立项前须与业务方明确承诺。
- judge 模型是软依赖可替换；提示词已纳入文件版本治理，评分批次仍须记录实际 prompt 版本以保持可比。
