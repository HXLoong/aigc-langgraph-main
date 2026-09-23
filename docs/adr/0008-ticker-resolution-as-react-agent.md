# ADR 0008 · 标的识别采用 ReAct Agent 而非固定链式流程

- 状态：**已被替代**（2026-09-20 标的识别委托 Java；此前 #154 裁决与实现沿革保留供追溯）
- 日期：2026-05-10
- 修订：2026-09-22 按取代关系改写为存根；此前：2026-08-28 P1 ticker 域迁移落地（Dify DSL v2 → LangGraph）；2026-08-27 深度改写为现状口径（对照代码核查）
- 作者：图灵科技 + Tony

## 当前职责（2026-09-20 起，2026-09-22 核对）

现役主链只提取证券原文、校验引用选择并调用 Java 业务接口；识别、排序、多候选与权威
校验由 Java 负责，见[标的识别边界](../backend-instrument-boundary.md)。本地 ticker 子图、
提示词及测试均已退役，原文和引用候选不标记为 `from_goats=True`。

以下章节记录迁移前的方案、约束和待办，不再作为当前实现要求。

## 历史迁移落地（2026-08-28）

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

场外衍生品场景大量涉及境外标的：境外期货 / 商品的行业俗称（"伦铜" = LME 铜期货）与跨市场中文简称（"腾讯" = `00700.HK`）都需要"简称 → 代码"映射与上下文消歧。原决策判断"识别步骤序列事先不确定"，选 **ReAct Agent + 工具循环**（tokenize / completeness / rank / infer_code 四个 `@tool`），否决固定链式流程；并附三条运行时约束：hard cap 8 步、GOATS 0 命中直接 fallback、多命中分差 ≥ 10 自动选否则 HITL。核心硬约束：任何最终标的必须经 GOATS 回查确认（`from_goats=True`）。

## 实际演进（历史）

1. **ReAct 从未接线**（2026-08-27 核查）：`react_agent.py` / `graph.py` 只在测试里编译冒烟；生产走确定性 resolver（tokenize → GOATS → 规则选优 → `infer_code` LLM 兜底 + GOATS 二次校验），与原决策相反但约束更强。三条运行时约束均为死逻辑。
2. **2026-08-27 裁决选项 (b)**：收窄为"确定性编排 + LLM 定点兜底（LLM 输出必须过 GOATS 校验）"，ReAct 死代码删除。
3. **DSL v2 迁移落地**（2026-08-28）：resolver 重写为对齐 Dify「标的智能化推断和分词工具」的 12 步管线（tokenize → 3 路批量 LLM → merge_and_validate → 逐 orgStr GOATS 查询 + LLM 排序），`completeness` 工具与三套私有选优逻辑删除。
4. **真子图化**（2026-09-17，ADR 0024 D3 重构 2）：私有 `TickerState`，`Send` 按 orgStr fan-out，`compile(checkpointer=False)`。
5. **整体移交 Java**（2026-09-20，commit `2f9ce65`）：上述全部本地实现删除；LangGraph 只提取原文候选与引用选择，标的工具由 Java 调用。

## 为何被取代

- 本地识别链路必然把业务清单（名称 → windCode、分词规则）写进提示词与代码，触碰 CLAUDE.md P0 红线。
- 本地实现与 Java 标的工具是同一职责的两份实现，ADR 0012 已证明会漂移。
- 每请求 3 路 LLM 调用与幻觉面在"后端才是权威"的前提下没有净收益。
- 用户 2026-09-20 指定的主工作流职责边界把标的工具放在 Java 侧。

原决策的两个动机（俗称、跨市场简称）仍然成立，只是解决位置从 LangGraph 移到后端标的工具。

## 仍有效的历史事实

- 调用方曾是 2 个节点（`swap/place_order` 与 `option/extract_inquiry`），close 基于订单号平仓从不依赖标的识别——ADR 0025 D2 的数据流沿用这一边界。
- `TickerCandidate.from_goats` 字段仍在 `app/graph/state.py` 作旧 checkpoint / HTTP 兼容，**原文候选不得标记 `from_goats=True`**（ADR 0025 D1）。
- HITL 消歧卡片、零命中回复等本地生成的标的类回复已全部退役（ADR 0021 与 ADR 0025 D3）。

## 关联

- [ADR 0025](./0025-instrument-resolution-delegated-to-backend.md) · 取代本 ADR
- [ADR 0012](./0012-restore-backend-http-for-securities-instrument.md) · 后端为标的真源的最初论证
- [ADR 0013](./0013-load-dynamic-inference-prompt-fragment.md) · 动态推断片段（已撤销）
- [ADR 0024](./0024-langgraph-native-rearchitecture.md) D3 · 曾经的 ticker 真子图
