# ADR 0010 · Qwen 三型号分工（历史存根）

- 状态：**已被 [ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) 取代**（2026-08-27 全部环境统一 DeepSeek-V4-pro）
- 日期：2026-05-10
- 作者：图灵科技 + Tony

## 原决策

开发期按 Qwen 型号分工：structured output 节点强制用 standard 型号（当时 thinking 型号不支持结构化输出），多步推理用 thinking，含图片用 VL。

## 为何被取代

- 全部环境统一为 DeepSeek-V4-pro 且关闭思考模式，standard / thinking / complex 三型号事实合一；
- "thinking 不支持 structured output"在 DeepSeek 下不成立（function calling 全模型可用）；
- 该强制规则在代码中从未被执行，2026-08-27 已废止。

## 仍有效的事实

- 工厂函数名（`get_qwen_standard` / `get_qwen_thinking` / `get_qwen_structured` / `get_qwen_complex` / `get_qwen_vl`，见 `app/llm/clients.py`）作为未来按节点分化模型的挂载点保留。
- **分化前置纪律**：将来若按工厂切换不同模型，须先做一次"调用点归位"改动，把 structured output 调用点对齐到语义正确的工厂，否则大部分节点会静默跟随 thinking 工厂。
