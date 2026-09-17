# tests · 局部约定

> 测试规范见 `.claude/rules/testing.md`（金字塔 / Mock 陷阱 / TDD / Golden）。本文件只补**目录布局**与**局部命令**。
> 测试体系总入口与分层实操（mock 环境 / 真后端切换 / 排查路径）见 `docs/testing/README.md`。

## 目录布局

```
tests/
├── conftest.py            # 全局 pytest 配置（仅占位；根纪律禁止用 autouse 绕过真实业务路径）
├── fixtures/              # categories/（现役数据源）+ unified_golden.jsonl / old_typing/（归档）+ README.md
├── api/                   # FastAPI 路由测试
├── nodes/                 # 节点级测试（intent_route / render / fallback ...）
├── subgraphs/{swap,option,close,ticker}/  # 子图级测试
├── tools/                 # backend client / auth / exception
├── observability/         # tracing / metrics
└── test_*.py              # 根级跨模块集成测试（含 test_e2e.py）
```

## 局部命令（不需要全量跑时）

```bash
.venv/bin/python -m pytest tests/subgraphs/swap/ -v       # 仅互换
.venv/bin/python -m pytest -k "not e2e"                   # 跳过 E2E（快）
.venv/bin/python -m pytest --lf -x                        # last-failed + 遇错即停
```
