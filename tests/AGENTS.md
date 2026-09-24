<!-- 自动生成：python scripts/sync_agents_md.py —— 禁止手改。
     真源是 tests/CLAUDE.md；改那里再重新生成，提交前跑 python scripts/sync_agents_md.py --check 校验同步。 -->

# tests · 目录布局与局部陷阱

> 测试规范（金字塔 / Mock 陷阱 / E2E / Golden / 验证范围）只在 `.claude/rules/testing.md` 维护；TDD 纪律见根 `CLAUDE.md` 核心原则 5。
> 测试体系总入口与分层实操（mock 环境 / 真后端切换 / 排查路径）见 `docs/testing/README.md`；数据集说明见 `tests/fixtures/README.md`。

## 目录布局

```
tests/
├── conftest.py            # 全局 pytest 配置（仅占位；根纪律禁止用 autouse 绕过真实业务路径）
├── fixtures/              # 数据集：intent/（意图集）、biz/（业务验收集）等，见其 README
├── intent_fixtures.py / evidence_support.py / llm_guard.py   # 共享 mock 工厂与守卫（证据必须来自真实输入；去 LLM 化模块不得持有 LLM 工厂）
├── graph/                 # 主图：拓扑 / reducer / 路由纯函数 / 入口分流 / RetryPolicy 读写清单 / 子图契约 / 确认路径
├── nodes/                 # 主图节点：ingest / pre_route / route_rules / render / persist / record_history ...
├── subgraphs/{swap,option,close}/  # 子图级测试（模型、图路由、各意图节点）；test_common.py 守三子图共用骨架
├── domain/                # app/domain 纯业务规则单测（order_ids / numerals / sanitize）
├── api_wire/              # /v1/workflows/run 对 Java 的现行 wire 契约：兼容 + 幂等 + 输入映射
├── tools/                 # backend client / bot_context / message_client / http_pool / 异常与回执透传
├── observability/         # tracing / metrics / logs / health
├── integration/           # mock_api ASGI 内存集成 + 本地 MySQL opt-in（RUN_LOCAL_MYSQL_TESTS=1，仅本地 / 联调环境；CI 不跑）
├── harness/               # 评测台：golden 加载、判定口径、意图 runner、节点 fixture 运行器、HTTP tape
├── prompts/               # 提示词治理：PromptSpec / loader / 灰度 / LangFuse 演练稿门槛
├── scripts/               # scripts/ 下脚本的测试（导入靠 pyproject pythonpath=["."]，禁止 sys.path.insert）
└── test_*.py              # 根级：跨模块集成（test_cascade_e2e / test_smoke / test_fallback_node ...）+ 导入卫生 + 注册表守护
```

## 局部陷阱

- **命令级隔离依赖**：本地 `.env` 开着持久化，跑单测一律带
  `USE_MYSQL_CHECKPOINTER=false REQUEST_IDEMPOTENCY=false ENABLE_LANGFUSE=false` 前缀，不在 conftest 里全局改
- **没有 `.env` 时部分文件收集失败**：`tests/scripts/test_langfuse_eval*.py` 等在导入期构造 `Settings`，
  需要 CI 同款占位环境变量（见 `.github/workflows/ci.yml` 的 fast job `env`）
- **新节点要进注册表**：`tests/test_node_catalog_contract.py` 断言 `app/node_execution/catalog.py` 与主图节点集合一致
