# ADR 0018 · 开发期 Qwen / 客户现场 DeepSeek 双模型分立（历史存根）

- 状态：**已被 [ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) 取代**（2026-08-27 全部环境统一 DeepSeek-V4-pro）
- 日期：2026-05-12
- 作者：图灵科技 + Tony

## 原决策

客户生产要求 DeepSeek-v4-pro，开发不能共用客户 key，因此开发 / 测试用 Qwen、现场用 DeepSeek，通过环境变量切换，代码不硬编码 vendor。

## 为何被取代

双轨制导致评测基线只对 Qwen 有效、提示词适配做两遍、开发结论无法外推现场。2026-08-27 统一为 DeepSeek-V4-pro。

## 仍有效的事实

- 工厂函数（`get_qwen_*`）与环境变量（`QWEN_*`）沿用 `qwen` 前缀，属历史命名妥协，重命名待办未执行。
- 教训：当年以"OpenAI 兼容接口、风险低"为由跳过了 DeepSeek 冒烟验证，后续全量切换暴露两处硬差异（关闭思考参数、不支持 `json_schema` 结构化输出），由 [ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) §2 适配层解决。"接口兼容 ≠ 行为兼容"。
