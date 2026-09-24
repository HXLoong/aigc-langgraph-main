# ADR 0020 · 全量统一 DeepSeek-V4-pro

- 状态：已采纳（图片 / Excel 链路另配视觉模型，见 §3）
- 日期：2026-08-27
- 关系：取代 [ADR 0018](./0018-dev-qwen-prod-deepseek-llm-split.md)（双模型分立）与 [ADR 0010](./0010-llm-model-selection-rules.md)（Qwen 型号分工）
- 作者：图灵科技 + Tony

## 背景

此前"开发用 Qwen、现场用 DeepSeek"的双轨制，使评测基线只对 Qwen 有效、提示词适配要做两遍、开发结论无法外推现场。客户现场只认 DeepSeek 上的表现，评测结论必须与现场同口径。

## 决策

### 1. 模型统一

开发、测试、评测与现场生产的所有文本 LLM 调用统一使用 `deepseek-v4-pro`，并统一**关闭思考模式**。切换只通过 `.env`，代码不硬编码 vendor（环境变量沿用历史前缀 `QWEN_*`）：

```dotenv
QWEN_API_BASE=https://api.deepseek.com/v1
QWEN_MODEL_STANDARD=deepseek-v4-pro
QWEN_MODEL_THINKING=deepseek-v4-pro
QWEN_MODEL_COMPLEX=deepseek-v4-pro   # 必须显式设置，默认值不是 DeepSeek 模型名
```

### 2. vendor 适配集中在一处（`app/llm/clients.py`）

DeepSeek 的 OpenAI 兼容接口与 Qwen 有两处硬差异，统一在工厂层适配，**节点层不得重复处理**（回归测试 `tests/test_llm_clients.py`）：

| 差异 | 现象 | 适配 |
|---|---|---|
| 关闭思考的参数不同 | DeepSeek 忽略 Qwen 的 `enable_thinking=False`，默认仍思考，延迟不可控 | DeepSeek 传 `{"thinking": {"type": "disabled"}}` |
| 不支持 `response_format=json_schema` | 结构化输出默认走 json_schema，直接 400 | 模型为 DeepSeek 且未显式指定时，自动改用 `function_calling`（`json_mode` 会漂移字段名，不采用） |

### 3. 视觉模型例外

DeepSeek 暂无视觉模型。互换图片 / Excel 链路（`app/subgraphs/swap/multimodal.py`）经 `QWEN_MODEL_VL` 单独配置视觉模型；现场未配置时该链路不可用，部署 checklist 须明确此项。

## 备选方案

- **维持双轨制**：双口径评估成本不可接受。
- **开发期用更便宜的 DeepSeek 非 pro 型号**：引入新的行为漂移维度，与"同口径"目标矛盾。

## 后果

- 正面：开发 / 评测 / 现场单一口径，数据集回归结论可直接外推现场；vendor 差异集中在一处，节点代码零改动。
- 负面：旧 Qwen 口径的评测与延迟基线作废，需在当前模型上重建（ADR 0030 D3）；开发环境依赖公网 DeepSeek API 的可用性与计费安排。
- 回退：`.env` 切回 §1 四行即可，适配层按模型名分支，双 vendor 兼容，无需改代码。
