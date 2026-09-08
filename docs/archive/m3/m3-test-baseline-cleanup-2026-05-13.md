# M3 测试基线整治 · 2026-05-13

> Tony 提出"fixtures 数据集混乱 + 测试既不在真实环境也不基于 Mock API"两个问题，F4 切流前 P0 双拳齐出处理。

## 1. 问题诊断（实证）

### 1.1 fixtures 不同步

| 文件 | 行数 | id 风格 | 实际加载入口 |
|---|---|---|---|
| `golden.jsonl` | 358 | `g001-g358` | **pytest** (test_harness.py / test_intent_route.py) |
| `unified_golden.jsonl` | 489 | `swap-001 / opt-001` | **`python -m harness run`** |
| `option_golden.jsonl` | 131 | `opt-001` | scripts/merge_golden.py 输入 |
| `golden_business_seeds_2026-05.jsonl` | 287 | `g101+` | 仅 docs 引用 |
| `golden_ticker_2026-05.jsonl` | 34 | `tk001` | ticker 单测专用 |

**核心问题**：
1. `golden.jsonl` (358) 和 `unified_golden.jsonl` (489) **id 共 0 重合**，但 raw_content 维度 unified 是 superset（其中 207 条共有 + unified 多 55 条 + 0 条 golden 独有）—— 历史 schema 迁移产物
2. pytest 跑的（358 条）和 harness CLI 跑的（489 条）**不是同一份基线**
3. 5 份 fixture 缺职责文档化，新人 / 业务方 review 时困惑

### 1.2 测试环境分层（实证）

| 层 | 现状 | 频率 |
|---|---|---|
| pytest 单测 | 96 文件 / 841 测试，48 个用 `unittest.mock` patch LLM + httpx | 每次 commit |
| **`mock_api/server.py`** | 完整 FastAPI 模拟 GOATS 20 端点 + Java 后端 9 端点 | **存在但 pytest 不用，资产闲置** |
| 真后端 `scripts/probe_*_e2e.py` | E3.* 跑过几次 | 不持续 |
| `tests/api/*` 真 GOATS 端点 | `--ignore=tests/api` 默认排除 | 0 |

**核心问题**：mock_api server **存在却没被 pytest 用**。业务子图改了，CI 跑全绿，但 mock_api 这层中间真实度的保护从未启用。

## 2. P0 双拳齐出（本次实施）

### 拳 1 · fixture 职责矩阵 + 一致性 lint

**新增 `tests/fixtures/README.md`**：
- 5 份 fixture 职责矩阵（哪个文件干什么 / 谁加载 / 写入约束）
- 数据流图（人工录入 → jsonl → unified → harness run）
- 不变量 3 条（CI lint 校验）
- 加 case 工作流（场景 A/B/C）
- 历史包袱说明（schema 迁移 / docs/m2-final-report 数字不一致）

**新增 `scripts/check_fixture_consistency.py`**：

校验 3 个不变量（CI lint）：
1. `unified` 的 raw_content ⊇ `golden` 的 raw_content（防 merge 漏跑）
2. `golden` 中 ADR 0015 锚点 g001-g030 全在（防误删）
3. 5 份 fixture id 命名规范（防风格漂移）

接入 `.github/workflows/ci.yml` 作为新 step（与 ADR 0019 阈值 lint 并列）。

跑通：
```
✅ tests/fixtures 一致性 OK（5 个 fixture · 1299 总 cases）
```

### 拳 2 · mock_api 接入 pytest（业务 client 集成测试）

**改 3 个 client 加 `transport` 注入参数**（仅测试用，生产零影响）：

```python
class OptionClientHttpx:
    def __init__(self, ..., transport: httpx.AsyncBaseTransport | None = None):
        ...
    def _client_kwargs(self) -> dict:
        kw = {"timeout": ..., "trust_env": False}
        if self._transport is not None:
            kw["transport"] = self._transport
        return kw
```

`OptionClientHttpx` / `SwapClientHttpx` / `TickerClientHttpx` 都改。

**新增 `tests/integration/`**：
- `conftest.py` · 3 个 fixture（option_client / swap_client / ticker_client）通过 `httpx.ASGITransport(mock_api.app)` 跑到 mock_api 内存调用，**无端口、零启动开销**
- `test_clients_via_mock_api.py` · 17 测试覆盖：
  - OptionClient operate 4 种 intent + query_close_orders
  - SwapClient operate 4 种 intent + get / get_conversation_orders
  - TickerClient search × 2 / inference / counterparty
  - transport 注入不影响生产路径（烟测）

**这正是用户问题 2 的答案**：现在业务 client 既能跑单测（unittest.mock）也能跑 mock_api 集成测试（ASGITransport），真后端 probe 仍可用——三层测试金字塔补齐。

## 3. 验证

| 维度 | 数据 |
|---|---|
| 集成测试 | **17 passed**（0.4s） |
| 完整回归 | **876 passed, 14 skipped, 0 failed**（195s）—— 之前 841 + 17 集成 + 18 health_probes 新增 |
| fixture lint | ✅ 5 份 1299 cases 全过 |
| CI workflow | 新 step 接入 |
| 客户端改动影响生产 | 0（transport 默认 None） |

## 4. 不在本次范围

| 项 | 为什么不做 |
|---|---|
| 把 golden.jsonl deprecated | 含 g001-g030 ADR 0015 规则层锚点，仍被 test_intent_route.py 使用，不能删 |
| 修订 docs/archive/m2/m2-real-llm-final-report.md "317 条" 数字 | 历史报告冻结，新文档引用 README.md 即可 |
| 把所有业务子图 e2e 测试改成调 mock_api | 工程量大，本 PR 只补 client 层入口；子图层后续按需迁移 |
| 真后端 probe 定时化 | 需要 Tony 对齐 cron 调度 + 通知策略 |

## 5. F4 切流影响

| 改动前风险 | 改动后状态 |
|---|---|
| pytest/harness 跑不同 fixture，PASS 率口径不一致 | ✅ README 明确双入口职责 + CI 防漂移 |
| 改业务 client 后只单测全绿，mock_api 资产未利用 | ✅ tests/integration/ 跑通 client → mock_api 全链路 |
| 业务方 review 时困惑用哪份基线 | ✅ README §1 职责矩阵 + §4 工作流 |

## 关联

- 触发：用户问题"fixtures 混乱 + 测试不在真实环境也不基于 Mock API"
- README：`tests/fixtures/README.md`
- Lint：`scripts/check_fixture_consistency.py` · `.github/workflows/ci.yml`
- 集成：`tests/integration/conftest.py` + `test_clients_via_mock_api.py`
- 关联 ADR：0001 D2 (3 client 拆分) / 0015 (锚点定义) / 0019 (CI lint 模式参考)
