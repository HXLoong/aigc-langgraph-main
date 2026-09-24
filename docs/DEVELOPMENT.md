# 开发指南

## 环境准备

### 系统要求
- Python 3.11+（严格）
- MySQL 8.0.19 ≤ version < 9.6.0
- Docker + Docker Compose（本地开发推荐）
- Node.js 18+（仅 Claude Code 需要）

### 初始化

```bash
git clone <repo>
cd otc-agent
cp .env.example .env        # 填入真实配置；MYSQL_URI 指向 Java 现有数据库
pip install -e ".[dev]"     # 含 pytest/ruff/mypy
# 在 Java 数据库执行一次初始化（LangGraph 不自带 MySQL 容器）
mysql -h <HOST> -P <PORT> -u <USER> -p --database=<JAVA_DATABASE> < sql/init.sql
USE_MYSQL_CHECKPOINTER=false REQUEST_IDEMPOTENCY=false ENABLE_LANGFUSE=false \
    python -m pytest tests/test_smoke.py -q
```

## 日常命令

```bash
# 启动服务
uvicorn app.main:app --reload --port 8000

# 跑测试
python -m pytest tests/ -q                          # 全部
python -m pytest tests/ -q -k "swap"               # 只跑互换
python -m pytest tests/integration/ tests/test_cascade_e2e.py -q   # 只跑集成 / E2E
python -m pytest --cov=app/                        # 覆盖率

# 代码质量
ruff check app/ tests/                 # lint
ruff format app/ tests/                # 格式化
mypy app/                              # 类型

# 评估
python scripts/langfuse/langfuse_eval.py --local tests/fixtures/intent --concurrency 3 --fail-under 0.95
python scripts/local_eval.py --base-url http://127.0.0.1:8201 --data tests/fixtures/categories --case case-025

# 一致性检查（提交前）
python scripts/check_fixture_consistency.py && python scripts/check_adr_refs.py
python scripts/check_alert_threshold_consistency.py && python scripts/sync_agents_md.py --check
```

## 添加新功能的标准流程

1. **feature branch**：`git checkout -b feature/adjust-hedge`
2. **跟 Claude Code 对话**：描述需求，让它规划步骤
3. **先写测试**：TDD，让 test-generator agent 帮忙
4. **小步提交**：每完成一层功能提交一次
5. **跑数据集**：确认 PASS 率不低于前值（ADR 0030 D3）
6. **提 PR**：模板见 `.claude/rules/git-workflow.md`

## 最佳实践

### 状态设计
- 新增 State 字段 → 先改 `app/graph/state.py`，再在节点里用；per-turn 字段记得在 `app/nodes/ingest.py` 重置
- 不要在节点里"偷偷"塞新字段（会破坏类型提示和测试）

### 节点函数
- 纯计算与写类节点用 `@safe_node`；只读 IO 节点用 `@io_node` + `add_io_node`（ADR 0024 D3）
- 返回 partial state dict，不是完整 state
- 必须追加 trace 条目

### LLM 调用
- 用 `with_structured_output(PydanticModel)`，不要手工解析 JSON
- 统一从 `app/llm/clients.py` 取工厂（全量 DeepSeek-V4-pro，ADR 0020；函数名沿用 `get_qwen_*`）
- 意图 / 参数提取节点用 `get_qwen_thinking()`（先例：swap/intent、option/extract_*）；swap 复杂提取用 `get_qwen_complex()`
- 图片 OCR 用 `get_qwen_vl()`；跨线程场景用非缓存 `make_qwen_thinking()`

### HTTP 调用
- 统一走 `OptionClient` / `SwapClient` / `TickerClient` Protocol（ADR 0001 D2），连接走 `app/tools/http_pool.py` 单例池
- 不要直接用 httpx.AsyncClient，不要在 client 里自写重试

### 提示词管理
- git `.md` 是唯一真源：改提示词直接改 `app/prompts/**/*.md` + 普通 PR（`prompt(<scope>)` commit）
- 新 LLM 节点按 ADR 0023 建 `PromptSpec`（`app/prompts/spec.py`，先例 `app/subgraphs/swap/intent.py`）；新意图可用 `/add-intent` skill

## 常见代码片段

### 新加一个节点
```python
from app.graph.safe_node import safe_node
from app.graph.state import AgentState

@safe_node
async def my_node(state: AgentState) -> dict[str, Any]:
    # 读 state
    raw = state.get("raw_text", "")

    # 做工作
    result = await do_something(raw)

    # 返回 partial update
    return {
        "my_field": result,
        "trace": [{"node": "my_node", "decision": "ok"}],
    }
```

### 新加一个 LLM 节点
```python
from app.graph.safe_node import safe_node
from app.graph.state import AgentState
from app.llm.clients import get_qwen_thinking
from app.prompts.spec import PromptSpec, register
from app.subgraphs.swap.models import MyOutput


def _build_user_message(state: AgentState) -> str:
    return f"raw_content：{state.get('raw_text', '') or ''}"


SPEC = register(PromptSpec(
    category="swap", name="something", output_model=MyOutput,
    inputs=("raw_text",), user_builder=_build_user_message,
))


@safe_node
async def extract_something(state: AgentState) -> dict[str, Any]:
    messages, prompt_name = SPEC.build_messages(state)
    llm = get_qwen_thinking().with_structured_output(MyOutput)
    result: MyOutput = await llm.ainvoke(messages)
    return {"...": result.xxx, "trace": [...]}
```

### 新加一个子图节点连接
```python
# 在 build_<product>_graph() 里
g.add_node("my_node", my_node)
g.add_edge("previous_node", "my_node")
g.add_edge("my_node", "next_node")
```

## 调试

### 查看 trace
```sql
SELECT * FROM langgraph_node_trace
WHERE message_id = 'xxx'
ORDER BY step_index;
```

### 本地重现生产 bug
1. 从 `langgraph_message_log` 拉 raw_content + quote_content
2. 写成 curl 发到本地 `POST /v1/workflows/run`，或用 `python -m harness node-run` 单独回放节点（ADR 0029）
3. 看 trace 定位哪个节点出错

### LangFuse trace
启用 `ENABLE_LANGFUSE=true`（ADR 0014），然后在 LangFuse UI 按 thread_id 搜索，能看到每一步的输入输出。

## 性能调优

### 当延迟过高
- 查 trace 各节点 duration_ms
- 大概率是 LLM 节点慢：
  - 缩短提示词（业务规则语义不变；git `.md` 为真源，改动走普通 PR）
  - 能确定性计算的步骤不走 LLM

### 当准确率下降
- 跑 `scripts/langfuse/langfuse_eval.py --local <fixture>` 定位失败 category
- 先在 `tests/fixtures/categories/` 补失败 case，再按 TDD 修复
- 检查是否提示词被意外改动：`git log app/prompts/`

## 发布流程

1. feature → develop：rebase + merge
2. develop → main：PR 审核通过 + CI 通过
3. main tag：`v0.2.0`
4. 部署到预发，跑数据集与 `scripts/drill_smoke.sh`
5. 金丝雀：按企微群组逐步切流（测试群 → 部分群 → 全量），见 `docs/on-call-runbook.md`
6. 上线观察按 ADR 0030 D3（7 天窗口）
