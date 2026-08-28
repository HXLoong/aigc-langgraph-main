# Python AI Agent 项目生成 / 迁移质量保障手册

> 目标：给 AI 或自己一份通用的规范，使生成的 Python 项目达到 80~90 分工程质量。
> 适用场景：从零生成、从低代码平台（Dify/Coze/n8n）迁移、从原型代码重构。
> 语言：Python 3.11+

---

## 如何使用本文档

**生成新项目时**：把第一章的 Master Prompt 发给 AI，作为系统级约束。  
**迁移已有工作流时**：先看第二章翻译表，再用第一章约束生成代码。  
**Review 生成结果时**：用第三章 Checklist 逐条验收，不通过的打回重写。

---

## 第一章：Master Prompt（直接发给 AI）

```
你是一个资深 Python 工程师。我需要你生成一个高质量的 Python AI Agent 项目。
在生成任何代码之前，你必须完整阅读并遵守以下所有规范，不得省略、简化或用注释代替实现。

业务背景：[在这里填写你的业务场景，一句话即可]
外部依赖：[列出你要调用的 API、数据库、第三方服务]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A. 项目结构规范
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
按以下结构组织代码，不允许把所有代码堆在一个文件里：

  app/
  ├── main.py              # Web 框架入口 + 生命周期管理
  ├── config.py            # 全局配置（pydantic-settings）
  ├── state.py             # 数据模型（TypedDict / Pydantic）
  ├── nodes/
  │   └── common.py        # 横切关注点（装饰器、工具函数）
  ├── subgraphs/           # 业务子模块（每个业务域一个文件）
  ├── tools/               # 外部服务客户端（每个服务一个文件）
  ├── llm/                 # LLM 客户端封装
  └── prompts/             # 提示词文件（.md，只读）
  tests/
  ├── conftest.py          # 共享 fixtures（Mock 工厂在这里）
  ├── test_models.py       # 纯函数 / 模型校验测试（快）
  └── test_e2e.py          # 端到端集成测试（Mock 外部依赖）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
B. 配置规范
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 所有配置通过 pydantic-settings + .env 文件管理：
   class Settings(BaseSettings):
       model_config = SettingsConfigDict(env_file=".env", extra="ignore")
       api_key: str           # 必填，无默认值，启动时即报错
       api_base: str
       log_level: Literal["DEBUG","INFO","WARNING","ERROR"] = "INFO"

2. 用 @lru_cache(maxsize=1) 包装 get_settings()，全局单例。
3. 禁止在代码任何位置硬编码 API Key、密码、URL、提示词字符串。
4. 提供 .env.example 文件列出所有必填变量及说明。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
C. 错误处理规范（最重要）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 实现一个 safe_node 装饰器，职责：
   - 捕获节点函数内所有异常，不让异常向外传播
   - 把错误信息写入 state['error'] 字段
   - 自动注入耗时（duration_ms）到 trace
   示例实现：
     def safe_node(fn):
         @functools.wraps(fn)
         async def wrapper(state):
             start = time.monotonic()
             try:
                 result = await fn(state)
                 result.setdefault("trace", []).append(
                     {"node": fn.__name__, "status": "ok",
                      "ms": int((time.monotonic()-start)*1000)}
                 )
                 return result
             except Exception as exc:
                 logger.exception("节点 %s 失败", fn.__name__)
                 return {"error": f"{fn.__name__}: {exc}", "trace": [...]}
         return wrapper

2. 所有业务节点函数必须用 @safe_node 装饰。
3. 业务节点内部不写 try/except，让装饰器统一兜底。
4. 最终有一个 render 节点检查 state['error']，生成用户友好的错误回复。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
D. 外部服务客户端规范
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
每个外部服务（后端 API、数据库、第三方平台）必须封装为独立客户端类：

1. 使用 async with 上下文管理器（__aenter__ / __aexit__）管理连接。
2. 网络错误（超时、连接失败）用 tenacity 重试 3 次，指数退避：
   @retry(stop=stop_after_attempt(3),
          wait=wait_exponential(multiplier=0.5, max=4.0),
          retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
          reraise=True)
   async def _post(self, path, payload): ...

3. 实现统一的 _normalize() 方法屏蔽后端响应差异，调用方只看 code / result。
4. 业务错误（code != 0）不重试，只重试网络错误。
5. 禁止在节点函数内直接 import httpx 并调用，必须通过客户端类。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
E. LLM 调用规范
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 禁止 json.loads(response.content) 手工解析 LLM 输出。
2. 所有 LLM 输出必须用 .with_structured_output(PydanticModel) 强制结构化：
   class IntentOutput(BaseModel):
       type: Literal["a", "b", "c"]
       confidence: float = Field(ge=0.0, le=1.0)
   
   llm = get_llm().with_structured_output(IntentOutput)
   result: IntentOutput = await llm.ainvoke(messages)

3. 所有提示词存为 app/prompts/<category>/<name>.md，用 load_prompt() 加载：
   def load_prompt(category, name) -> str:
       path = Path(__file__).parent / category / f"{name}.md"
       return path.read_text(encoding="utf-8")
   用 @lru_cache 包装，避免重复 IO。

4. LLM 客户端在 app/llm/clients.py 集中管理，按能力分档（standard/thinking/vision）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
F. 状态与数据流规范
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 用 TypedDict(total=False) 定义全局状态，字段按来源分组：
   - 输入（不可变）/ 上下文 / 路由决策 / 业务参数 / 输出 / Trace
2. 并行分支合并的字段用 Annotated[list, add]（如 trace）。
3. 提供 make_initial_state(**input_fields) 函数，给所有字段设默认值，
   防止下游节点读到 KeyError。
4. 节点函数只返回需要更新的字段（partial dict），不返回整个 state。
5. 路由函数（决定走哪条分支的函数）必须是纯函数：不调 LLM，不做 IO，只读 state。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
G. 有状态服务生命周期规范
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
数据库连接池、消息队列连接、LangGraph Checkpointer 等有状态资源：
1. 在 app/main.py 的 lifespan 函数里统一管理（启动 → 注册到 app.state → yield → 关闭）：
   @asynccontextmanager
   async def lifespan(app):
       db = await init_db()
       app.state.db = db
       yield
       await db.close()

2. 必须是应用级单例，不在每个请求里新建。
3. 工厂函数放在独立模块（如 app/checkpointer/factory.py），main.py 只调用。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
H. 测试规范
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 所有测试必须在不联网、不连真实数据库的环境下通过。
2. 测试分三层：
   - 快层：纯函数 / Pydantic 模型校验，不 Mock 任何东西
   - 中层：单个节点 / 函数，Mock 外部 IO
   - 慢层（E2E）：Mock LLM + Mock HTTP，跑完整流程
3. Mock 打到「使用处」，不是定义处：
   # 错误：monkeypatch.setattr("app.tools.client.MyClient", mock)
   # 正确：monkeypatch.setattr("app.subgraphs.swap.MyClient", mock)
4. E2E 测试用内存存储替代真实数据库（InMemorySaver / SQLite）。
5. conftest.py 提供共享 fixtures：mock_settings（清 lru_cache）、mock_client。
6. pyproject.toml 里设置 asyncio_mode = "auto"，避免每个 async test 手写 mark。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
I. 代码风格规范
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 每个文件第一行：from __future__ import annotations
2. 所有函数签名必须有类型提示（含返回值）
3. 异步优先：能 async 就 async，并发请求用 asyncio.gather()
4. 日志用 logging.getLogger(__name__)，% 格式化，不用 f-string（保留结构化）
5. 禁止 from x import *，使用绝对路径导入
6. 注释只写 WHY（为什么这样做），不写 WHAT（代码本身已经说明了）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
J. 可观测性规范
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 每个节点通过 state['trace'] 记录：节点名、状态、耗时、关键决策。
2. 日志配置区分环境：development 用可读格式，production 用 JSON（方便采集）。
3. 提供 /health 端点返回服务状态和关键配置开关。
4. 预留可观测性接入点（Langfuse / OpenTelemetry），用 feature flag 控制开关。

生成顺序（严格按此顺序，后面的文件依赖前面的）：
  1. pyproject.toml
  2. .env.example
  3. app/state.py（TypedDict + 枚举 + make_initial_state）
  4. app/config.py（Settings + get_settings）
  5. app/nodes/common.py（safe_node 装饰器）
  6. app/tools/<service>_client.py（HTTP 客户端）
  7. app/llm/clients.py
  8. app/prompts/<category>/<name>.md（提示词占位文件）
  9. app/subgraphs/<product>_models.py（Pydantic 输出模型）
 10. app/subgraphs/<product>.py（子图 / 子模块）
 11. app/graphs/main_graph.py 或等价的主流程编排
 12. app/main.py（FastAPI + lifespan）
 13. tests/conftest.py
 14. tests/test_models.py
 15. tests/test_e2e.py
```

---

## 第二章：从低代码工作流迁移的翻译表

当你有 Dify / Coze / n8n / Zapier 的工作流配置时，按此表找到对应的代码位置：

| 工作流元素 | 迁移到代码的位置 | 注意事项 |
|---|---|---|
| LLM 节点的 System Prompt | `app/prompts/<category>/<name>.md` | 原文原封存入，不改内容 |
| LLM 节点的输出变量 | `<product>_models.py` 里的 Pydantic 模型字段 | 用 Literal 约束枚举值 |
| if-else / Switch 条件分支 | 纯函数 `route_xxx()` + 框架的条件路由 | 纯函数，不含 IO |
| HTTP Request 节点 | `app/tools/<service>_client.py` 的方法 | 加重试和 normalize |
| Code 节点（Python 脚本） | 普通 Python 函数，作为工具函数或节点 | 直接翻译，加类型提示 |
| 平台管理的会话变量 | `AgentState` TypedDict 字段 | 按来源分组 |
| 平台管理的对话历史 | `load_history()` 从 checkpointer 读 | 加截断防止超 context |
| 平台内置错误处理 | `@safe_node` 装饰器 + `render` 节点兜底 | 所有节点都要套 |
| 子工作流 / 工具工作流 | `app/subgraphs/<product>.py` 子图 | 编译后嵌入主图节点 |
| 平台管理的连接池 / 会话 | `app/main.py` lifespan + 全局单例 | 不在请求里新建 |
| 环境变量配置 | `app/config.py` Settings 字段 | `Field(...)` 必填无默认 |
| 工作流入口参数（Start 节点） | `make_initial_state()` 函数 | 所有字段给默认值 |

**迁移三步骤**：

```
Step 1  读工作流配置 → 画节点拓扑图（不要急着写代码）
        识别：输入 → 预处理 → 路由 → [各业务子流程] → 输出 → 审计

Step 2  提取所有 LLM 节点的提示词 → 存为 .md 文件
        这是最核心的资产，原文保留，不做改写

Step 3  按翻译表逐个元素转换
        先转数据模型（state.py），再转基础设施（client/checkpointer），最后转业务逻辑
```

---

## 第三章：验收 Checklist（Review 时逐条检查）

生成完代码后，让 AI 对照以下清单自检，未通过的条目必须修改后重新确认。

### 🔴 致命问题（必须修复，否则生产会崩）

```
□ 每个业务节点都有 @safe_node（或等价的异常捕获装饰器）
□ 没有任何 json.loads(llm_response) 出现
□ 有状态资源（DB连接池、Checkpointer）是应用级单例，不在请求里新建
□ 路由函数是纯函数，不含 LLM 调用或 IO 操作
□ make_initial_state() 给所有 State 字段设了默认值（防 KeyError）
```

### 🟠 高优先级问题（影响可靠性和可维护性）

```
□ HTTP 客户端有 tenacity 重试，且只重试网络错误（不重试业务错误）
□ 没有硬编码的 API Key / Secret / URL / 提示词字符串
□ Mock 是 patch 到使用处（import 该类的模块），不是定义处
□ E2E 测试用内存存储，不依赖真实数据库或网络
□ 所有函数签名有类型提示（含返回值）
□ 节点函数只返回 partial dict（需要更新的字段），不返回整个 state
```

### 🟡 中优先级问题（影响可观测性和运维）

```
□ 每个节点的 trace 记录了：节点名、状态（ok/error）、耗时 ms
□ 日志用 % 格式化，不用 f-string
□ 有 /health 端点
□ 配置有 log_level 和 environment 字段，日志格式按环境切换
□ .env.example 列出了所有必填变量
□ 测试在 pyproject.toml 配置了 asyncio_mode = "auto"
```

### 🟢 加分项（区分 80 分和 90 分）

```
□ 并发 IO 用 asyncio.gather()，不串行 await
□ 提示词用 load_prompt() + @lru_cache，不重复读文件
□ 最终有 render 节点统一处理 state['error']，给用户友好回复
□ conftest.py 的 mock_settings fixture 会清除 get_settings.cache_clear()
□ HTTP 客户端有 _normalize() 方法统一处理后端响应码差异
□ Settings 必填字段用 Field(...)，有描述性的 description 参数
```

---

## 第四章：三个最容易被 AI 偷懒的地方

AI 在生成代码时有三种典型的"走捷径"行为，需要在 prompt 里明确禁止：

### 偷懒 1：用注释代替实现

```python
# ❌ AI 经常这样生成
class BackendClient:
    async def _post(self, path, payload):
        # TODO: 添加重试逻辑
        return await self._client.post(path, json=payload)

# ✅ 要求：直接实现，不接受 TODO
```

**在 prompt 里加**：「不允许出现 TODO、pass（非抽象类）、raise NotImplementedError，所有函数必须有完整实现。」

### 偷懒 2：测试只测 happy path

```python
# ❌ AI 经常只写这一个测试
def test_intent_classification():
    result = classify("我要买期权")
    assert result.type == "new_inquiry"

# ✅ 要求：每个关键函数至少测试 happy path + 1个边界/错误情况
```

**在 prompt 里加**：「每个测试文件至少包含：正常输入、非法输入（应报错）、边界值各一个测试用例。」

### 偷懒 3：把所有代码堆在 main.py

```python
# ❌ AI 图方便会把路由、节点、客户端全写在一个文件
# app/main.py 里有 500+ 行

# ✅ 要求：main.py 只做三件事：配置日志、lifespan、注册路由
```

**在 prompt 里加**：「app/main.py 不超过 100 行，所有业务逻辑必须在对应子模块里。」

---

## 第五章：pyproject.toml 最小依赖参考

```toml
[project]
name = "your-project"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
    # Web 框架
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",

    # LangGraph（如果用）
    "langgraph>=0.6.0",
    "langchain>=0.3.0",
    "langchain-openai>=0.2.0",

    # HTTP 客户端 + 重试
    "httpx>=0.27.0",
    "tenacity>=8.5.0",

    # 数据验证 + 配置
    "pydantic>=2.8.0",
    "pydantic-settings>=2.4.0",

    # 日志
    "structlog>=24.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "ruff>=0.6.0",
    "mypy>=1.11.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"          # async test 自动识别

[tool.ruff]
line-length = 100

[tool.mypy]
python_version = "3.11"
strict = true
```

---

## 总结：80 分的本质

> 80 分不是靠写了多少代码，而是靠**把每类问题只解决一次**：
>
> - 所有节点异常 → `@safe_node` 解决一次
> - 所有外部 IO 重试 → `BackendClient._post` 解决一次  
> - 所有配置读取 → `get_settings()` 解决一次
> - 所有 LLM 解析 → `with_structured_output` 解决一次
> - 所有测试依赖 → `conftest.py` fixtures 解决一次
>
> 业务节点只写业务逻辑，基础设施问题不在业务代码里重复出现。
> 这一条原则，值 20 分。
