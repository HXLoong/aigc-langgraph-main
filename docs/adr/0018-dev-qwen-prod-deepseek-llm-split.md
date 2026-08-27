# ADR 0018 · 开发期 Qwen / 客户现场 DeepSeek-v4-pro 双模型分立

- 状态：**已被 [ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) 取代**（2026-08-27 起全部环境统一 DeepSeek-V4-pro）
- 日期：2026-05-12
- 起源：grill-with-docs（M3/M4 路线图 C1.10）
- 作者：图灵科技 + Tony

## 上下文

M3 阶段进入客户现场前，需要明确生产环境用什么大模型。

历史现状：
- 开发期使用 Qwen 系列（ADR 0010 规定的 standard / thinking / VL 三型号分工）
- `app/llm/clients.py` 全部围绕 Qwen 配置，通过 `langchain_openai.ChatOpenAI` 调用（OpenAI 兼容接口）
- M2 的 92.5% PASS baseline 是在 Qwen 上测得

客户现场约束（2026-05-12 Tony 同步）：
- 客户要求生产环境使用 **外部云 DeepSeek-v4-pro**
- 客户内网可访问公网，DeepSeek API endpoint 可直连
- DeepSeek-v4-pro 是 **OpenAI 兼容接口**

冲突点：
- 92.5% PASS 是在 Qwen 上验证的；切换到 DeepSeek 后行为可能漂移
- 但不可能让开发团队在客户现场或客户的 DeepSeek API 上做每日开发（key 管理、计费、网络隔离都是麻烦）

## 决策

**开发期与生产期使用不同 LLM 后端，通过 env var 切换：**

### 开发 / 测试 / harness 评测

- **Qwen 系列**（按 ADR 0010）：
  - standard：`qwen3-30B-A3B`
  - thinking：`qwen-max-latest` + `enable_thinking=True`
  - VL：`qwen-vl-max-latest`
- API key 由图灵科技团队管理
- 用于：所有 PR 开发、harness golden 回归、本地 smoke、CI

### 客户现场生产

- **DeepSeek-v4-pro**（OpenAI 兼容接口）
- 上下文窗口：≥ 128K（假设值，Tony 与客户最终确认）
- API key 由客户提供（具体形式 Tony 在 C1.19 完成后落实）
- 网络：客户内网可访问公网，直连 DeepSeek API endpoint
- 用于：客户现场部署、shadow 双跑、金丝雀、全量上线

### 切换机制

通过 `app/config.py` 的 env var 控制，**不在代码里硬编码**：

- `LLM_API_BASE`（替代 `QWEN_API_BASE`）
- `LLM_API_KEY`（替代 `QWEN_API_KEY`）
- `LLM_MODEL_STANDARD` / `LLM_MODEL_THINKING` / `LLM_MODEL_VL`

`app/llm/clients.py` 的函数名保留 `get_qwen_*` 形式以减少重写成本（OpenAI 兼容接口下函数实现不需要改），但**注释和文档**应明确这是"标准模型客户端"而非"Qwen 客户端"。

> **历史命名遗留**：函数名 `get_qwen_*` 在切换 DeepSeek 后**事实上是误导性**的，但出于"避免大面积 import 修改"的考虑，本 ADR 选择保留命名。**未来重命名** PR 可以集中做（M4 全量上线后），不在 M3 阶段做。

## 双模型行为差异的验证机制

引入 C1.19：**DeepSeek smoke 验证任务**（在阶段 1 子线 1B 末尾）。

约束：
- 用 DeepSeek API key 跑 **B 桶 ≥ 20 条代表性 case**
- 对比 Qwen baseline 的 PASS 率和输出字段差异
- **红线**：PASS 率 < Qwen × 0.9（即 92.5% × 0.9 = 83.25%）
- 红线触发后：按节点跑回归 + 适配 prompt（这些 prompt 改写**不**计入 ADR 0001 D5 已登记的"重构期允许改写"范围，是独立的"模型适配"改写，必须在 PR 描述中明确标记）

C1.19 必须在阶段 2 D2.1 真后端联调启动之前完成——否则真后端联调可能撞上"DeepSeek 输出不符合 Java 后端契约期望"的连环故障。

## 替代方案

### 全 DeepSeek（开发期也用 DeepSeek）

放弃：
- 客户 key 不能轮流给所有开发者使用（计费 / 安全 / 网络）
- 开发速度受网络抖动影响
- 用客户 key 跑 CI = key 暴露给 CI runner 的风险

### 全 Qwen（说服客户接受 Qwen）

放弃：客户已明确要求 DeepSeek，不接受 Qwen 论证。

### 在客户现场镜像部署 DeepSeek 私有化版本

放弃：DeepSeek 私有化版本部署成本远高于云调用，且客户已确认能访问公网，没必要私有化。

## 后果

### 正面

- 开发速度不受客户网络约束
- API key 管理边界清晰（开发 = 我方，生产 = 客户）
- harness golden baseline 与开发环境一致，回归可信

### 负面

- 92.5% PASS 数字**只对 Qwen 有效**；DeepSeek 上的 baseline 由 C1.19 重新建立
- prompt 在切到 DeepSeek 后可能需要小幅适配（字段顺序 / JSON 格式细节 / 中文指令理解差异）
- 阶段 4 的 ADR 0017 量化指标在 DeepSeek 上测，不能直接复用 Qwen 期间数据
- `get_qwen_*` 函数命名误导，未来需要重命名 PR

### 风险监控

- **C1.19 红线触发率监控**：若 PASS 率 < 83.25%，必须在阶段 1 内修补到位
- **阶段 4 量化指标**（5xx / cascade fail / P95 延迟 / 严重错例）在 DeepSeek 上重新测量，作为正式 baseline

### 后续行动

- M4 全量上线后：发起重命名 PR，把 `get_qwen_*` 改为 `get_llm_*` 或 `get_chat_*`
- 配置项 env var 命名按本 ADR：`LLM_API_BASE` 等
- C1.19 是阶段 2 启动前的 gate

## 关联

- ADR 0010 · Qwen 三型号分工（开发期沿用）
- ADR 0017 · M4 金丝雀退出门量化指标（在 DeepSeek 上测量）
- ADR 0001 D5 · 提示词改写授权范围（DeepSeek 适配改写**不属于** D5 范围，必须独立标记）
- 路线图 C1.10 / C1.19（`docs/m3-m4-roadmap.md`）
