# ADR 0020 · 通用模型配置与 DeepSeek Pro 当前基线

- 状态：已采纳（通用配置与工厂已实现；切换模型后的真实链路验收单独执行）
- 日期：2026-09-24；修订：2026-09-28
- 关系：模型请求额度与附件边界见 [ADR 0031](./0031-single-model-request-per-message.md)，评测断言见 [ADR 0005](./0005-annotation-roles-judge-plus-business-spotcheck.md)
- 作者：图灵科技 + Tony

## 背景

模型可以随部署需要更换。配置变量和工厂函数使用厂商名称会误导维护者，也不能可靠地根据网关模型别名判断接口协议。采用通用名称与显式厂商适配；`deepseek-v4-pro` 保留为当前业务验收基线，切换模型需要重新验收，不能沿用旧模型结果。

## 决策

### 1. 通用配置与三个模型角色

凭据从环境变量读取，三个角色共用地址、密钥与厂商适配，各自独立配置模型标识：

```dotenv
LLM_PROVIDER=deepseek
LLM_API_BASE=https://your-openai-compatible-gateway/v1
LLM_API_KEY=your-llm-api-key
LLM_MODEL_STANDARD=deepseek-v4-pro
LLM_MODEL_THINKING=deepseek-v4-pro
LLM_MODEL_COMPLEX=deepseek-v4-pro
```

| 角色 / 工厂 | 当前用途 |
|---|---|
| `LLM_MODEL_STANDARD` / `get_llm_standard()` | 业务唯一解析器：一次联合识别产品、意图与候选 |
| `get_llm_structured()` | 复用 STANDARD 配置，不增加第四个角色 |
| `LLM_MODEL_THINKING` / `get_llm_thinking()` | 离线改写生成工具；角色名称不自动开启思考 |
| `LLM_MODEL_COMPLEX` / `get_llm_complex()` | 保留独立角色，当前业务链不使用 |

不建设运行时多模型编排或失败后切换模型。开发、评测和生产应使用待验收的同一业务模型与适配配置；数据集评分使用确定性断言，不另配 Judge 模型。业务回归能力预检只验证实际使用的 STANDARD，未使用角色不可用不应阻塞该回归。

### 2. 显式适配集中在模型工厂

`LLM_PROVIDER` 必填，可选值如下；厂商选择不读取模型名称或 URL 的特征。

| `LLM_PROVIDER` | 请求扩展 | 默认结构化输出方式 |
|---|---|---|
| `deepseek` | `thinking: {type: disabled}` | `function_calling` |
| `qwen` | `enable_thinking: false` | 保留当前 LangChain 默认方式 |
| `openai_compatible` | 不附加厂商私有字段 | `function_calling` |

调用方显式指定 `method` 时保留该选择。通用适配不会猜测网关的私有开关，部署时须核对目标接口能力与默认行为。

`app/llm/clients.py` 统一处理连接、结构化输出和厂商扩展；节点通过 `with_structured_output(PydanticModel)` 获取输出，不自行解析模型 JSON。SDK、图层与外层封装的模型重试均关闭；产品、意图和候选共用一次真实请求，失败不切换模型重试（ADR 0031）。

### 3. 直接迁移，不保留旧变量别名

| 旧变量 | 新变量 |
|---|---|
| `QWEN_API_BASE` | `LLM_API_BASE` |
| `QWEN_API_KEY` | `LLM_API_KEY` |
| `QWEN_MODEL_STANDARD` | `LLM_MODEL_STANDARD` |
| `QWEN_MODEL_THINKING` | `LLM_MODEL_THINKING` |
| `QWEN_MODEL_COMPLEX` | `LLM_MODEL_COMPLEX` |

删除已退役的 `QWEN_MODEL_VL`，另行填写 `LLM_PROVIDER`。旧工厂名也同步替换为 `get_llm_*`，不提供兼容别名。配置加载检测到任意 `QWEN_*` 键即失败，包括新旧同时存在的情况；错误只显示键名，不显示配置值。

迁移覆盖本地、部署模板和 CI。意图评测 CI 使用 secrets `LLM_API_BASE` / `LLM_API_KEY`、必填 variable `LLM_PROVIDER`，三个 `LLM_MODEL_*` variables 可选。远程配置由维护者迁移，修改工作流文件不代表远程密钥已经迁移。配置与模型工厂有缓存，更改环境变量后重启服务；不支持热切换。

### 4. 本阶段只处理文本与 Excel

- 图片暂不处理，不安排图片解析、OCR 或多模态接线。收到图片时在请求模型前提示改用文本或 Excel；混合输入不静默丢弃图片后处理其余内容。
- Excel 由代码读取单元格及来源，再通过同一次请求批量解析，不逐行请求模型。
- 不建设独立 VL 模型接线或按 VL 型号拆分告警。容量超限或输出无法承载全部订单时停止并提示调整输入；切换厂商不会自动扩大输入范围。

## 备选方案

- **保留厂商前缀与兼容别名**：容易出现新旧配置冲突和隐式回退，不采用。
- **只保留一个模型变量**：会丢失已保留的离线角色配置，本次不采用。
- **由模型名称推断厂商**：网关可能使用任意别名，不采用。
- **通用三角色配置 + 显式适配（已选）**：业务保持一次解析，独立配置模型标识与协议。

## 后果

既有部署必须同步迁移变量后再启动新版本。更换业务模型、厂商适配或网关后，重新验证结构化输出、准确率、失败率、成本与延迟，记录模型和 provider，不能直接继承旧基线。当前代码与离线专项验证状态、真实验收和远程配置待办统一见[工作计划](../work-plan.md)。
