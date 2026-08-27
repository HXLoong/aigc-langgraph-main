# LangGraph 课程资源（otc-agent）

## Knowledge

### 官方一手资料（最高信任级）
- [LangGraph 官方文档 · Low-level Concepts](https://langchain-ai.github.io/langgraph/concepts/low_level/)
  State / Node / Edge / Reducer / Command 的权威定义。用于：核心概念课的原始出处与引用。
- [LangGraph 官方文档 · Persistence（Checkpointer）](https://langchain-ai.github.io/langgraph/concepts/persistence/)
  checkpoint / thread_id / 恢复语义。用于：多轮对话与 HITL 课。
- [LangGraph 官方文档 · Subgraphs](https://langchain-ai.github.io/langgraph/concepts/subgraphs/)
  子图共享/独立 schema 两种模式。用于：swap 子图模板课。
- [LangChain Academy · Introduction to LangGraph（免费课程）](https://academy.langchain.com/courses/intro-to-langgraph)
  官方出品的入门视频课。用于：想要视频形式补充的同学，作为课后延伸。

### 本仓库一手资料（比外部资料优先级更高——项目怎么写以这里为准）
- `docs/training/langgraph-handbook.md` — 4000+ 行参考书，分 12 章。用于：每课"深入阅读"跳转目标，不要从头读。
- `docs/training/intern-langgraph-primer.md` — 实习生零基础版。用于：无 Dify 背景的新人第一天。
- `CLAUDE.md`（仓库根） — 项目宪法：8 条核心原则 + P0 红线。用于：铁律课与 review 检查。
- `.claude/rules/langgraph-patterns.md` — State/节点/路由/子图/checkpointer 项目模式。用于：所有代码课的规范出处。
- `.claude/rules/testing.md` + `tests/CLAUDE.md` — 测试金字塔 + mock "patch where it's looked up" 陷阱。用于：TDD 课。
- `docs/adr/`（ADR 0000-0020 共 21 篇） — 每个设计"为什么"。用于：学员问"为什么这样设计"时的标准答案来源。
- `app/graph/state.py` / `app/graph/safe_node.py` / `app/graphs/main_graph.py` / `app/subgraphs/swap/` — 活教材代码。

## Wisdom (Communities)
- [LangChain Forum](https://forum.langchain.com/)
  官方论坛，LangGraph 维护者出没。用于：项目外的通用 LangGraph 疑难。
- [langgraph GitHub Issues/Discussions](https://github.com/langchain-ai/langgraph)
  一手 bug/行为确认。用于：怀疑是框架行为而非我们代码时先搜这里。
- 内部：团队每日 15 分钟 standup + PR pair review（见 docs/training/README.md "Tech Lead 对接要点"）
  用于：真实 PR 的实战反馈，这是本课程最主要的"智慧"来源。

## Gaps
- 缺一份"Dify 老成员常见心智误区"的实测清单（如全局变量思维、if-else 声明式思维）——随学习记录积累后补入课程。
