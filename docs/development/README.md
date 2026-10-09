# 开发指南

本目录回答"本地怎么开发、调试、排错"：

| 文档 | 用途 |
|---|---|
| 本页 | 环境准备、日常命令、新功能流程、最佳实践、调试与发布 |
| [troubleshooting.md](./troubleshooting.md) | **开发期**遇错快查（Q&A）；生产故障见 [../operations/](../operations/README.md) |
| [nodes-run.md](./nodes-run.md) | `POST /v1/nodes/run` 节点级调试接口与节点回归 |

## 环境准备

### 系统要求
- Python 3.11+（严格）
- MySQL 8.0.19 ≤ version < 9.6.0
- Docker + Docker Compose（运行自托管 Langfuse 时需要）
- app 与本地评测无需 Node.js；AI 辅助工具的安装要求见各自文档

### 初始化

```bash
git clone <repo>
cd otc-agent
cp .env.example .env        # 填入真实配置；MYSQL_URI 指向 Java 现有数据库
pip install -e ".[dev]"     # 含 pytest/ruff/mypy
# 在 Java 数据库执行一次初始化（LangGraph 不自带 MySQL 容器）
mysql -h <HOST> -P <PORT> -u <USER> -p --database=<JAVA_DATABASE> < sql/init.sql
PYTHONUTF8=1 USE_MYSQL_CHECKPOINTER=false ENABLE_LANGFUSE=false \
    python -m pytest tests/graph/test_entry_branches.py tests/graph/test_entry_route_guard.py -q
```

无数据库的本地单轮调试设置 `ENVIRONMENT=development`、`USE_MYSQL_CHECKPOINTER=false`、`MYSQL_URI=""`。生产必须启用 checkpoint；仅关闭 checkpoint 不会关闭已配置 URI 的节点审计。Windows 安装、PowerShell 环境变量和 V2 调用示例见 [根 README](../../README.md)。

## 日常命令

```bash
# 启动服务
uvicorn app.main:app --reload --port 8000

# 跑 app 核心测试（先相关文件，完整验收再全量）
PYTHONUTF8=1 USE_MYSQL_CHECKPOINTER=false ENABLE_LANGFUSE=false python -m pytest tests/ -q
PYTHONUTF8=1 USE_MYSQL_CHECKPOINTER=false ENABLE_LANGFUSE=false python -m pytest tests/ -q -k "swap"

# 代码质量
ruff check app/ tests/                 # lint
ruff format app/ tests/                # 格式化
mypy app/                              # 类型

# 评估（黄金数据集）
python -m harness run --group biz --backend mock      # 业务黄金集全量，mock 后端
python -m harness run --group intent --backend mock   # 意图黄金集全量
python -m harness run --file tests/datasets/biz/swap_prod.jsonl --case ai_trade_assist_prod_swap_order_case_1 --backend java  # 仅授权单条
python -m harness run --case case-021 --backend mock  # 指定单条用例

```

黄金集参数与执行限制见 [测试指南](../testing/README.md)。Harness 固定请求已启动的 `127.0.0.1:8000`，不启动 app 或 mock_api、不修改服务配置。评测输入缺省 V2，显式版本原值透传。Java 全量仅在明确授权后运行，不因部署自动执行。

### HTTP 业务调用

普通业务请求显式传入 V2，账号与群使用授权身份，消息 ID 每次调用保持唯一。

```json
{
  "inputs": {
    "rawContent": "查可平持仓",
    "messageId": 100000000000001,
    "conversationId": "local-read-example",
    "userId": "<授权测试账号>",
    "roomId": "<授权测试群>",
    "atBot": true,
    "fastQuery": "0",
    "existingCommand": "0",
    "robotVersion": "V2"
  },
  "response_mode": "blocking",
  "user": "<授权测试账号>"
}
```

请求入口为 `POST /v1/workflows/run`，接口结构见本地 `/docs`。

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
- 统一从 `app/llm/clients.py` 取 `get_llm_*` 工厂；`LLM_PROVIDER` 显式选择 deepseek / qwen / openai_compatible，`LLM_MODEL_*` 选择模型（ADR 0020）。
- 业务只有 `parse_instruction` 调 `get_llm_standard()`；`get_llm_structured()` 复用 STANDARD，THINKING 供离线生成，COMPLEX 保留但当前业务不用。角色名称不自动开启思考。
- 每次工具调用最多一次真实模型请求、零重试。仅支持文本与 Excel，图片在模型前拒绝。
- 修改配置后重启；换模型需重新验收，当前基线为 deepseek-v4-pro。

### HTTP 调用
- 统一走 `OptionClient` / `SwapClient` / `MessageClient` / `GoatsAgentClient` Protocol，连接走 `app/tools/http_pool.py` 单例池；不调用证券查询接口（ADR 0025）
- 不要直接用 httpx.AsyncClient，不要在 client 里自写重试

### 提示词管理
- git `.md` 是唯一真源：改提示词直接改 `app/prompts/**/*.md` + 普通 PR（`prompt(<scope>)` commit）
- 模型解析契约按 ADR 0023 建 `PromptSpec`（`app/prompts/spec.py`）；业务模型入口是 `app/nodes/parse_instruction.py`，修改不得增加同次调用的模型请求。新意图可用 `/add-intent` skill

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

### 声明解析契约（示意，不新增第二次模型请求）
```python
from app.graph.safe_node import safe_node
from app.graph.state import AgentState
from app.llm.clients import get_llm_standard
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
    llm = get_llm_standard().with_structured_output(MyOutput)
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
- 跑 `python -m harness run --group intent --backend mock` 定位失败用例
- 先在 `tests/datasets/biz/` 补失败 case，再按 TDD 修复
- 检查是否提示词被意外改动：`git log app/prompts/`

## 发布流程

1. feature → develop：rebase + merge
2. develop → main：PR 审核通过 + CI 通过
3. main tag：`v0.2.0`
4. 部署到预发，跑数据集与 `scripts/drill_smoke.sh`
5. 金丝雀：按企微群组逐步切流（测试群 → 部分群 → 全量），见 `docs/operations/on-call-runbook.md`
6. 上线观察按 ADR 0030 D3（7 天窗口）
