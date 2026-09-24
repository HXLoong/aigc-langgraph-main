# LangGraph 实习生培训说明 · 从零上手 otc-agent

> **编写者**：图灵科技
> **目标读者**：新来的实习生——不要求有 Dify 背景，不要求用过 LangGraph，只要求会 Python + async 基础
> **预期用时**：第 1 天建立全貌，第 1 周能独立改一个节点并提 PR
> **配套资料**：本目录 `course/` 交互式小课

---

## 0. 这份文档怎么用

- 你是**实习生、第一次接触 LangGraph** → 从头往下读，跟着代码走，大约 2 小时读完
- 你是**从 Dify 团队转过来的老同事** → 直接看 [README.md](./README.md) 的路径 A/B/C，那边以 Dify 对照为主线
- 读到任何一节觉得"想再深入" → 对应的 `course/` 小课与 LangGraph 官方文档

**一句话版本**：本项目用 LangGraph 把"客户在企微群里说一句话 → 机器人理解意图 → 调后端下单/查单 → 回复客户"这条链路建模为一张**有状态的有向图**。你要学的就是：图怎么定义、状态怎么流动、节点怎么写、错误怎么兜底、测试怎么跑。

---

## 1. 项目 5 分钟背景

**otc-agent** 是场外衍生品 AI 指令助手：

```
企微群客户消息 ──→ FastAPI (POST /v1/workflows/run)
                      │
                      ▼
              LangGraph 主图
      ingest → intent_route ──┬→ swap 子图（互换：下单/撤单/确认/查单）
                              ├→ option 子图（期权：询价/下单/撤单/确认/查询）
                              ├→ close 子图（期权平仓）
                              └→ fallback（听不懂时的友好降级）
                      │
                      ▼
        render 节点生成回复 ──→ 返回企微
```

- 业务后端是 Java（下单、查单等真实交易接口），我们通过 HTTP 客户端调它
- LLM 全环境统一 DeepSeek-V4-pro（`app/llm/clients.py` 统一工厂，ADR 0020）
- 多轮对话状态存 MySQL（LangGraph checkpointer）
- 可观测用 LangFuse（每个节点的输入输出、耗时都能在 UI 里看到）

项目从 Dify（低代码工作流平台）迁移而来，原始提示词资产保留在 `app/prompts/**/*.md`。你不需要懂 Dify，只需要知道：**提示词是历史资产，改动有纪律约束**（见第 6 节铁律）。

---

## 2. LangGraph 核心心智模型（30 分钟）

LangGraph 只有 5 个必须掌握的概念：**State / Node / Edge / Graph / Checkpointer**。其余都是这 5 个的组合。

### 2.1 一个能跑的最小例子

先看 30 行完整代码，5 个概念全在里面：

```python
import asyncio
from operator import add
from typing import Annotated, TypedDict
from langgraph.graph import END, START, StateGraph

# ① State：一个类型化 dict，节点间传递数据的唯一载体
class State(TypedDict, total=False):
    counter: int                       # 普通字段：后写的覆盖先写的
    log: Annotated[list[str], add]     # reducer 字段：用 + 合并（list 追加）

# ② Node：一个 async 函数，读 state，返回"要更新的字段"（partial dict）
async def increment(state: State) -> dict:
    n = state.get("counter", 0) + 1
    return {"counter": n, "log": [f"now {n}"]}

# ③ 条件路由函数：同步纯函数，返回下一站的名字
def is_done(state: State) -> str:
    return "done" if state.get("counter", 0) >= 3 else "again"

# ④ Graph：组装节点和边，然后编译
g = StateGraph(State)
g.add_node("inc", increment)
g.add_edge(START, "inc")                                     # 普通边
g.add_conditional_edges("inc", is_done, {"again": "inc", "done": END})  # 条件边
graph = g.compile()

# ⑤ 执行
result = asyncio.run(graph.ainvoke({"counter": 0}))
print(result)   # {'counter': 3, 'log': ['now 1', 'now 2', 'now 3']}
```

把这段代码存成文件跑一遍（本仓库环境即可），确认你理解每一行再往下读。

### 2.2 State：数据的唯一载体

- State 是一个 `TypedDict`，**所有字段先声明后使用**
- `total=False` 表示所有字段可选——节点只关心自己用到的字段
- 节点**永远不要修改传入的 state**（`state["x"] = ...` 禁止），只返回 partial dict，框架负责合并
- **reducer**：`Annotated[list, add]` 的字段合并时做 `旧值 + 新值`（追加）而不是覆盖。没有 reducer 的字段直接覆盖

为什么 trace / history_messages 必须用 reducer？因为每个节点都要追加自己的记录，覆盖型字段会把前面节点写的内容冲掉。

本项目的 State 是 `app/graph/state.py` 里的 `AgentState`，字段按**业务对象**聚合（`place_params` / `cancel_params` / `tickers`……），不按节点铺开——这是 ADR 0001 D6 的决策，好处是多个节点共享同一业务字段、render 节点不用关心数据来自哪个节点。

### 2.3 Node：纯函数节点

节点签名固定：`async def node(state: AgentState) -> dict`。四条铁律：

| 铁律 | 反例 | 正例 |
|---|---|---|
| 不 mutate 入参 | `state["counter"] += 1` | `return {"counter": state["counter"] + 1}` |
| 返回 partial 不返回完整 state | `return state` | `return {"intent": "..."}` |
| 路由函数不做 IO / LLM | 路由里 `await llm.ainvoke(...)` | 路由是同步纯函数，只读 state |
| 不裸 try/except | 节点里 `except: pass` | 用 `@safe_node` 统一兜底 |

### 2.4 Edge：普通边和条件边

```python
g.add_edge("ingest", "intent_route")            # 无条件流转

g.add_conditional_edges(                         # 由路由函数决定下一站
    "intent_route",
    _route_after_intent,                         # 返回字符串
    {"swap": "swap", "option": "option", "fallback": "fallback"},
)
```

路由函数返回的字符串必须是映射表的 key，否则运行时报错。

### 2.5 Checkpointer：多轮对话的记忆

每次图跑完，state 快照写进存储；同一个 `thread_id` 下次再来，自动从上次的 state 继续——这就是多轮对话的实现方式。

```python
# 测试用内存版
from langgraph.checkpoint.memory import InMemorySaver
graph = g.compile(checkpointer=InMemorySaver())

# 生产用 MySQL 版（app/checkpointer/factory.py）
config = {"configurable": {"thread_id": conversation_id}}
result = await graph.ainvoke(state, config=config)
```

**项目约定：thread_id 固定 = conversation_id（企微会话 ID）**。同群同客户共享历史，换群即隔离。

### 2.6 Subgraph：子图就是一个节点

```python
from app.subgraphs.swap import build_swap_graph
g.add_node("swap", build_swap_graph())   # 整个 swap 子图作为主图的一个节点
```

本项目所有业务子图与主图**共享 AgentState**，子图内部改的字段会回传主图。

> 深入：`course/` 第 01-02 课。
> 官方文档：<https://langchain-ai.github.io/langgraph/>

---

## 3. 本项目怎么用 LangGraph（1 小时，对照真实代码读)

学完通用概念，现在看本项目的 4 个工程模式。**每一小节都请打开对应文件对照读**。

### 3.1 `@safe_node`：所有节点的统一外衣

打开 `app/graph/safe_node.py`（91 行，全读）。它做三件事：

1. 节点抛异常 → 捕获后写入 `state["error"]`（ErrorInfo：node / type / message / traceback），**图不崩**
2. 自动往 `state["trace"]` 追加 TraceEntry（节点名 + 耗时 ms）
3. 自动上报监控埋点（`emit_node_completed`）

所以业务节点长这样，干净得只剩业务：

```python
from app.graph.safe_node import safe_node
from app.graph.state import AgentState

@safe_node
async def swap_intent(state: AgentState) -> dict:
    ...                                  # 这里抛任何异常都会被兜住
    return {"intent": result.type}
```

### 3.2 cascade 防御：错误不扩散

上游节点 fail 后 `state["error"]` 非空，**所有下游条件路由第一件事就是检查它**：

```python
# app/graph/main.py 的真实路由
def _route_after_intent(state: AgentState) -> str:
    if state.get("error") is not None:      # ← cascade 防御，永远第一行
        return "fallback"
    pt = state.get("product_type", "unknown")
    return "fallback" if pt == "unknown" else pt
```

`fallback` 节点输出友好回复（"我没完全理解你的意思，能换种说法重新告诉我吗"），trace 里记录是哪个节点触发的。`app/graph/cascade.py` 提供了 `has_error()` / `with_cascade_guard()` 两个工具。

**这是 CLAUDE.md 核心原则第 8 条，review 必查。**

### 3.3 LLM 调用三件套：load_prompt + with_structured_output + Pydantic

本项目每个 LLM 节点都是同一个模板（打开 `app/subgraphs/swap/intent.py` 对照）：

```python
from app.prompts import load_prompt
from app.llm.clients import get_qwen_structured
from app.subgraphs.swap.models import SwapIntentOutput   # Pydantic 输出模型

@safe_node
async def swap_intent(state: AgentState) -> dict:
    prompt = load_prompt("swap", "intent")               # ① 提示词从 .md 加载，绝不硬编码
    llm = get_qwen_structured().with_structured_output(SwapIntentOutput)  # ② 强类型输出
    result = await llm.ainvoke([
        ("system", prompt.system),
        ("user", user_message),
    ])                                                    # ③ result 直接是 Pydantic 实例
    return {"intent": result.type, "trace": [...]}
```

三条对应的铁律：

- **提示词不进 Python 源码**——`app/prompts/<category>/<name>.md` + `load_prompt()`
- **LLM 输出不手工 `json.loads`**——`with_structured_output(PydanticModel)`，解析失败自带 1 次重试，最终由 `@safe_node` 兜底
- **输出模型对齐 Java DTO**——字段名与后端契约 1:1（`docs/api-contracts/java-backend.md`）

### 3.4 后端调用走 Protocol，不直接 httpx

```python
# ❌ 禁止：节点里直接 httpx.AsyncClient(...)
# ✅ 必须：走三个 Protocol 之一
from app.tools.swap_client import SwapClient      # POST /swap-order/operate
from app.tools.option_client import OptionClient  # POST /financial-orders/operate
from app.tools.message_client import MessageClient  # POST /set-intent（会话意图写回）
```

Protocol（接口）+ Httpx 实现分离 = 单测时塞一个 FakeClient 就能 mock 整个后端。

### 3.5 串起来看一遍完整链路

按这个顺序走读代码（半天，建议边读边在纸上画图）：

1. `app/api/routes.py` —— 请求入口，构造初始 state，`graph.ainvoke(state, config)`
2. `app/graph/main.py` —— 主图组装：ingest → intent_route → 条件路由 → 子图 → render
3. `app/nodes/intent_route.py` —— 一级路由三层策略：正则 → 关键词 → LLM 兜底
4. `app/subgraphs/swap/graph.py` —— 子图模板：intent 节点 → 按意图分发到 5 个真节点 + 1 个 unknown 兜底
5. `app/subgraphs/swap/place_order.py` —— 最复杂的业务节点：LLM 提取参数原文与证据，标的原文交后端识别
6. `app/nodes/render.py` —— 把业务结果渲染成企微回复文本

> 深入：`course/` 第 06 课（子图模板）+ `docs/architecture/README.md`。

---

## 4. 第一周学习路径

### Day 1 · 环境跑通 + 全貌

```bash
git clone https://github.com/GZTL-AI/aigc-langgraph.git    # 用 HTTPS
cd aigc-langgraph
pip install -e ".[dev]"
cp .env.example .env                  # 找导师拿 QWEN_API_KEY 与 MYSQL_URI
USE_MYSQL_CHECKPOINTER=false REQUEST_IDEMPOTENCY=false ENABLE_LANGFUSE=false \
    python -m pytest tests/test_smoke.py -q   # 应全绿；跑不通先解决环境再往下

# 启动服务，发一条真实请求
uvicorn app.main:app --reload
curl -X POST http://localhost:8000/v1/workflows/run \
  -H "Content-Type: application/json" \
  -d '{"inputs": {"rawContent": "下单 600519 1000 股", "conversationId": "test-1"},
       "response_mode": "blocking", "user": "test-1"}'
```

阅读：本文档第 1-2 节 + 自己跑通 2.1 的 Hello World。

### Day 2 · 走读 swap 子图

阅读本文档第 3 节 + 把 3.5 的 6 个文件全部走读一遍。目标：能用自己的话说出"一条'帮我下单'的消息经过了哪些节点、state 里各字段是谁写的"。

### Day 3 · 测试与评估

- 读 `tests/CLAUDE.md`（mock 陷阱页）+ `.claude/rules/testing.md`
- 跑一次 harness：`python -m harness run`，看 JSON/markdown 报告长什么样
- 挑一个失败或跳过的 case，顺着 trace 找到对应节点

### Day 4 · 动手练习（不提交，本地玩）

三个递进练习：

1. **改 Hello World**：给 2.1 的例子加一个 `double` 节点（counter 翻倍），用条件边控制"到 10 就结束"
2. **加 trace**：在本地给 `swap_query_order` 节点的 trace 里多记一个字段，跑 `pytest tests/ -k swap` 确认没破坏任何测试
3. **写一个 FakeClient 单测**：模仿 `tests/` 里现有写法，给任一子图节点写一个新的单测（mock LLM + FakeClient），跑到 GREEN

### Day 5 · 领第一个真实任务

找导师领一个 P2 小 issue（历史推荐：`swap.hand_to_share` / `close.query_status` 这类无复杂业务逻辑的节点）。按第 6 节的铁律 + TDD 流程走完：写失败测试 → 修 → 全量回归 → feature 分支提 PR（PR 标题和描述用中文）。

**第一周结束的验收标准**：

- [ ] `pytest tests/` 本地全绿跑过至少一次
- [ ] 能画出主图 + swap 子图的节点流转图（不看代码）
- [ ] 能解释：reducer 是什么、`@safe_node` 做了什么、cascade 防御为什么必须
- [ ] 提交了第一个 PR（哪怕很小）

---

## 5. 常用命令速查

```bash
# 测试
python -m pytest tests/ -q             # 全套
pytest -k "not e2e"                   # 跳过 e2e
pytest -v --lf                        # 只跑上次失败的
ruff check app/ tests/                # lint（行宽 100）
mypy app/                             # 类型检查

# 评估
python -m harness run --backend mock  # categories 业务集快速 smoke
python scripts/langfuse/langfuse_eval.py --local tests/fixtures/categories --ids case-025 --concurrency 1
                                      # 带 DeepSeek Judge 的正式评估

# 服务
uvicorn app.main:app --reload         # FastAPI
```

---

## 6. 项目铁律（背下来，review 必查）

1. **提示词不硬编码**——从 `app/prompts/**/*.md` 用 `load_prompt()` 加载
2. **LLM 输出必须 `with_structured_output(PydanticModel)`**——绝不手工解析 JSON
3. **每个节点 `@safe_node`**——异常降级到 `state["error"]`，图不崩
4. **State 字段先声明后使用**——新字段必须先进 `app/graph/state.py` 的 `AgentState`
5. **TDD 强制**——bug fix / 新功能必须先写失败测试（RED）再改代码（GREEN），禁止反过来
6. **cascade 防御**——任何条件路由第一行检查 `state.get("error")`
7. **标的原文交后端识别**——LangGraph 只提取客户原文，不补代码、不查证券池（ADR 0025）
8. **后端调用走 Protocol**——禁止节点里直接 `httpx.AsyncClient`
9. **不在 main 分支直接改业务子图**——feature 分支 + PR，PR 标题/描述用中文
10. **不掩盖后端真实响应**——严禁"后端返回 X 就本地改成 Y"的伪造逻辑（P0 红线）
11. **不硬编码业务数据字典**——"中文名 → 代码"这类映射靠 LLM 推断 + 后端校验，不进代码
12. **Mock 要 patch 使用点**——patch 节点模块里 import 后的名字，不是原定义处（`tests/CLAUDE.md`）

---

## 7. 深入阅读地图

| 想了解 | 去哪里 |
|---|---|
| 所有约定的总入口（项目宪法） | 根目录 `CLAUDE.md` |
| 业务术语（雪球/互换/平仓的行话） | `CONTEXT.md` |
| LangGraph 每个概念的展开讲解 | `docs/training/course/` + LangGraph 官方文档 |
| 手把手写一个新子图 | `course/` 第 06 课 + `.claude/agents/subgraph-builder.md` |
| 常见陷阱 | `tests/CLAUDE.md` + `docs/development/troubleshooting.md` |
| 为什么这样设计（架构决定） | `docs/adr/`（ADR 0000-0020） |
| Java 后端接口契约 | `docs/api-contracts/java-backend.md` |
| State/节点/路由/checkpointer 项目模式 | `.claude/rules/langgraph-patterns.md` |
| 测试规范与 mock 陷阱 | `.claude/rules/testing.md` + `tests/CLAUDE.md` |
| 提示词管理纪律 | `.claude/rules/prompt-management.md` |
| LangGraph 官方文档 | <https://langchain-ai.github.io/langgraph/> |

---

## 8. 卡住了怎么办

- 环境跑不起来 → `docs/development/troubleshooting.md`，还不行找导师
- 看不懂某段代码 → 先读该文件顶部 docstring 和所在目录的 CLAUDE.md，再查 `course/` 对应小课
- 测试 mock 不生效 → 九成是 patch 了定义处而不是使用点，看 `tests/CLAUDE.md`
- 改了提示词没效果 → `load_prompt` 有 lru_cache，测试里 `from app.prompts import clear_cache; clear_cache()`
- 不知道一个设计为什么这样 → `docs/adr/` 按编号找，找不到就问，**不要猜**

> 最后一条建议：**遇到问题先花 15 分钟自己查（本表 + course + 代码 docstring），15 分钟内没头绪就去问导师**。不问白白卡半天，是实习期最常见的浪费。
