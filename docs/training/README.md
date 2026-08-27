# LangGraph 培训资料 · 入口

> 你正要接手 otc-agent 项目（从 Dify 迁到 LangGraph 的场外衍生品 AI 助手）。
> 本目录是为你准备的**全部培训资料**，本文件是**唯一入口**——按下面的路径走就行。

---

## 目录里有什么

| 文件 | 用途 | 何时看 |
|---|---|---|
| **README.md**（本文件） | 学习路径 + 第 1 周日程 | **第 1 步：现在** |
| `intern-langgraph-primer.md` | **实习生/零基础版**：不假设 Dify 背景，从零讲 LangGraph + 第一周路径 | 新实习生从这里开始 |
| `langgraph-handbook.md`（4000+ 行） | 完整培训手册，分 12 章 + 3 附录 | 按需查阅，不要从头读 |

> **你是新来的实习生（没用过 Dify）**：直接读 `intern-langgraph-primer.md`，本文件的路径 A/B/C 以 Dify 对照为主线，更适合老团队成员。

> 别被 4000 行吓到——它是**参考书**，不是必读。下面会告诉你每一步看哪几节。

---

## 你的 3 条路径（按时间预算选）

### 路径 A · 90 分钟速通（先建立全貌）

**目标**：理解项目在做什么、LangGraph 是什么、回头能看懂 main 分支代码。

| 顺序 | 阅读 | 时长 |
|---|---|---|
| 1 | `langgraph-handbook.md` 第 0 章（写在前面） | 5 分钟 |
| 2 | 第 1.1 节（为什么从 Dify 迁出） | 5 分钟 |
| 3 | 第 2 章（LangGraph 5 个核心概念 + Hello World） | 30 分钟 |
| 4 | 第 3 章（Dify ↔ LangGraph 概念对照表） | 15 分钟 |
| 5 | 第 6.1 节（主图全貌 + Mermaid 流程图） | 10 分钟 |
| 6 | 第 5.1-5.5 节（swap 子图模板，看 5 步建图） | 25 分钟 |

**完成后能干什么**：
- 看懂 `app/graph/main.py` 在做什么
- 看懂任意一个节点函数（如 `app/subgraphs/swap/intent.py`）
- 知道 Dify 里你熟悉的"LLM 节点 / if-else / 代码节点"在 LangGraph 里对应到什么

### 路径 B · 第 1 天（动手跑起来 + 看完关键章节）

**目标**：跑通本地环境、跑一次 harness、看完上手必读章节。

```bash
# 上午 · 把环境跑起来
git clone git@github.com:GZTL-AI/aigc-langgraph.git
cd aigc-langgraph
pip install -e ".[dev]"
cp .env.example .env                          # 找团队拿 QWEN_API_KEY
docker compose up -d mysql
pytest tests/test_smoke.py -v                 # 应全绿

# 下午 · 跑一次主图 + 看 trace
uvicorn app.main:app --reload                 # 启动服务
# 另起终端
curl -X POST http://localhost:8000/v1/workflows/run \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {"rawContent": "下单 600519 1000 股", "conversationId": "test-1"},
    "response_mode": "blocking",
    "user": "test-1"
  }'

# 跑一次 harness
python -m harness run --case g001
```

**同步阅读**：

| 时段 | 阅读章节 |
|---|---|
| 上午 | 路径 A 的全部内容（90 分钟） |
| 下午 | 第 4 章（项目代码结构对比，逐节点类型对照） |
| 晚上 | 第 8 章（提示词与 LLM 调用） + 第 9 章（测试与 harness） |

### 路径 C · 第 1 周（完整掌握 + 提交首个 PR）

| Day | 任务 | 阅读 |
|---|---|---|
| **Day 1** | 跑通环境 + 路径 A 速通 + 第 4 章 | 第 0-4 章 + 第 6.1 节 |
| **Day 2** | 走读 swap 子图全部代码（intent/place_order/cancel/confirm/query_order/graph） | 第 5 章（重点） |
| **Day 3** | 走读主图 + 一级路由 + ticker ReAct 子图 | 第 6 章 + 第 7 章 |
| **Day 4** | 看 harness 输出 + 用 LangFuse UI 看一次 trace | 第 8-9 章 |
| **Day 5** | 找 Tech Lead 领一个 P2 issue，按手册第 11 章模板写 | 第 11 章 + 附录 A（陷阱） |
| **Day 6-7** | 单测 + golden case + 跑 harness + 开 PR + 改 review 意见 | 第 10 章（PR 规约） |

**Day 5-7 的 issue 推荐**（任选一个 P2 节点起步）：
- `swap.image_recognize`（图片识别工具节点）
- `swap.hand_to_share`（互换分享节点）
- `close.query_status`（平仓查询状态）

> 这 3 个节点都没有复杂业务逻辑，是练手的好选择。让 Tech Lead 帮你确认范围。

---

## 必读 · 这 5 件事不知道一定会踩坑

### 1. 节点函数 4 铁律（手册第 2.2 节）

```python
# ❌ 不要 mutate state           # ✅ return partial dict
# ❌ 不要 return 完整 state       # ✅ 只返回要改的字段
# ❌ 路由函数不能 async / IO      # ✅ 路由函数是同步纯函数
# ❌ 不要裸 try/except            # ✅ 用 @safe_node 装饰器
```

### 2. Mock 必须 patch 使用点（手册第 9.2 节）

```python
# ❌ patch 原模块（不生效）
monkeypatch.setattr("app.llm.clients.get_qwen_structured", fake)

# ✅ patch 节点模块的 import 名
monkeypatch.setattr("app.subgraphs.swap.intent.get_qwen_structured", fake)
```

### 3. State 字段必须先在 `app/graph/state.py` 声明再用

不在 `AgentState` 里声明就用 → mypy 报错 → 不能合 PR。

### 4. 提示词从 .md 加载，不在 Python 里写

```python
# ❌ system_prompt = "你是一个意图识别器..."  # 硬编码
# ✅ prompt = load_prompt("swap", "intent")
```

### 5. 一节点一 PR + 5 条 golden 全 PASS（手册第 10.1 节）

> 节点 PR 的"绿"标准 = 该节点至少 5 条 golden 全 PASS（PASS 率，不是行覆盖率）。
> 禁止"先合代码、稍后补 case"。

---

## 卡住了怎么办

| 卡点 | 该看什么 |
|---|---|
| "环境跑不起来" | 项目根目录 `HOW_TO_RUN.md` + `docs/TROUBLESHOOTING.md` |
| "不懂 LangGraph 某个 API" | LangGraph 官方文档 <https://langchain-ai.github.io/langgraph/> |
| "项目里某段代码看不懂" | 手册第 4-7 章 + 对应节点的 docstring |
| "mypy / ruff 报错" | 手册附录 A（12 个常见陷阱） |
| "测试 mock 不生效" | 手册第 9.2 节 + 附录 A.3 |
| "Dify 里这个节点对应代码哪里" | 手册第 4.3 节（节点类型逐一对照） |
| "改了提示词没效果" | 手册附录 A.10（lru_cache 缓存） |
| "PR review 不知道怎么改" | 手册第 10.6 节（reviewer 检查清单） |
| "想了解某个设计为什么这样" | `docs/adr/`（ADR 0000-0020 共 21 篇）+ `CLAUDE.md` |

---

## 项目相关的 5 份必读文档（在主仓库）

| 文档 | 作用 |
|---|---|
| `CLAUDE.md` | **项目宪法**——所有约定的总入口，与本手册冲突时以它为准 |
| `CONTEXT.md` | 业务术语 + 领域语言（雪球、互换、期权平仓的中文术语） |
| `docs/api-contracts/java-backend.md` | Java 后端契约——写 Pydantic Output 必看 |
| `docs/adr/0001-rewrite-app-with-harness-first.md` | 含 D1-D9 子决策（节点拆分/合并、API 兼容、State 设计） |
| `.claude/rules/langgraph-patterns.md` | LangGraph 项目模式（State / 节点 / 路由 / 子图 / checkpointer） |

---

## Tech Lead 的对接要点

如果你是 Tech Lead 在带新人：

1. **第 1 天**：和新人一起跑通环境，确保 `pytest tests/test_smoke.py` 全绿
2. **第 2-3 天**：让新人结对跟你 walk through 一个真实业务 case（从客户原话 → 主图 → 子图 → 调后端 → 回复）
3. **第 4 天**：选一个 P2 issue 给新人，明确范围 + 验收标准
4. **第 5-7 天**：每天 15 分钟 standup，PR 草稿出来后 pair review 一次

**新人 Day 7 的产出预期**：
- 1 个节点的完整 PR（代码 + 单测 + 5 条 golden + ADR 引用）
- harness PASS 率不降
- 对手册第 1-7 章 + 第 11 章能用自己的话复述

---

## 本目录维护说明

- 这份 README 是给"接手开发的人"看的，不要扩成完整教程
- 完整内容在 `langgraph-handbook.md`，4000+ 行不要再加
- 有新的高频踩坑点 → 在手册附录 A 加，不要在这里加
- 有新的 ADR / 规则 → 在主仓库 `docs/adr/` 或 `.claude/rules/` 加
