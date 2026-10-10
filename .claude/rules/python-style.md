# Python 编码规范

## 版本与工具链
- Python 3.11+（严格要求，因为用了 `TypedDict` with `total=False` + `Annotated` reducer 语法）
- 依赖管理：`pyproject.toml`，不用 requirements.txt
- lint：ruff（目标行宽 100，E501 未强制）；CI 范围 `app/ tests/ harness/ scripts/probe_goats/`
- type check：mypy strict（CI 范围 `app/ harness/`）
- 格式化：`ruff format` 未在 CI 强制，只对自己新写 / 大改的文件使用，不做全仓格式化

## 类型提示

**强制**：所有函数签名必须有类型提示，包括返回值。

```python
# ✅ 正确
async def classify_intent(state: AgentState) -> dict[str, Any]:
    ...

# ❌ 错误：缺返回类型
async def classify_intent(state):
    ...
```

- 新建模块用 `from __future__ import annotations` 作为第一行（ruff 未强制，存量个别模块没有）
- 用内建泛型 `list[int]` / `dict[str, Any]`，不用 `typing.List` / `typing.Dict`
- `X | None` 代替 `Optional[X]`
- `Literal["a", "b"]` 用于枚举字符串

## 异步优先

```python
# ✅ 正确：异步 + 复用 lifespan 单例池（app.tools.http_pool.acquire_http_client）
async def load_data(client: httpx.AsyncClient) -> dict[str, Any]:
    r = await client.get(url)
    return r.json()

# ❌ 错误：在异步函数里用同步 requests
import requests   # 绝对禁止
```

- HTTP 用 httpx 异步客户端，经 `app.tools.http_pool` 获取，不自己 new
- 并发请求用 `asyncio.gather(...)`，不要串行 await
- 阻塞 IO（如 openpyxl）用 `asyncio.to_thread` 包一下（如果可能卡住事件循环）

## 错误处理

节点装饰器（`@safe_node` / `@io_node` + `add_io_node`）与重试策略见 `.claude/rules/langgraph-patterns.md`「IO 与错误」。
重试只由 LangGraph RetryPolicy 负责，不在 Client 里自写 tenacity 重试（对图不可见，写接口会重复下单）。

```python
# ❌ 错误：裸 try/except Exception
try:
    do_something()
except Exception:
    pass   # 吞掉异常
```

## Import 规范

```python
from __future__ import annotations       # 第一行

# 标准库
import asyncio
import logging
from pathlib import Path

# 第三方
import httpx
from pydantic import BaseModel

# 本项目（绝对导入）
from app.config import get_settings
from app.graph.state import AgentState
```

**禁止**：
- `from x import *`
- 相对导入（`from ..config import`）
- 循环导入（必要时在函数体内延迟导入）

## 日志

```python
# ✅ 正确
logger = logging.getLogger(__name__)
logger.info("msg=%s latency=%dms", msg_id, latency)   # 用 % 格式化

# ❌ 错误
print(...)                  # app/ 生产代码不要 print（scripts/ 的 CLI 输出例外，见 scripts/CLAUDE.md）
logger.info(f"msg={msg_id}")  # 不要 f-string（丢失结构化日志能力）
```

日志由 `app/observability/logs.py` 统一配置（structlog 接管 stdlib，ADR 0024 D5）：`LOG_FORMAT=json` 时每条是一行
JSON，`/v1/workflows/run` 期间自动带 `trace_id` / `conversation_id` / `message_id`（contextvars，
`bound_request_context`）。不要在模块里 `basicConfig` / 自己加 handler；需要额外上下文键用
`structlog.contextvars.bind_contextvars`，不要拼进消息文本。

## 命名

- `snake_case` for 函数、变量
- `PascalCase` for 类、Pydantic 模型、TypedDict
- `UPPER_CASE` for 常量、枚举
- 中文业务术语保持原样（如 `期权意图`）作为注释，但标识符用英文

## 单行函数与 lambda

- 避免 `lambda` 用于非平凡逻辑，用 `def` 定义
- 单行 `if: return` 可以接受，多行必须展开
