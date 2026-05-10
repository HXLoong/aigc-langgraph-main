# ADR 0015 · 一级路由：规则前置 + LLM 兜底

- **Status**: Accepted
- **Date**: 2026-05-10
- **Deciders**: Tony
- **Skill**: 由 grill-with-docs 复盘 M2 计划时决定

## Context

主图入口需要把客户原话路由到 `product_type` 一级类目，进入对应子图。M1 阶段 ingest 节点是占位（默认 `swap`），M2 必须实现真路由。

复盘 golden.jsonl 30 条与 Java 后端约定后，发现：

- **ProductType 真值集 4 个**（不是 ADR 0001 D6 / state.py 写的 3 个）：`swap` / `option` / `option_close` / `unknown`
- **业务硬约定**：订单号 prefix 是唯一识别符——`H-`（swap）/ `OPT-`（option）/ `CO-`、`OPTG-`（option_close）。g029 暴露"订单号 over 关键词"优先级（"互换订单 CO-... 帮我平仓" → option_close）
- **强信号 case 占比近半**：30 条 golden 中约 14 条含订单号或单一明确关键词
- **口语化 case 必须 LLM**：g010 "做 纳指 一笔互换"、g020 "我有哪些期权持仓"等

## Decision

`ingest` 保持薄入口（仅 inputs → state）；新增 `intent_route` 独立节点（按 ADR 0001 D6 已规划），按以下三层处理：

### 第 1 层 · 规则前置（最高优先级）

**订单号正则匹配**（命中即返回，跳过其余）：

| 正则 | → product_type |
|---|---|
| `H-\d{8}-[A-Z0-9]+` | swap |
| `OPT-\d{8}-[A-Z0-9]+` | option |
| `CO-\d{8}-[A-Z0-9]+` 或 `OPTG-[A-Z0-9]+` | option_close |

**关键词优先级表**（订单号未命中时遍历，命中即 break）：

| 优先级 | 关键词 | → product_type |
|---|---|---|
| 1 | `平仓` / `平.*全部` / `持仓` | option_close |
| 2 | `期权` / `询价` / `雪球` | option |
| 3 | `互换` / `TRS` / `总收益互换` | swap |

关键词表抽到 `app/prompts/router/keywords.yaml`（不在代码里硬编码），业务方可单文件维护。

### 第 2 层 · LLM 兜底

仅在规则全部未命中或多 product 冲突时调用：

- `load_prompt("router", "product_type")` —— ~80 行，4 分类 + few-shot 6 条
- `with_structured_output(ProductTypeOutput)` —— `Literal["swap","option","option_close","unknown"]`
- 模型选 **standard**（按 ADR 0010）

### 第 3 层 · unknown 兜底

LLM 也判定 unknown 或异常 → `product_type = "unknown"` → 主图走 fallback render（友好回复 + 写 trace + 不进任何子图）。

### 连带 schema 订正

```python
# app/graph/state.py
ProductType = Literal["swap", "option", "option_close", "unknown"]
```

`app/graph/main.py` 的 `conditional_edges` 加 `option_close` / `unknown` 分支（M2 实施 intent_route PR 时一并修）。

## Alternatives

### A · 纯 LLM 分类

**做法**：ingest → 一次 LLM 调用 → 子图。

**风险**：
- 30 条 golden 中近半是强信号 case，纯 LLM 浪费调用，延迟 +200-500ms
- "订单号 over 关键词" 是业务硬约定，写进 prompt 让 LLM 学，每次调用有 5-10% 概率违反硬约定
- 抖动让"幂等可解析"的输入产生不一致路由

**为什么不选**：性能与一致性双输。

### C · 纯规则

**做法**：仅订单号 + 关键词，没命中即 unknown。

**风险**：
- 处理不了 g010 "做 纳指 一笔互换"（关键词命中但有歧义）
- 处理不了客户口语简写（如"做空 茅台 互换 买 100w"）
- unknown 比例会过高，用户体验差

**为什么不选**：覆盖面不够。

## Consequences

### 积极后果

- **强信号 case < 1ms 出结果**——硬约定 100% 一致，无 LLM 抖动
- **LLM 仅处理真歧义**——~50% 流量省一次 LLM 调用，成本与延迟双优
- **关键词表外置 yaml**——业务方可单文件维护，不走代码 PR
- **trace 可分析"规则 vs LLM"决策来源**——后续可统计哪些 case 落到 LLM，反哺规则覆盖率优化

### 消极后果与缓解

| 后果 | 缓解 |
|---|---|
| 规则代码每加一个 product 都要改 | 业务扩展时不可避免；ADR 0007 已定独立子图判断流程 |
| 关键词冲突时（多 product 同时命中）需要规则消歧 | 默认走 LLM 兜底；冲突频次过高时考虑加二级关键词组合规则 |
| 订单号 prefix 业务方未来若变更 | 走 ADR 决策 + 灰度迁移；正则集中在 `intent_route.py` 一处易改 |

## Related

- **ADR 0001 D6** · 主图组装与一级路由——本 ADR 是其精确化
- **ADR 0010** · LLM 模型选择——intent_route LLM 兜底走 standard
- **ADR 0014** · LangFuse trace——节点 trace 写入"规则命中 vs LLM 兜底"决策来源
- **ADR 0007** · 独立子图 vs 新意图判断——未来扩展 product 时遵循
