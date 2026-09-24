# 培训资料 · 入口

新成员接手 otc-agent（场外衍生品 AI 指令助手，原生 LangGraph 实现）时从这里开始。

## 目录里有什么

| 文件 | 用途 | 何时看 |
|---|---|---|
| `intern-langgraph-primer.md` | 零基础入门：LangGraph 核心概念 + 第一周路径 | 新成员第一天 |
| `course/` | 8 节交互式小课（State / 路由 / `@safe_node` / LLM 调用 / checkpointer / 子图 / Protocol 客户端 / harness） | 第一周逐课学习 |
| `skills-guide.md` | Claude Code 与 Codex 的项目 Skills 怎么调、怎么加 | 第一次用 `/xxx` 或 `$xxx` 之前 |
| `customer-onboarding.md` | 业务方使用培训（企微机器人怎么用） | 给客户业务方做培训时 |

## 第一周路径

| Day | 任务 |
|---|---|
| 1 | 读 `intern-langgraph-primer.md`；按 `docs/DEVELOPMENT.md` 跑通本地环境，`pytest tests/test_smoke.py` 全绿 |
| 2-3 | 学完 `course/` 第 1-4 课；走读 `app/graph/main.py` 与 `app/subgraphs/swap/` |
| 4 | 学完第 5-8 课；用 `python -m harness run` 跑一次回归，在 LangFuse 中看一次 trace |
| 5-7 | 领一个小任务，按 TDD 写测试与实现，补数据集用例，开 PR |

## 必读 · 这 5 件事不知道一定会踩坑

1. **节点函数返回部分更新**：不修改输入 state，只返回要改的字段；路由函数是同步纯函数；节点用 `@safe_node` / `@io_node` 包住异常。
2. **Mock 要 patch 使用点**：patch 节点模块里 import 进来的名字，不 patch 原定义处（见 `tests/CLAUDE.md`）。
3. **State 字段先声明再用**：新字段必须先在 `app/graph/state.py` 声明。
4. **提示词不写在 Python 里**：LLM 节点声明 `PromptSpec`，提示词放 `app/prompts/**/*.md`（ADR 0023）。
5. **改动必过评测门**：TDD → pytest → 一致性 lint → 数据集 PASS 率不降（ADR 0030 D3）。

## 卡住了怎么办

| 卡点 | 该看什么 |
|---|---|
| 环境跑不起来 | `docs/DEVELOPMENT.md` + `docs/TROUBLESHOOTING.md` |
| 不懂 LangGraph 某个 API | LangGraph 官方文档 <https://langchain-ai.github.io/langgraph/> |
| 想知道某个设计为什么这样 | `docs/adr/README.md` + `CLAUDE.md` |
| 业务术语看不懂 | `CONTEXT.md` |
| 写 Pydantic 模型对接后端 | `docs/api-contracts/java-backend.md` |

项目约定以根目录 `CLAUDE.md` 为准，与本目录内容冲突时以它为准。
