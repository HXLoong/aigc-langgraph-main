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
pytest tests/test_e2e.py -v            # 只跑 E2E
pytest --cov=app/                      # 覆盖率

# 代码质量
ruff check app/ tests/                 # lint
ruff format app/ tests/                # 格式化
mypy app/                              # 类型

# 评估
python scripts/eval_golden.py tests/fixtures/golden.jsonl
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
- 新增 State 字段 → 先改 `app/state.py`，再在节点里用
- 不要在节点里"偷偷"塞新字段（会破坏类型提示和测试）

### 节点函数
- 永远加 `@safe_node` 装饰器
- 返回 partial state dict，不是完整 state
- 必须追加 trace 条目

### LLM 调用
- 用 `with_structured_output(PydanticModel)`，不要手工解析 JSON
- 意图分类用 `get_qwen_standard()`
- 复杂参数提取用 `get_qwen_thinking()`
- 图片 OCR 用 `get_qwen_vl()`

### HTTP 调用
- 统一走 `OtcBackendClient`（重试 + mock 友好）
- 不要直接用 httpx.AsyncClient

### 提示词管理
- **不要**改 `app/prompts/*.md` 内容
- **要**通过 `load_prompt(category, name)` 加载
- 新增提示词走 `/migrate-prompt` skill

## 常见代码片段

### 新加一个节点
```python
from app.nodes.common import safe_node
from app.state import AgentState

@safe_node
async def my_node(state: AgentState) -> dict[str, Any]:
    # 读 state
    raw = state["wechat_input"]["raw_content"]

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
from app.llm.clients import get_qwen_standard
from app.prompts import load_prompt
from app.subgraphs.xxx_models import MyOutput

@safe_node
async def extract_something(state: AgentState) -> dict[str, Any]:
    prompt = load_prompt("swap", "something")
    llm = get_qwen_standard().with_structured_output(MyOutput)

    user_msg = f"raw={state['wechat_input']['raw_content']}"
    result: MyOutput = await llm.ainvoke([
        ("system", prompt.system),
        ("user", user_msg),
    ])
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
  - 缩短提示词（但 Dify 原始提示词不要改）
  - 减少不必要的节点（Agent 循环次数）

### 当准确率下降
- 跑 `eval_golden.py` 定位失败 category
- 用 `dify-reviewer` agent 做对齐分析
- 检查是否提示词被意外改动：`git log app/prompts/`

## 发布流程

1. feature → develop：rebase + merge
2. develop → main：PR 审核通过 + CI 通过
3. main tag：`v0.2.0`
4. 部署到预发：跑 shadow compare 24h
5. 金丝雀：5% 流量，观察 1-3 天
6. 全量切换
