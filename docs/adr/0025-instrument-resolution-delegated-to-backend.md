# ADR 0025 · 标的识别职责移交 Java 后端：LangGraph 只提取原文候选

- 状态：已采纳（2026-09-20 落地，commit `2f9ce65`；本篇为 2026-09-22 追认记录，决策本体已由用户当日指定）
- 日期：2026-09-20（记录：2026-09-22）
- 起源：用户按 `tmp/场外交易-test (20).yml` 指定主工作流职责边界；执行说明见 [docs/backend-instrument-boundary.md](../backend-instrument-boundary.md)
- 取代：[ADR 0008](./0008-ticker-resolution-as-react-agent.md)（标的识别在 LangGraph 内编排，含 2026-08-27 裁决的"确定性编排 + LLM 定点兜底"形态）
- 修订：[ADR 0001](./0001-rewrite-app-with-harness-first.md) D4（"标的查询职责归 LangGraph"）与 D6（ticker 子图）、[ADR 0012](./0012-restore-backend-http-for-securities-instrument.md)（后端为标的真源的结论保留，LangGraph 侧调用点退役）、[ADR 0024](./0024-langgraph-native-rearchitecture.md) D2（`tickers` 业务对象）与 D3（ticker 真子图）、[ADR 0023](./0023-prompt-as-code-langgraph.md) D5 第三批（ticker 4 个 PromptSpec）；[ADR 0013](./0013-load-dynamic-inference-prompt-fragment.md) 的残余引用随之清空
- 作者：图灵科技 + Tony

## 上下文

标的识别在本仓经历了三种形态：ReAct Agent（ADR 0008 原决策，从未接线）→ 确定性 resolver + GOATS 二次校验（2026-08-27 裁决）→ 2026-09-17 按 ADR 0024 D3 做成真子图（`Send` 三路 LLM 并行 + GOATS 检索 + LLM 排序）。三种形态共同的前提是"LangGraph 本地产出证券代码，且必须 `from_goats=True`"。

这一前提带来三类持续成本：

1. **业务清单长进代码**：`infer_code.md` 的"名称 → windCode"事实清单、`tokenize.md` 501 行分词规则，都是 CLAUDE.md P0 红线（禁止硬编码业务数据字典）的反例，且随新 ETF / 指数发行持续腐烂。
2. **双实现漂移**：ADR 0012 已证明"把后端规则搬进 LangGraph"会丢失非平凡业务规则；本地三路 LLM 推断 + 排序与 Java 侧标的工具是同一职责的两份实现。
3. **成本与幻觉面**：每次下单 / 询价多 3 路批量 LLM 调用；LLM 推断结果需 GOATS 二次校验才可信，校验失败时本地生成"零命中 / 消歧卡"会阻断本应由后端判定的请求。

2026-09-20 用户指定的 Dify 主工作流把标的工具调用放在 Java 侧，LangGraph 只提取原文并调用业务接口。

## 决策

### D1 · LangGraph 只提取原文候选与用户选择

- 保留用户的证券表达原文（代码或名称）与引用候选中的用户选择（序号 / 直接换标的），交给业务接口；**不补代码、不计算近月合约、不查证券池、不做本地预检、不因本地未匹配而阻止后端**。
- 引用序号选择只映射到对应订单的引用候选；用户直接换标的时保留其新表达，即使不在候选列表中。订单范围和字段证据仍须一致（[ADR 0027](./0027-field-evidence-contract.md)）。
- 来源记录是"用户原文"或"引用"，**不得标记为 `from_goats=True`**；`TickerCandidate.from_goats` 降为旧 checkpoint / HTTP 兼容字段（`app/graph/state.py`）。

### D2 · 数据流

```
互换文本      → 原文候选 → 证据校验 / 归一化 → 对手或引用标的选择 → POST /swap-order/operate
图片 / Excel  → 转写 / 逐行候选 → 证据校验 / 归一化 → POST /swap-order/operate
普通期权询价  → 原文候选 → 证据校验 / 归一化 → POST /financial-orders/operate
```

Java 负责精确匹配、标的工具调用、多候选处理、权限与市场校验；业务回复沿用后端回执契约（[ADR 0026](./0026-request-idempotency-uncertain-receipts-reconciliation.md) D3）。

### D3 · 兼容边界

- Java DTO 与业务 HTTP 路径不变：`placeOrderWindCode` / `stockCode` 可承载原始名称或代码。
- HTTP 输出 `tickers` 保持空列表兼容字段，**不能解释为后端未匹配**；旧 checkpoint 的 `tickers` / `ticker_hitl_candidates` 继续可读、在 `ingest` 清理；本地不再生成证券零命中回复或 ticker 消歧卡。
- 15 个业务 PromptSpec 保留固定 system；生成的当前时间与机器人名称名单不再送入 LLM。

### D4 · 删除与遗留清单（commit `2f9ce65`）

| 处置 | 内容 |
|---|---|
| 删除 | `app/subgraphs/ticker/`（`graph` / `resolver` / `tools` / `models` / `context` / `__init__`，共 6 文件）、`app/prompts/ticker/`（`infer_code` / `judge_type` / `rank` / `tokenize`）、`tests/subgraphs/ticker/`（14 个测试）、~~`tests/subgraphs/swap/test_ticker_binding.py`~~、~~`scripts/probe_ticker_e2e.py`~~（删除线 = 已删除路径，供 lint 跳过） |
| 收缩 | PromptSpec 注册表 20 → **15**（ADR 0023 D5 第三批的 ticker 4 个随之注销）；`swap/select_ticker.py` 改为只映射引用选择 |
| 保留（2026-09-23 裁决） | `app/tools/ticker_client.py` 继续供 `scripts/local_eval.py` 的 `LocalJavaMessages.prepare` 获取按群、用户、业务类型授权的交易对手列表；交易图不调用它进行本地标的识别。相关客户端契约测试继续保留；`app/config.py` 的 `ticker_mysql_*` / `securities_instrument_*` 死配置已于 2026-09-22 清理 |
| 追加清理（2026-09-22） | 节点调试注册表 `app/node_execution/registry.py` 与工作台 `harness/node_registry.py` 移除 ticker 命名空间，并对齐 09-20 后的询价 / 平仓阶段（`inquiry_normalize` / `pc_candidates`）；此前主分支因该注册表仍 import 已删除的 ticker 子图而无法启动，CI 关闭期间未被发现 |

### D5 · 验证口径

- 业务回归检查**传给后端的原始表达**与**后端实际回复**；`case-021` 的旧 `winners` 断言迁移为完整后端卡片断言（仍须含 `标的代码：600519.SH`）。
- 历史工具数据中的 `winners` 不自动判为通过，也不从用户输入回填 `tickers`。
- 统一验收只使用显式 `tests/fixtures/categories`，不并入历史工具集。

## 备选方案

- **保留本地 resolver + GOATS 二次校验**（2026-08-27 裁决选项 b，ADR 0024 D3 真子图形态）：标的准确性最终仍由后端工具决定，本地实现只是多一份会漂移的副本，且业务清单必然进代码。否决。
- **本地只做 GOATS 精确匹配、不做 LLM 推断**：仍需本地维护匹配规则与零命中语义，且"本地未匹配即阻止后端"会误伤后端能识别的表达。否决。
- **原文透传 + 后端权威识别（已选）**：单一真源，代码与业务清单解耦。

## 后果

### 正面

- 标的准确性归后端单一真源，ADR 0012 的"与后端规则升级自动对齐"收益扩展到整个识别链路。
- 每请求少 3 路 LLM 调用；LLM 幻觉造成的错标的面归零；`app/prompts/` 不再承载任何证券事实清单。
- CLAUDE.md 核心原则 7 与"排查与修复流程"的标的行已同步为本 ADR 口径。

### 负面 / 风险

- 本地 eval 无法独立判定"标的是否正确"，只能断言原文透传与后端卡片；`--backend dry-run` 下标的相关 case 的判定能力下降。
- 排错必经后端标的工具日志；D 桶标的错例回流需要后端提供工具调用记录字段。
- `tickers` 兼容字段何时从 wire 移除、`ticker_client.py` 去留，均未决。

## 关联

- [docs/backend-instrument-boundary.md](../backend-instrument-boundary.md) · 执行说明与验证口径
- [ADR 0008](./0008-ticker-resolution-as-react-agent.md) · 被取代的本地识别决策（历史存根）
- [ADR 0012](./0012-restore-backend-http-for-securities-instrument.md) · 后端为标的真源的最初论证
- [ADR 0024](./0024-langgraph-native-rearchitecture.md) D3 · 被撤销的 ticker 真子图
- [ADR 0027](./0027-field-evidence-contract.md) · 原文候选的证据契约
