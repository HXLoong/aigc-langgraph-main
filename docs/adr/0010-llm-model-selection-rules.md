# Qwen 三型号分工：structured output 节点强制 standard

> **2026-08-27 修订**：[ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) 起全部环境统一
> DeepSeek-V4-pro，standard / thinking / complex 事实合一，"thinking 不支持 structured
> output"的约束在 DeepSeek 下不成立。本文保留为历史背景；工厂函数的 import 语义与
> "structured output 默认走 standard 工厂"的习惯仍然沿用。

`app/llm/clients.py` 暴露三个 Qwen 客户端：standard（`qwen3-30B-A3B`）、thinking（`qwen-max-latest` + `enable_thinking=True`）、VL（多模态）。我们用以下选型规则约束开发者：

| 场景 | 必选型号 | 理由 |
|---|---|---|
| 任何使用 `with_structured_output(PydanticModel)` 的节点 | **standard** | thinking 模型不支持 structured output（function calling），返回非法 JSON 会让 Pydantic 解析失败 |
| ReAct Agent / 不走 structured output 的工具循环 | thinking | 利用思考能力做多步推理 |
| 输入含图片（截图、合同照片、含图 Excel） | VL | 唯一支持多模态 |
| 短文本路由判断（无 structured output 需求） | standard | 默认低延迟 |

**默认原则**：写新节点时**先用 standard**。只有当节点是 ReAct Agent 或确实不需要 structured output 时才考虑 thinking。

## Considered Options

- **全部 thinking 追求最高准确率**：`qwen-max-latest` 不支持 structured output，业务子图全部依赖 Pydantic 解析，无法工作。
- **全部 standard 追求一致性**：ticker ReAct Agent 这类多步推理场景准确率会下降。
- **按业务复杂度自由选（无规则）**：开发者直觉容易写"复杂参数抽取选 thinking"，撞上 structured output 限制后线上才暴露。

## Consequences

- 这条规则反直觉（"复杂场景反而用更小模型"），必须在 PR review 强制检查。`.claude/rules/langgraph-patterns.md` 应明确写入。
- 如果未来 `qwen-max-latest` 或新版 thinking 模型支持 structured output，这条规则需要重新评估并更新 ADR。
- structured output 节点的"准确率不够"问题不能靠换 thinking 解决，只能靠：(a) 拆解提示词为多阶段；(b) 给 standard 模型更精细的 few-shot；(c) 升级 standard 模型本身（如未来的 qwen3.5）。
- ReAct Agent 用 thinking 后，单次调用延迟和 token 浮动更大，必须配合 ADR-0004 的 trace 监控工具调用次数。
- VL 模型与 standard / thinking 不能混用：含图请求**整条链路**（含意图分类）都要走 VL，不能"先 standard 判定有图再切 VL"——切换会丢失上下文且增加延迟。
