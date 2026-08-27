# ADR 0020 · 全量统一 DeepSeek-V4-pro（取代开发/现场双模型分立）

- 状态：已采纳
- 日期：2026-08-27
- 取代：[ADR 0018](./0018-dev-qwen-prod-deepseek-llm-split.md)（双模型分立）；修订 [ADR 0010](./0010-llm-model-selection-rules.md)（Qwen 三型号分工）
- 起源：Tony 2026-08-27 指示"全部使用 DeepSeek-V4-pro"
- 作者：图灵科技 + Tony

## 上下文

ADR 0018 规定"开发期 Qwen / 客户现场 DeepSeek-v4-pro"双轨制，代价是：

- M2 的 92.5% PASS baseline 只对 Qwen 有效，DeepSeek 上要靠 C1.19 单独重建
- prompt 适配、行为漂移排查都要在两套模型上做两遍
- 开发环境验证过的行为不能直接外推到现场

M3.3 进入真后端 golden 回归 + 业务方 sign-off 阶段，评估结论必须与现场同口径。
2026-08-27 Tony 决定：**开发 / 测试 / harness 评测 / 现场生产全部统一使用 DeepSeek-V4-pro**。

## 决策

### 1. 模型统一

所有 LLM 调用（standard / thinking / structured / complex 四个工厂）统一 `deepseek-v4-pro`。
切换仍只通过 `.env`，代码不硬编码 vendor（`QWEN_*` 是历史通用前缀，沿用 ADR 0018 的命名妥协）：

```dotenv
QWEN_API_BASE=https://api.deepseek.com/v1
QWEN_MODEL_STANDARD=deepseek-v4-pro
QWEN_MODEL_THINKING=deepseek-v4-pro
QWEN_MODEL_COMPLEX=deepseek-v4-pro   # 必须显式设置：config.py 默认值是 qwen 模型名，不覆盖会 404
```

### 2. vendor 适配层（app/llm/clients.py，2026-08-27 落地）

DeepSeek 的 OpenAI 兼容接口与 Qwen/dashscope 有两处硬差异，已在统一工厂集中适配，
**节点层不得重复处理**（回归测试：`tests/test_llm_clients.py`，13 用例）：

| 差异 | 现象 | 适配 |
|---|---|---|
| 关闭思考模式参数不同 | DeepSeek 静默忽略 Qwen 的 `enable_thinking=False`，默认仍开思考（实测 reasoning token 非零，延迟不可控） | `_thinking_off_extra_body()`：DeepSeek 用 `{"thinking": {"type": "disabled"}}`，Qwen 保持 `enable_thinking=False` |
| 不支持 `response_format=json_schema` | 400 "This response_format type is unavailable now"；而 langchain_openai 的 `with_structured_output` 默认走 json_schema，全库 43 处调用均不传 method | `_ChatLLM.with_structured_output`：模型名以 deepseek 开头且未显式传 method 时，自动降级 `method="function_calling"`（实测可用；`json_mode` 会漂移字段名，不采用） |

### 3. VL 视觉模型例外

DeepSeek 暂无视觉模型。`get_qwen_vl` 仍指向 `qwen-vl-max-latest`，但 base 已切
DeepSeek，**当前不可用**。M3 未使用图片链路（place_order_image / image_recognize 为
P2 增量节点）；启用时需给 VL 工厂单独配 Qwen base（新增独立 env var），届时修订本 ADR。

### 4. 对 ADR 0010 选型规则的影响

- standard / thinking / complex 三型号**事实合一**（同一模型、同为关思考）；四个工厂函数与
  import 语义保留，未来按节点切不同模型时只改 `.env` 或对应工厂
- ADR 0010 的核心约束"thinking 模型不支持 structured output"在 DeepSeek 下不再成立
  （function calling 全模型可用），该规则降级为历史背景；"structured output 节点默认走
  standard 工厂"的习惯保留，不强制回改存量代码

## 替代方案

- **维持 ADR 0018 双轨制**：放弃。双口径评估成本在 M3.3 sign-off 阶段不可接受，且
  客户现场只认 DeepSeek 上的表现。
- **开发期用 DeepSeek 其他型号（如更便宜的非 pro）**：放弃。引入新的行为漂移维度，
  与"同口径"目标矛盾。

## 后果

### 正面

- 开发 / 评测 / 现场单一口径，golden 回归结论可直接外推现场
- C1.19 从"一次性 smoke 验证"升级为常态：所有日常评估天然在 DeepSeek 上进行
- vendor 差异集中在 clients.py 一处，节点代码零改动（43 处 `with_structured_output` 未动）

### 负面 / 风险

- **baseline 作废**：Qwen 口径的 92.5%（mock）/ 84.6%（真 LLM）不再是对照基线，
  需在 DeepSeek 上重跑 `scripts/langfuse_eval.py` 重建（沿用 ADR 0018 C1.19 红线思路）
- 开发期 API key 计费与管理归属需要与客户/内部重新明确（原 ADR 0018 的"key 边界清晰"优势失效）
- 开发环境依赖公网 DeepSeek API 的可用性与延迟
- 长提示词节点（swap/place_order ≈ 40K tokens）在 DeepSeek 上的 P95 延迟需重新测量
  （ADR 0017 量化指标同步在 DeepSeek 上重建）

### 回退路径

- `.env` 中保留 Qwen 配置注释，切回只改 §3 四行
- `_thinking_off_extra_body` / `_ChatLLM` 按模型名分支，双 vendor 兼容，回退无需改代码

## 关联

- ADR 0018 · 开发 Qwen / 现场 DeepSeek 双模型分立（被本 ADR 取代）
- ADR 0010 · Qwen 三型号分工（被本 ADR 修订为历史背景）
- ADR 0017 · M4 金丝雀退出门量化指标（在 DeepSeek 上重新测量）
- ADR 0001 D5 · DeepSeek 适配类 prompt 改写仍须独立标记（沿用 ADR 0018 约定）
