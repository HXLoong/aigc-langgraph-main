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
cp .env.example .env        # 填入真实配置
pip install -e ".[dev]"     # 含 pytest/ruff/mypy
docker compose up -d mysql
docker compose exec mysql mysql -uroot -prootpassword < sql/schema.sql
pytest tests/ -v            # 应看到 49+ 通过
```

## 日常命令

```bash
# 启动服务
uvicorn app.main:app --reload --port 8000

# 跑测试
pytest tests/ -v                       # 全部
pytest tests/ -v -k "swap"             # 只跑互换
pytest tests/integration/ tests/test_cascade_e2e.py -v   # 只跑集成 / E2E
pytest --cov=app/                      # 覆盖率

# 代码质量
ruff check app/ tests/                 # lint
ruff format app/ tests/                # 格式化
mypy app/                              # 类型

# 评估
python scripts/langfuse_eval.py --local tests/fixtures/categories
python scripts/shadow_compare.py --langgraph ... --dify ... --sample ...

# 提示词
python scripts/export_dify_prompts.py <dify-yaml-dir> <out-dir>
```

## 添加新功能的标准流程

1. **feature branch**：`git checkout -b feature/adjust-hedge`
2. **跟 Claude Code 对话**：描述需求，让它规划步骤
3. **先写测试**：TDD，让 test-generator agent 帮忙
4. **小步提交**：每完成一层功能提交一次
5. **跑 golden set**：确认准确率没退步
6. **提 PR**：模板见 `.claude/rules/git-workflow.md`

## 最佳实践

### 状态设计
- 新增 State 字段 → 先改 `app/graph/state.py`，再在节点里用（`app/state.py` 仅剩兼容 shim）
- 不要在节点里"偷偷"塞新字段（会破坏类型提示和测试）

### 节点函数
- 永远加 `@safe_node` 装饰器
- 返回 partial state dict，不是完整 state
- 必须追加 trace 条目

### LLM 调用
- 用 `with_structured_output(PydanticModel)`，不要手工解析 JSON
- 统一从 `app/llm/clients.py` 取工厂（全量 DeepSeek-V4-pro，ADR 0020；函数名沿用 `get_qwen_*`）
- 意图 / 参数提取节点用 `get_qwen_thinking()`（先例：swap/intent、option/extract_*）；swap 复杂提取用 `get_qwen_complex()`
- 图片 OCR 用 `get_qwen_vl()`；跨线程场景用非缓存 `make_qwen_thinking()`

### HTTP 调用
- 统一走 `OptionClient` / `SwapClient` / `TickerClient` 三个 Protocol（ADR 0001 D2；重试 + 可 mock）
- 不要直接用 httpx.AsyncClient

### 提示词管理
- git `.md` 是唯一真源：改提示词直接改 `app/prompts/**/*.md` + 普通 PR（`prompt(<scope>)` commit）
- Dify 侧更新走 `dify/sync.py` → `scripts/export_dify_prompts.py` → 人工 diff 选择性合入，不要一键覆盖
- 新 LLM 节点按 ADR 0023 建 `PromptSpec`（`app/prompts/spec.py`，先例 `app/subgraphs/swap/intent.py`）；`/migrate-prompt` skill 可辅助迁移

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

### 查看某个会话的 state
```bash
curl http://localhost:8000/v1/conversations/<conversation_id>/state | jq
```

### 查看 trace
```sql
SELECT * FROM node_trace
WHERE message_id = 'xxx'
ORDER BY step_index;
```

### 本地重现生产 bug
1. 从生产日志/shadow_compare 表拉 raw_content + quote_content
2. 写成 curl 发到本地 /v1/message
3. 看 trace 定位哪个节点出错

### LangFuse trace
启用 `ENABLE_LANGFUSE=true`（ADR 0014），然后在 LangFuse UI 按 thread_id 搜索，能看到每一步的输入输出。

## 性能调优

### 当延迟过高
- 查 trace 各节点 duration_ms
- 大概率是 LLM 节点慢：
  - 换更快的模型（standard 代替 thinking）
  - 缩短提示词（业务规则语义不变；git `.md` 为真源，改动走普通 PR）
  - 减少不必要的节点（Agent 循环次数）

### 当准确率下降
- 跑 `scripts/langfuse_eval.py --local <fixture>` 定位失败 category
- 用 `dify-reviewer` agent 做对齐分析
- 检查是否提示词被意外改动：`git log app/prompts/`

## 发布流程

1. feature → develop：rebase + merge
2. develop → main：PR 审核通过 + CI 通过
3. main tag：`v0.2.0`
4. 部署到预发：跑 shadow compare 24h
5. 金丝雀：5% 流量，观察 1-3 天
6. 全量切换
