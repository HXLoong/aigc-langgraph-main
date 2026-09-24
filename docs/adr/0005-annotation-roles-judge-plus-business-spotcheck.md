# ADR 0005 · 标注闭环：LLM Judge 全量 + 业务方抽检关键 case

- 状态：已采纳（离线 Judge 在用；线上标注运营待启动）
- 日期：2026-05-10
- 关系：标注平台随 [ADR 0014](./0014-langfuse-as-harness-backend.md) 定为 LangFuse Annotation Queue
- 作者：图灵科技 + Tony

## 决策：角色分工

1. **LLM Judge 做日常自动评分**，目标覆盖全量流量。
2. **业务方做关键 case 定性**：每周约 30 分钟，复核 Judge 低分 / 不确定的 case，结论回流数据集。
3. **工程师不充当业务正确性裁判**：只负责 trace 抓取、Judge 提示词调优与回流脚本。

业务方结论权重高于 Judge：业务方判"错"的 case 无条件进入数据集作为反例。

## 现状

- Judge 载体：`scripts/langfuse/langfuse_eval.py`，当前覆盖离线数据集批跑，线上全量仍是目标态。
- Judge 模型：经 DeepSeek 兼容端点调用，默认 `deepseek-v4-flash`（评估成本考量，可配置）；Judge 提示词在 `app/prompts/judge/`，纳入版本管理。
- 输出契约：`{pass, score(0-1), reason}`。若要驱动"业务方只看低置信"队列，需另定 score 阈值。
- 标注平台：LangFuse Annotation Queue（与 trace 天然关联，零额外开发）；标注队列与回流脚本待线上标注启动时建设，数据集需新增标注来源字段（judge / business / engineer）。

## 备选方案

仅工程师标注（不懂业务）/ 仅业务方（规模上不去）/ 仅 Judge（领域常识不足、偏差累积）/ **业务方 + Judge 混合（已选）**。

## 后果

- 业务方每周投入是线上标注闭环的硬依赖，启动前须与业务方明确承诺。
- Judge 模型可替换；评分批次须记录提示词版本以保持可比。
