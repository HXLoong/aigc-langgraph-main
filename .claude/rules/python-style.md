# Python 编码规范

## 版本与工具链
- Python 3.11+（严格要求，因为用了 `TypedDict` with `total=False` + `Annotated` reducer 语法）
- 依赖管理：`pyproject.toml`，不用 requirements.txt
- lint：ruff（行宽 100）
- type check：mypy strict
- 格式化：ruff format（黑体风格）

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

- 用 `from __future__ import annotations` 作为每个文件第一行
- 用内建泛型 `list[int]` / `dict[str, Any]`，不用 `typing.List` / `typing.Dict`
- `X | None` 代替 `Optional[X]`
- `Literal["a", "b"]` 用于枚举字符串

## 异步优先

```python
# ✅ 正确：异步
async def load_data(client: httpx.AsyncClient) -> dict:
    r = await client.get(url)
    return r.json()

# ❌ 错误：在异步函数里用同步 requests
import requests   # 绝对禁止
```

- httpx.AsyncClient 是标准选择
- 并发请求用 `asyncio.gather(...)`，不要串行 await
- 阻塞 IO（如 openpyxl）用 `asyncio.to_thread` 包一下（如果可能卡住事件循环）

## 错误处理

```python
# ✅ 正确：节点用 @safe_node
@safe_node
async def my_node(state: AgentState) -> dict[str, Any]:
    # 这里的异常会被装饰器捕获，转成 state['error']
    result = await risky_operation()
    return {"result": result}

# ✅ 正确：HTTP 客户端用 tenacity
@retry(stop=stop_after_attempt(3),
       wait=wait_exponential(multiplier=0.5, max=4.0),
       retry=retry_if_exception_type(httpx.TimeoutException))
async def _post(self, path, payload):
    ...

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
from app.state import AgentState
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
print(...)                  # 生产代码不要 print
logger.info(f"msg={msg_id}")  # 不要 f-string（丢失结构化日志能力）
```

## 命名

- `snake_case` for 函数、变量
- `PascalCase` for 类、Pydantic 模型、TypedDict
- `UPPER_CASE` for 常量、枚举
- 中文业务术语保持原样（如 `期权意图`）作为注释，但标识符用英文

## 单行函数与 lambda

- 避免 `lambda` 用于非平凡逻辑，用 `def` 定义
- 单行 `if: return` 可以接受，多行必须展开
