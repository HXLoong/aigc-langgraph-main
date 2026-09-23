# ADR 0010 · Qwen 三型号分工：structured output 节点强制 standard

- 状态：**历史背景**（选型口径已被 [ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) 取代：全部环境统一 DeepSeek-V4-pro，三型号事实合一）
- 日期：2026-05-10
- 修订：2026-08-27 深度改写为现状口径（对照代码核查）
- 作者：图灵科技 + Tony

## 原决策（历史）

开发期 Qwen 时代按型号分工：standard（`qwen3-30B-A3B`）/ thinking（`qwen-max-latest` + `enable_thinking=True`）/ VL（多模态），选型规则：

| 场景 | 必选型号 | 理由（当时）|
|---|---|---|
| 任何 `with_structured_output(PydanticModel)` 节点 | **standard** | thinking 模型不支持 structured output |
| ReAct Agent / 工具循环 | thinking | 多步推理 |
| 输入含图片 | VL | 唯一多模态，含图请求整条链路走 VL |
| 短文本路由 | standard | 低延迟 |

## 现状（2026-08-27）

- 工厂已从"三个客户端"演进为 **6 个**：`get_qwen_standard` / `get_qwen_thinking` / `make_qwen_thinking`（跨 event loop 非缓存）/ `get_qwen_structured` / `get_qwen_complex` / `get_qwen_vl`（`app/llm/clients.py`）。
- 模型实体以 `.env` 为准，现全部 `deepseek-v4-pro` 且**统一关闭思考**（含 thinking 工厂——原表"thinking + enable_thinking=True"已双双反转）。
- "thinking 不支持 structured output"的核心约束在 DeepSeek 下**不成立**（function calling 全模型可用，0020 §2 适配层处理）。
- VL：曾全库零调用点；**2026-09-22 复核**：`app/subgraphs/swap/multimodal.py` 已调用 `get_qwen_vl`（swap 图片 / Excel 分支），现场需单独配置视觉模型（0020 §3 修订）。
- 原 Consequences 承诺"规则写入 `.claude/rules/langgraph-patterns.md`"**未执行**（该文件无此条目）。

## 实现偏离（历史事实，必须记录；2026-08-27 已裁决）

**本 ADR 的强制规则从未在代码中被执行**：`get_qwen_standard` 业务侧零调用（2026-09-18 起曾由 ~~`app/graph/instructions.py`~~ 多指令拆分调用它；本分支已退役该编排）；20 个 `with_structured_output` 调用点实际分布为 **thinking 15 / structured 2 / complex 1 / standard 0**（`swap/intent.py` 的 docstring 甚至自称遵守本规则，实际调 thinking 工厂）。

**裁决（2026-08-27）**：选 (b) 追认——thinking 工厂为 structured output 的**事实默认**，本规则正式废止。**分化前置纪律**：未来按工厂分化模型前，必须先做一个'调用点统一 PR'把 20 处 structured output 调用点归位到语义正确的工厂，否则 15 个节点会静默跟随 thinking 工厂拿到错误模型。

## 备选方案（历史论证）

- **全部 thinking**：当时 qwen-max 不支持 structured output，无法工作。
- **全部 standard**：ReAct 多步推理准确率下降。
- **按复杂度自由选**：开发者直觉易撞 structured output 限制。

## 后果（现状口径）

- 保留价值：四个工厂函数的 **import 语义**（standard/thinking/structured/complex 的意图分工）仍是未来按节点分化模型时的挂载点——前提是先解决上述偏离。
- structured output 准确率问题的解法不变：拆提示词、精细 few-shot、升级模型本体——不靠切 thinking。
