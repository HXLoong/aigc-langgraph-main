# otc-agent · Claude Code Memory

场外衍生品 AI 指令助手。FastAPI + LangGraph + MySQL，从 Dify 工作流迁移而来。
企微群客户消息 → 意图解析 → 后端业务/交易系统。

## 关键命令

```bash
# 开发
pip install -e ".[dev]"          # 首次安装
docker compose up -d mysql        # 启 MySQL 依赖
docker compose exec mysql mysql -uroot -prootpassword < sql/schema.sql  # 建业务表
uvicorn app.main:app --reload     # 启服务（本地开发）
pytest tests/ -v                  # 跑全部测试（目标 49+ 通过）
pytest tests/test_e2e.py -v       # 只跑端到端测试

# 评估与运维
python scripts/eval_golden.py tests/fixtures/golden.jsonl
python scripts/shadow_compare.py --langgraph <url> --dify <url> --sample <file>
python scripts/export_dify_prompts.py <dify-yaml-dir> <output-dir>
```

## 项目结构

```
app/
├── main.py                  # FastAPI 入口 + lifespan
├── state.py                 # AgentState（TypedDict）+ 所有枚举
├── graphs/main_graph.py     # 主图组装
├── subgraphs/               # 业务子图（swap / option / close / ticker）
│   └── *_models.py          # 每个子图的 Pydantic 模型
├── nodes/                   # 顶层节点（ingest/route/persist/render/history）
├── tools/otc_backend.py     # 后端 HTTP 客户端（unified，带重试）
├── checkpointer/factory.py  # AIOMySQLSaver 生命周期
├── llm/clients.py           # Qwen standard / thinking / VL
├── prompts/                 # 23 个真实 Dify 提示词（.md 资源文件）
└── api/routes.py            # /v1/message + /v1/message/confirm
```

详见 @docs/ARCHITECTURE.md，规则详见 `.claude/rules/`。

## 核心原则（永远有效）

1. **提示词不硬编码在代码里** —— 从 `app/prompts/**/*.md` 用 `load_prompt()` 加载
2. **LLM 输出用 `with_structured_output(PydanticModel)`** —— 绝不手工解析 JSON 字符串
3. **每个节点用 `@safe_node` 装饰** —— 异常降级到 state['error']，不让图崩
4. **State 字段只通过 TypedDict 约定** —— 新增字段必须先在 `app/state.py` 中声明
5. **测试优先** —— 改代码前先改/加测试。商业逻辑必须有单元测试，链路必须有 E2E
6. **不碰 Dify 原始提示词内容** —— 23 个 .md 文件是生产验证过的资产，只做加载不做改写
7. **标的代码必须 from_goats=True** —— Ticker Agent 的绝对约束，任何标的最终都要过 goats 库

## 绝对禁止

- **硬编码 API Key / Secret** —— 必须通过 `app.config.get_settings()`，读环境变量
- **在节点函数内抛未捕获异常** —— 用 `@safe_node` 包住
- **MySQL 版本不符合 8.0.19 ≤ v < 9.6.0 的假设** —— AIOMySQLSaver 兼容性硬约束
- **修改 `app/prompts/**/*.md` 的内容** —— 这是从 Dify 原封导入的生产资产
- **直接 httpx.AsyncClient 调后端** —— 走 `OtcBackendClient`（否则 mock 不生效，E2E 会断）
- **在 main 分支直接改业务子图** —— 走 feature branch + PR

## 代码风格

- Python 3.11+，严格类型提示
- ruff lint，行宽 100
- 异步优先：能 async 就 async
- 中文注释 OK，docstring 简洁清晰
- 不加 emoji（生产代码）

## 当前阶段

v1.0 已完成：骨架 + 标的识别 + 业务子图 + 真实 Dify 提示词 + 历史加载。
下一步：Shadow 双跑验证差异率 → 金丝雀切换。

详见：
- 架构：@docs/ARCHITECTURE.md
- Dify 迁移：@docs/DIFY_MIGRATION.md
- 开发指南：@docs/DEVELOPMENT.md
- 常见问题：@docs/TROUBLESHOOTING.md
