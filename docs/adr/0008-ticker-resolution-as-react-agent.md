# ADR 0008 · 标的识别采用 ReAct Agent 而非固定链式流程

- 状态：**已裁决；标的识别职责已于 2026-09-20 迁至 Java**——[#154](https://github.com/GZTL-AI/aigc-langgraph/issues/154) 选项 (b)：确定性编排 + LLM 定点兜底（LLM 输出必须过 GOATS 校验），ReAct Agent 死代码已随 Dify DSL v2 迁移删除
- 日期：2026-05-10
- 修订：**2026-08-28 P1 ticker 域迁移落地**（Dify DSL v2 → LangGraph，见下方「迁移落地」段）；2026-08-27 深度改写为现状口径（wayfinder map #138 / 核查 #140）
- 作者：图灵科技 + Tony


## 当前边界（2026-09-20）

标的识别已由 Java 负责，见[标的识别后端边界](../backend-instrument-boundary.md)。
LangGraph 提取用户原文、处理引用候选选择并调用业务接口；标准代码、证券池和多候选判断由 Java 完成。
本地不再运行 ticker resolver，也不以 `from_goats=True` 作为提交前提；空 `tickers` 不表示零命中。

以下内容保留 2026-08 的历史裁决与实现记录；其中的管线、约束和后果不代表当前业务链路。

## 迁移落地（历史，2026-08-28）

~~`app/subgraphs/ticker/react_agent.py`~~ / ~~`graph.py`~~ 已删除（无任何生产/测试引用，`build_ticker_graph` 从未被主图接线）。`resolver.py` 重写为对齐 Dify 新 DSL「标的智能化推断和分词工具」（12 节点）+「标的相关性排序工具」的确定性编排管线：

```
tokenize（本地候选提取，暂代 P5 路由域的"候选标的提取"节点）
  -> format_candidate_list（空 -> 短路）
  -> asyncio.gather(infer_code_batch, split_ticker_keywords, judge_ticker_type)  # 3 路批量 LLM，一次调用处理全部候选
  -> merge_and_validate（确定性，交易所后缀正则校验完整标的，移植自 Dify code 节点）
  -> 逐 orgStr：GOATS securities-instrument/select 批量查询 + rank_candidates（LLM 排序过滤）
  -> TickerCandidate(from_goats=True)
```

- `completeness` 工具已删除，被 `merge_and_validate` 的确定性正则校验替代（Dify 新 DSL 同步删除了 completeness LLM 节点）。
- `_pick_winner` / `_pick_within_a_share` / `tools.pick_best` 三套互不一致的私有选优逻辑已删除，统一由 `rank_candidates`（LLM，对齐「大模型排序并过滤」提示词）承担排序 + 过滤职责。
- `infer_code` 从"单 keyword 同步线程调用 + 动态 prompt HTTP 拉取拼接"（ADR 0013）改为"全候选批量 async 调用 + 纯静态 `load_prompt()` 加载"，删除 5 分钟 LRU 缓存与 `_get_dynamic_prompt_cached` 链路。
- `from_goats=True` 硬约束**保持不变**——新管线在 GOATS 之后才产出 `TickerCandidate`，是本项目对 Dify DSL（本身不含 GOATS 校验步骤）的有意增强，详见下方「后果」段。
- 运行时约束 a/c（hard cap 8 步 / HITL 消歧）随死代码一并移除，未来若要接真 HITL 应走 [ADR 0006](./0006-hitl-interrupt-boundary.md) 的 interrupt 机制，而非复活 ReAct cap。

## 上下文（历史，供追溯原始决策动机）

场外衍生品场景大量涉及境外标的，两类硬识别难题：

1. **境外期货/商品的行业俗称**："伦铜" = LME 铜期货、"布油" = Brent 原油，无统一命名规范。
2. **跨市场的中文简称**："腾讯" = `00700.HK`、"50ETF" = `510050.SH`，需要简称→代码映射 + 上下文消歧。

原决策判断"识别步骤序列事先不确定"（短文本 1 步命中，俗称可能 5 步），因此选 **ReAct Agent + 工具循环**，否决了固定链式流程。

## ⚠️（历史，2026-08-27 核查快照，已被上方「迁移落地」段取代）落地现状：生产走确定性 resolver，ReAct 为死代码

核查（[#140](https://github.com/GZTL-AI/aigc-langgraph/issues/140)）确认：

- ~~`app/subgraphs/ticker/react_agent.py`~~ / ~~`graph.py`~~（2026-08-28 已删除，见上方「迁移落地」段）已构建但**主图从未接线**（`app/graph/main.py` 无 ticker 节点），仅测试里编译冒烟；
- 生产链路是 ~~`app/subgraphs/ticker/resolver.py`~~ 的**确定性 async 编排**：`resolve_ticker_full()` = tokenize（纯正则）→ 逐 keyword 查 GOATS → `_pick_winner` 规则选优 → 命中不足时 `infer_code` LLM 推断 + **GOATS 二次校验**。函数名 `_resolve_via_react_full` 只保留了命名，无 ReAct 语义——这正是原决策否决的"固定链式流程"形态（但比原链式方案多了 LLM 定点兜底）；
- 调用方是 **2 个节点**：`swap/place_order.py` 与 `option/extract_inquiry.py`（原文"swap/option/close 三子图共用"不成立——close 基于订单号平仓，明确不依赖标的识别）；
- 4 个 `@tool` 中业务链路只用 `tokenize` + `infer_code`；`completeness` / `rank` 零调用，被 resolver 的三套私有选优逻辑（`_pick_winner` / `_pick_within_a_share` / `tools.pick_best`）替代且互不一致；
- `app/prompts/ticker/{tokenize,completeness,rank,tokenize_v2}.md` 均为非活跃资产（tokenize 已纯规则化），仅 `infer_code.md` 在用。

**唯一完全兑现的核心约束：`from_goats=True`**——任何最终标的必须经 GOATS 回查确认（resolver 只在 GOATS 返回对象上构造 `TickerCandidate(from_goats=True)`；LLM 推断结果必须过 GOATS 二次校验才采纳）。CLAUDE.md 绝对约束持续有效。

**裁决选项**（[#154](https://github.com/GZTL-AI/aigc-langgraph/issues/154)）：(a) resolver 接回 ReAct Agent；(b) 新增 ADR 收窄本决策为"确定性编排 + LLM 定点兜底（LLM 输出必须过 GOATS 校验）"——现实现实际上是**更强的约束**，只是与本 ADR 记载相反且从未记录。

## 备选方案（历史论证）

- **固定链式四步**：覆盖 A 股没问题，俗称场景要大量判断胶水、短文本被迫跑全程。
- **LLM 单次结构化输出**：无法访问外部字典。
- **ReAct Agent（原选）**：路径长度自适应；代价是步数/token 浮动需单独监测。

## 运行时约束（历史核查）

| 原约束 | 现状 | 裁定 |
|---|---|---|
| a · Hard cap 8 步（`TICKER_MAX_STEPS=8`，recursion_limit=16），超限返回 `from_goats=False` 触发 cascade，步数入 trace | 常量在 `react_agent.py` 但 agent 不在业务链路，**cap 从不生效**；超限降级契约未实现；resolver 不写任何步数/调用次数 trace（原 Consequence 明列的观测指标缺失） | 死逻辑，随 [#154](https://github.com/GZTL-AI/aigc-langgraph/issues/154) 一并裁决（resolver 侧应有等价护栏：keyword 数上限 / 单次解析 LLM 调用上限） |
| b · GOATS 0 命中直接 fallback，不补 LLM 调用 | **反向实现**：primary 命中不足时调 `infer_code` LLM，再拿 LLM 答案做 GOATS 二次查询——设计更优（LLM 不可信输出被 GOATS 拦截）但与原文相反 | 建议随 (b) 选项改写为"LLM 推断 + GOATS 二次校验"约束 |
| c · 多命中消歧：分差 ≥ 10 自动选，否则 `interrupt(...)` HITL | 整条死逻辑：`RANK_AUTO_PICK_GAP` 定义后未使用、`needs_hitl` 恒 False、`hitl_pending` 恒空、render 消歧卡片为死路径；且 **relevanceScore 语义已反转（越小越相关，0=精确匹配）**，"选最高"在新语义下应为"选分数最低"。HITL 基础设施缺失与 [ADR 0006](./0006-hitl-interrupt-boundary.md) 同簇（[#153](https://github.com/GZTL-AI/aigc-langgraph/issues/153)） | 要么实现要么删 |

另：`infer_code` 实现为 raw invoke + 正则抽取 `<result>`/windCode（非原文的 `with_structured_output`），经 `make_qwen_thinking()` 在子线程同步调用（100s 超时）；thinking 模式已随 [ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) 全局关闭。

## 后续迁移澄清（历史，Dify 等价性）

- **数据源**：走后端 HTTP `GET /admin-api/integration/securities-instrument/select`（[ADR 0012](./0012-restore-backend-http-for-securities-instrument.md)），已落地于 `TickerClientHttpx`。
- **动态 prompt 片段**：`instrument-inference-prompt` 拉取 + 拼接（[ADR 0013](./0013-load-dynamic-inference-prompt-fragment.md)），已落地（5 分钟缓存 + 净化 + 降级）。
- "收敛 Dify 31 节点"在结构层面有效，收敛载体是共享 ticker 模块（resolver），非 ReAct Agent。

## 后果（历史落地口径）

- ticker 模块跨子图共享（swap.place_order + option.extract_inquiry），任何改动同时影响两条业务线，golden 须覆盖两方的标的识别 case。
- 高频俗称的本地字典缓存仍未建（依赖 `infer_code.md` 内置词典 + LLM 通用知识推断；注意 CLAUDE.md "禁止硬编码业务数据字典"红线——缓存只能做运行时 LRU，不能做静态清单）。
