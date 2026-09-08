# 测试 Sweep + Coverage 报告 · 2026-05-13

> F4 灰度上线前的"全仓库测试体检"。看 841 个测试是否有遗漏失败 / 14 个 skip 是不是真 bug / 哪些模块覆盖率盲区影响生产。

## 1. 总览

| 指标 | 数值 |
|---|---|
| 测试总数 | **841 passed + 14 skipped + 0 failed** |
| 总运行时间 | 107s (2 min 不到) |
| 行覆盖率 | **82%**（3700 stmts，654 missed） |
| 100% 覆盖文件 | 41 个 |
| Python 版本 | 3.13.11 |

**结论：测试套件健康，0 失败。** 14 skip 全部是数据完备性问题（不是 bug）。Coverage 盲区集中在尚未接入生产的模块（checkpointer / tracing），符合 M1/M2 阶段预期。

## 2. 修复发现：test_cost_report.py import 错误

跑 sweep 时发现 `tests/observability/test_cost_report.py` ModuleNotFoundError，原因：
- 测试用 `from scripts.llm_cost_report import (...)`
- 但 `scripts/` 不是 package（无 `__init__.py`），未装到 site-packages
- 同级 `tests/test_*.py` 用 `sys.path.insert` workaround，深层目录 `tests/observability/` 没加

**修复**：`pyproject.toml [tool.pytest.ini_options]` 加 `pythonpath = ["."]`，让 repo root 自动加到 sys.path。

修后 cost_report **17 个测试全部恢复**——这些原本被静默忽略的测试现在保护成本计算逻辑。

副产物：发现 **`scripts/llm_cost_report.py` 已实现完整 LLM 成本估算**（按模型 × 方向 × token 数算价 + 按节点聚合 + 日环比增长 + 价格表 env override）。之前我推荐"token pricing 估算"未做，实际上已就位。

## 3. 14 Skip 分析（全部数据完备性，非 bug）

| Skip 来源 | 数量 | 类型 |
|---|---|---|
| `tests/subgraphs/ticker/test_golden_ticker_fixture.py::test_winner_is_known_wind_code[*]` | 14 | golden fixture 中 14 条 ticker case 没填 `expected.winner` 字段 |

**判断**：这不是 bug——是 PM 标注待补充。test 写得对（动态 skip 没填 winner 的 case，避免误报 PASS）。

**修复路径**：留给 PM 标注 14 条 ticker case 的 winner 字段，本 sweep 不动业务数据。

## 4. Coverage 盲区分析

### 4.1 0% 覆盖率文件（5 个）

| 文件 | stmts | 性质 | 行动 |
|---|---|---|---|
| `app/checkpointer/factory.py` | 33 | M2 未接入 MySQL Checkpointer，M3 联调时启用 | M3 接入 → 加 integration test |
| `app/observability/tracing.py` | 26 | OpenTelemetry 接入是 M1 占位，**实际无任何调用方**（grep 验证） | 评估是否删；如保留 → M4 接入后测 |
| `app/state.py` | 8 | TypedDict 类型定义，本身不可执行 | ✅ 预期 0%（类型注解不需测） |
| `harness/__main__.py` | 3 | `python -m harness` 入口 stub | ✅ 预期 0%（CLI dispatch） |
| `harness/case_generator/__main__.py` | 5 | 同上 | ✅ 预期 0% |
| `harness/case_generator/cli.py` | 78 | LLM paraphrase case 生成 CLI，跑过实际 case 但没单测 | 价值低（一次性工具）；F4.1 用 LLM 真后端时再加 smoke test |

### 4.2 低覆盖率模块（< 70%，**生产路径**）

| 文件 | 覆盖率 | 缺失行 | 性质 | 行动建议 |
|---|---|---|---|---|
| ~~`app/observability/health_probes.py`~~ | ~~32%~~ → **100%** ✅ | ~~71/104~~ → 0 | **PR #108 已修**：4 probe 内部 _check 全 mock（aiomysql / httpx），18 个新测试覆盖 ok/fail/timeout/disabled/total_timeout 路径 |
| `harness/cli.py` | 37% | 67/106 | `python -m harness run` 入口逻辑（参数解析 / cases 过滤 / 报告写盘），实际跑过几十次但没单测 | 中风险：harness CLI 改坏不会立即被发现。CLI 行为相对稳定，价值中等 |
| `app/subgraphs/option/intent.py` | 67% | 16/49 | option 意图识别节点的错误分支（LLM 调用失败 / Pydantic 解析失败） | 低风险：safe_node 装饰器兜底 + golden case 覆盖正常路径 |

### 4.3 中等覆盖率（70-85%，**业务节点常态**）

业务子图节点普遍 70-85%：

```
swap/cancel.py            81%  swap/confirm.py           85%  swap/place_order.py      87%
swap/query_order.py       81%  swap/hand_to_share.py     97%
option/extract_*.py     79-85%  option/intent.py          67%
close/intent.py           72%  close/place_close.py      70%  close/cancel_close.py    83%
```

**缺失行模式**：基本都是 `try/except` 异常分支（"LLM 调用失败 → safe_node 兜底"）+ HITL 中断恢复路径（trace 数据非常规结构）。**Golden case 覆盖正向路径，异常路径靠 safe_node 框架级测试保障**。

### 4.4 高覆盖率（≥ 90%，**核心模块**）

- `app/observability/alerts.py` 90% — F4 告警链
- `app/observability/metrics.py` 95% — 指标埋点
- `app/graph/main.py` 98% — 主图编译
- `app/nodes/intent_route.py` 98% — 一级路由
- `app/nodes/persist.py` 96% — checkpoint 持久化
- `app/subgraphs/ticker/tools.py` 91% — ticker 工具
- `harness/runner.py` 91% — harness 核心
- `harness/reporter.py` 95% — 报告渲染
- `harness/token_tracker.py` 93% — F4.1 token 追踪

## 5. 建议行动项

| # | 项 | 优先级 | 负责人 |
|---|---|---|---|
| 1 | PM 补 14 条 ticker case 的 `expected.winner` 字段 | 低 | PM |
| 2 | ~~M3 末：health_probes 4 个 probe 用 mock 补单测~~ ✅ PR #108（32% → 100%） | ~~**中**~~ 完成 | 工程 |
| 3 | 删 `app/observability/tracing.py`（确认无调用方）或 M4 接入 OpenTelemetry 后再测 | 低 | 工程 |
| 4 | M3 真后端联调时为 `checkpointer/factory.py` 加 integration test | 中 | 工程 |
| 5 | harness CLI 加 smoke test（解析 + 报告生成端到端） | 低 | 工程 |

## 6. 复检脚本

```bash
# 全套测试 sweep
pytest tests/ --tb=no -q

# Coverage 详细报告
pytest tests/ --cov=app --cov=harness --cov-report=term-missing:skip-covered -q --tb=no

# 跳过的测试列表
pytest tests/ -v --tb=no 2>&1 | grep -i SKIP

# 单个模块覆盖率（替换 health_probes）
pytest tests/observability/ --cov=app.observability.health_probes --cov-report=term-missing
```

## 关联

- 上线包：F4 #92-#106
- CI：`.github/workflows/ci.yml`（M3 期 workflow_dispatch only）
- ADR 一致性审计结论：已并入 ADR 0001 D8 / 0002 / 0013 / 0019 行内修订；复检能力固化为 `scripts/check_adr_refs.py`（CI 常跑，原 AUDIT-2026-05-13.md 已删除）
