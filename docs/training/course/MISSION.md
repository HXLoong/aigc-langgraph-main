# Mission: LangGraph 团队实战课（otc-agent）

## Why
团队要把基于 Dify 的场外衍生品助手全部用 LangGraph 重构并推进到 M3.3/M4 上线。
成员（Dify 背景的工程/算法同事 + 新实习生）必须尽快具备独立开发 LangGraph 节点/子图的能力，
否则重构收尾、错例修复和上线值守都会压在少数人身上。

## Success looks like
- 每位成员能独立认领一个节点级 issue，按项目规范（`@safe_node` + `with_structured_output` + `load_prompt` + golden case）提交 PR 并通过 review
- 能不看文档画出主图 + 任一子图的节点流转，并解释 State/reducer/cascade 防御
- 能用 harness / langfuse_eval 定位一条失败 case 到具体节点，并按 TDD 流程修复
- 新人第一周内完成第一个 PR（对齐 docs/training/README.md 的路径 C）

## Constraints
- 全中文授课；单课 ≤ 30 分钟，适合碎片时间
- 教材必须以本仓库真实代码为准（不教"通用 LangGraph"，教 otc-agent 现在长什么样）
- 已有 `docs/training/langgraph-handbook.md`（4000+ 行参考书）——课程**引用**它，不复制它
- 编写者署名：图灵科技

## Out of scope
- LangChain legacy（Chain / LLMChain / AgentExecutor）
- LangGraph Pregel runtime 内部实现
- 通用提示词工程（只教本项目的提示词加载/版本化工程模式）
