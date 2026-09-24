# 课程大纲 · LangGraph 团队实战课

> 编写者：图灵科技
> 单课 ≤ 30 分钟，HTML 课件在 `lessons/`，速查表在 `reference/`。
> 8 课已全部生成；每课末尾小测全对再进下一课。学习中的卡点反馈给助教，课件会随之修订。

| # | 课名 | 一句话目标 | 课件 |
|---|---|---|---|
| 01 | 把第一张图跑起来：State / Node / Edge | 30 行代码跑通闭环，理解 reducer 覆盖 vs 累加 | `lessons/0001-state-node-edge.html` |
| 02 | 条件路由与 cascade 防御 | 写出 `_route_after_intent` 级别的路由，理解 error 检查为什么必须在第一行 | `lessons/0002-conditional-routing-cascade.html` |
| 03 | `@safe_node`：错误不崩图 | 读懂 91 行装饰器，能解释 fallback 链路全过程 | `lessons/0003-safe-node.html` |
| 04 | LLM 三件套：load_prompt + with_structured_output + Pydantic | 独立写一个 LLM 节点（以 swap.intent 为模板） | `lessons/0004-llm-three-pieces.html` |
| 05 | Checkpointer 与多轮对话 | 理解 thread_id = conversation_id 约定与状态恢复语义 | `lessons/0005-checkpointer-multiturn.html` |
| 06 | 子图模板：以 swap 为例 | 五步搭出一个业务子图并嵌入主图 | `lessons/0006-subgraph-swap-template.html` |
| 07 | Protocol Client 与 TDD | FakeClient mock 后端 + "patch 使用点"陷阱 + RED→GREEN | `lessons/0007-protocol-client-tdd.html` |
| 08 | harness 与 golden case：你的第一个 PR | 跑评估、读 trace 定位失败节点、按节点级 PR 交付（毕业课） | `lessons/0008-harness-golden-pr.html` |

## 学习节奏建议

- 先读 `docs/training/intern-langgraph-primer.md`，再从第 01 课开始，每天 1-2 课，一周完成。
- 每课末尾有小测（即时反馈），全对再进下一课。
- 学完 04 课后即可在导师确认范围后领小任务练手。
