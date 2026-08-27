# ADR 0018 · 开发期 Qwen / 客户现场 DeepSeek-v4-pro 双模型分立

- 状态：**已被 [ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) 取代**（2026-08-27 起全部环境统一 DeepSeek-V4-pro；本文压缩为历史存根）
- 日期：2026-05-12
- 修订：2026-08-27 按取代关系改写为存根（wayfinder map #138 / 核查 #142）
- 作者：图灵科技 + Tony

## 原决策（历史）

客户要求生产用外部云 DeepSeek-v4-pro，而开发不能共用客户 key（计费/安全/网络）。故采用**双轨制**：开发/测试/harness 用 Qwen（standard `qwen3-30B-A3B` / thinking `qwen-max-latest` / VL），客户现场用 DeepSeek-v4-pro；通过 env var 切换，不硬编码 vendor。

**为何被取代**：双轨制的代价（92.5% baseline 只对 Qwen 有效、prompt 适配做两遍、开发结论不能外推现场）在 M3.3 真后端回归 + 业务方 sign-off 阶段不可接受，2026-08-27 Tony 决定全量统一 DeepSeek-V4-pro（详见 ADR 0020）。

## 仍有效的历史事实（0020 的上下文依赖，勿删）

1. **`get_qwen_*` 函数命名保留**：为避免大面积 import 修改，工厂函数名沿用 `qwen` 前缀（事实上误导但成本最低）；M4 全量上线后再做 `get_llm_*` 重命名 PR——待办仍未清。
2. **env var 改名提案（`LLM_API_BASE` 等）从未落地**：`app/config.py` 与 `.env` 至今全是 `QWEN_*` 前缀。这是 0020 §1 "沿用 ADR 0018 的命名妥协"一语的实际出处——本 ADR 原文写的是"替代 QWEN_*"，未执行。
3. **C1.19（DeepSeek smoke 验证 gate：B 桶 ≥20 条，PASS 红线 83.25%）已于 2026-05-12 标记跳过**（`docs/m3-m4-roadmap.md`，理由"OpenAI 兼容接口，行为差异风险低"）。事后证明该判断是误判：全量切换时暴露两处硬差异（关思考参数、`response_format=json_schema` 不支持），由 `app/llm/clients.py` 的适配层解决（0020 §2）——"接口兼容所以无需改代码"的前提被证伪。
4. 双轨期的具体型号表与 API key 边界安排转为历史，现行配置见 0020 §1。

## 关联

- [ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) · 取代本 ADR
- [ADR 0010](./0010-llm-model-selection-rules.md) · Qwen 三型号分工（同为历史背景）
- [ADR 0017](./0017-m4-canary-quantitative-exit-gate.md) · 量化指标在 DeepSeek 上重建
