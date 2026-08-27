# LangGraph 特定模式

## State 设计

- 在 `app/state.py` 统一管理 `AgentState`（TypedDict）
- 新增字段必须：
  1. 在 TypedDict 中声明类型
  2. 若需要并行合并（如 `trace`），加 `Annotated[list, add]`
  3. 在 `make_initial_state()` 中给默认值

```python
class AgentState(TypedDict, total=False):
    trace: Annotated[list[TraceEntry], add]  # 并行合并
    product_type: ProductType                 # 单值覆盖
    history_messages: Annotated[list, add]    # 累加
```

## 节点函数规范

```python
@safe_node
async def my_node(state: AgentState) -> dict[str, Any]:
    """做一件事的简洁文档。"""
    # 1. 从 state 读需要的字段
    wx = state["wechat_input"]

    # 2. 做业务逻辑（LLM / HTTP / 纯计算）
    result = await do_work(...)

    # 3. 返回 **部分** state 更新（不要返回整个 state）
    return {
        "intent": result.type,
        "trace": [{"node": "my_node", "decision": "..."}],
    }
```

**关键**：
- 节点只返回**需要更新的字段**，LangGraph 会自动 merge
- 不要修改传入的 state（immutable 对待）
- trace 用 list 形式（reducer 会累加）

## 条件路由

```python
# ✅ 正确：路由函数是纯函数
def route_by_intent(state: AgentState) -> str:
    return state.get("intent", "default")

g.add_conditional_edges(
    "classify",
    route_by_intent,
    {"place_order": "extract_place", "confirm": "extract_id"},
)

# ❌ 错误：路由函数里做 IO 或 LLM 调用
def route_by_intent(state):
    result = llm.invoke(...)   # 禁止
    return result.type
```

## 子图嵌入

```python
# 子图作为节点嵌入主图
from app.subgraphs.swap import build_swap_graph

g.add_node("swap", build_swap_graph().compile())
```

- 子图和主图**共享 State schema**（都是 AgentState）
- 子图内部有自己的 START/END
- 主图的 conditional_edges 选择哪个子图

## Checkpointer 使用

```python
# ✅ 生产：MySQL
from langgraph.checkpoint.mysql.aio import AIOMySQLSaver
async with AIOMySQLSaver.from_conn_string(uri) as cp:
    await cp.setup()
    graph = build_main_graph(cp)

# ✅ 测试：内存
from langgraph.checkpoint.memory import InMemorySaver
graph = build_main_graph(InMemorySaver())

# ❌ 错误：不传 checkpointer 就编译（多轮对话会失效）
graph = g.compile()  # 不行，需要 checkpointer
```

## thread_id 约定

- **thread_id 固定等于 conversation_id**（企微会话 ID）
- 同一客户在同一群的对话会共享 state 历史
- 换客户/换群 → thread_id 不同 → state 完全隔离

```python
config = {"configurable": {"thread_id": req.conversation_id}}
result = await graph.ainvoke(state, config=config)
```

## 历史消息加载

- FastAPI 路由层预加载：`load_history_from_checkpoint()` → 注入 state
- 节点内不应直接读 checkpoint，通过 state 获取

## Structured Output（必须）

```python
# ✅ 正确
from app.subgraphs.swap_models import SwapIntentOutput
llm = qwen.with_structured_output(SwapIntentOutput)
result: SwapIntentOutput = await llm.ainvoke([...])

# ❌ 错误：手工解析 JSON
response = await qwen.ainvoke(...)
data = json.loads(response.content)  # 容易失败，违反 Dify 迁移原则
```

## Human-in-the-Loop（interrupt）

```python
# 编译时指定在哪些节点前暂停
graph = g.compile(
    checkpointer=cp,
    interrupt_before=["swap_place_order"],  # 下单前人工确认（示例；生产当前未启用 interrupt，见 ADR 0006）
)

# API 层：暂停时返回确认卡片给企微
# 确认后：graph.ainvoke(None, config=config)  # None = 不新增输入，从 checkpoint 恢复
```

## 观测

- 生产：LangFuse（`ENABLE_LANGFUSE=true` + `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`，ADR 0014）
- 自建：OpenTelemetry（`app/observability/tracing.py`）
- 每个节点通过 `trace` 字段记录决策，写到 MySQL `node_trace` 表

## 常见陷阱

1. **节点返回值不要 `state.update(...)`**：返回 partial dict 即可
2. **Checkpointer 是应用级单例**：别在每个请求创建新的
3. **ReAct Agent 作为子图节点时自动处理 state**：不用手工做 invoke
4. **递归限制**：复杂子图设 `{"recursion_limit": 25}` 避免死循环
