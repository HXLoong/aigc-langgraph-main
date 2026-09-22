<!-- 自动生成：python scripts/sync_agents_md.py —— 禁止手改。
     真源是 tests/CLAUDE.md；改那里再重新生成，提交前跑 python scripts/sync_agents_md.py --check 校验同步。 -->

# tests · 局部约定

> 测试规范见 `.claude/rules/testing.md`（金字塔 / Mock 陷阱 / TDD / Golden）。本文件只补**目录布局**与**局部命令**。
> 测试体系总入口与分层实操（mock 环境 / 真后端切换 / 排查路径）见 `docs/testing/README.md`。

## 目录布局

```
tests/
├── conftest.py            # 全局 pytest 配置（仅占位；根纪律禁止用 autouse 绕过真实业务路径）
├── fixtures/              # categories/（A 方言）+ unified_golden.jsonl（B 方言，harness 默认并入）+ README.md（历史归档已移至 docs/archive/fixtures/old_typing/）
├── intent_fixtures.py / evidence_support.py / llm_guard.py   # 共享 mock 工厂与守卫（证据必须来自真实输入；去 LLM 化模块不得持有 LLM 工厂）
├── graph/                 # 主图：拓扑 / reducer / 路由纯函数 / RetryPolicy 读写清单 / 子图契约 / 确认路径
├── nodes/                 # 节点级测试（ingest / entry_route / render / fallback / persist ...）
├── subgraphs/{swap,option,close}/  # 子图级测试（标的识别已委托 Java，无 ticker 子图）
├── api_wire/              # /v1/workflows/run 对 Java 的现行 wire 契约；原生协议迁移暂缓，保持兼容 + 幂等 + 输入映射
├── tools/                 # backend client / auth / exception / http_pool
├── observability/         # tracing / metrics / logs / health
├── integration/           # mock_api ASGI 内存集成 + 本地 MySQL opt-in（RUN_LOCAL_MYSQL_TESTS=1，CI slow job 打开）
├── harness/               # 评测台（harness/）：golden 加载、判定口径、节点 fixture 运行器、HTTP tape
├── prompts/               # 提示词治理：PromptSpec / loader / 灰度 / LangFuse 演练稿门槛
├── scripts/               # scripts/ 下运维与评估脚本的测试（导入靠 pyproject pythonpath=["."]，禁止 sys.path.insert）
└── test_*.py              # 根级：跨模块集成（test_cascade_e2e / test_smoke / test_inquiry_continuation ...）+ 导入卫生 + 注册表守护
```
```

## 局部命令（不需要全量跑时）

```bash
.venv/bin/python -m pytest tests/subgraphs/swap/ -v       # 仅互换
.venv/bin/python -m pytest -k "not e2e"                   # 跳过 E2E（快）
.venv/bin/python -m pytest --lf -x                        # last-failed + 遇错即停
```
