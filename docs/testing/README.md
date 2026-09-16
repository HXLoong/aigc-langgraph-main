# 测试指南 · docs/testing 目录说明

> 本目录保存**专用测试文档**：测试计划、阶段性测试报告、现场 smoke checklist、
> 测试环境配置记录等。本文件是测试体系的**总入口与实操指南**。
>
> 纪律真源（本文不重复，冲突时以它们为准）：
> - `.claude/rules/testing.md` — 测试金字塔 / Mock 陷阱 / TDD / Golden 规范
> - `tests/CLAUDE.md` — tests/ 目录布局 + 局部命令
> - 根 `CLAUDE.md`"排查与修复流程" — bug 定位 SOP

---

## 一、测试分层全景（从快到慢）

| 层 | 跑什么 | 依赖 | 耗时 | 何时跑 |
|---|---|---|---|---|
| 1 · 单元/子图测试 | `pytest -k "not e2e"` | 无（LLM/后端全 mock） | ~30s | 每次改代码后，提交前必跑 |
| 2 · mock_api 集成测试 | `pytest tests/integration/ mock_api/` | 无（ASGI 内存直连，不起端口） | ~1s | 改 Client / 后端契约相关代码后 |
| 3 · 全链路手测（mock 后端） | uvicorn mock_api + uvicorn app + curl | 真实 LLM key | 秒级/条 | 验证单条指令的真实识别效果 |
| 4 · golden 批量评估 | `langfuse_eval.py` / `python -m harness run` | 真实 LLM key（+后端，可 mock） | 分钟级 | 改提示词/路由后、发版前 |
| 5 · 真后端探针 | `scripts/probe_*_e2e.py` | VPN + 真实测试环境 | 手动 | 联调期、现场部署时 |
| 6 · 真后端 golden 回归 | `langfuse_eval.py`（指向真后端） | VPN + LLM key | 小时级 | E3.x 退出门（PASS ≥ 92.5%） |

原则：**低层绿了才上高层**。层 1-2 零外部依赖，是 CI 与日常开发的守卫；层 3-4 验证 LLM
真实效果；层 5-6 验证真实环境契约。

## 二、命令速查

### 本地联合回归验收（Windows）

```powershell
$env:PYTHONUTF8 = '1'
$env:ENABLE_LANGFUSE = 'false'
.\.venv\Scripts\python.exe -m pytest tests/ scripts/ai_test_langgraph/ -v -W error -rs
.\.venv\Scripts\python.exe -m ruff check app/ tests/ scripts/ai_test_langgraph/
.\.venv\Scripts\python.exe scripts/ai_test_langgraph/langgraph_direct_regression.py --dry-run --limit 3
.\.venv\Scripts\python.exe scripts/ai_test_langgraph/langgraph_direct_regression.py --self-test
.\.venv\Scripts\python.exe scripts/ai_test_langgraph/automation_runner_server.py --self-test
```

直接回归 CLI 未传 `--data` 时，按文件名排序加载 `tests/fixtures/categories/`
直属的全部 JSONL；工作台默认发现范围相同，不扫描历史归档或嵌套目录。
当前是 6 份、389 条顶层用例；可重复传入 `--data` 显式选择多个文件，兼容既有格式。
详见 [工作台使用文档](../../scripts/ai_test_langgraph/README.md)。

联合 pytest 保留 `tests/api` 的原有排除及 15 项条件跳过，不新增 skip/xfail，
以零失败、零警告及 Ruff 零告警为通过条件。默认 dry-run 只验证数据加载与筛选；
两项自检不执行真实交易。检查记录分别报告本地自动化和真实业务验收状态，
真实模型准确率、客户 GOATS 业务闭环须另行取得证据。

### 分层调试命令

```bash
# 层 1 · 快速回归（提交前必跑）
.venv/bin/python -m pytest tests/ -q -k "not e2e" --tb=line 2>&1 | tail -3

# 层 2 · mock_api 集成测试（含契约校验）
.venv/bin/python -m pytest tests/integration/ mock_api/ -q

# 层 3 · 全链路手测（终端 1 起 mock，终端 2 起应用，终端 3 发指令）
uvicorn mock_api.server:app --reload --port 8099
uvicorn app.main:app --reload
curl -X POST http://localhost:8000/v1/workflows/run \
  -H "Content-Type: application/json" \
  -d '{"inputs": {"rawContent": "600519.SH 询价 3 个月平值看涨", "conversationId": "t-1"},
       "response_mode": "blocking", "user": "t-1"}'

# 层 4 · fixture 批量评估（DeepSeek Judge 打分）
.venv/bin/python scripts/langfuse_eval.py --local tests/fixtures/categories --limit 20 --concurrency 5
.venv/bin/python scripts/langfuse_eval.py --local tests/fixtures/categories --ids case-025 --no-judge  # 单 case 冒烟

# 层 5 · 真后端探针（需 VPN）
.venv/bin/python scripts/probe_real_backend_e2e.py     # 通用连通性
.venv/bin/python scripts/probe_swap_write_e2e.py       # 互换写
.venv/bin/python scripts/probe_option_write_e2e.py     # 期权写
.venv/bin/python scripts/probe_close_write_e2e.py      # 平仓写
.venv/bin/python scripts/probe_ticker_e2e.py           # 标的识别
```

## 三、本地 Mock 测试环境

`mock_api/` 是本地假后端（GOATS 22 端点 + Java 后端 10 端点，按真实 DTO 校验入参），
让全链路测试**不需要 VPN 和真实后端**。用法与 .env 配置详见
[`mock_api/README.md`](../../mock_api/README.md)，要点：

```bash
# .env 指向 mock（LLM 仍走真实 DeepSeek，只有后端是假的）
OTC_API_BASE_URL=http://127.0.0.1:8099
GOATS_BASE_URL=http://127.0.0.1:8099
SECURITIES_INSTRUMENT_URL=http://127.0.0.1:8099/admin-api/integration/securities-instrument/select
```

- mock 返回**固定 stub**，验证的是"链路通 + 契约对 + 参数提取对"，不验证业务数值正确性
- 不想产生任何写副作用（即使对 mock）：叠加 `DRY_RUN_BACKEND=true`（写类 intent 在
  Client 层拦截，读类放行）
- ⚠️ macOS 下客户端务必用 `127.0.0.1` 而非 `localhost`（IPv6 解析陷阱，见 mock README）

## 四、切换到真实客户测试环境

1. **改 .env**：三个 URL 换成真实地址（内网格式参考 `.env.example` 注释），需 VPN 可达
2. **跑探针**（层 5）：五个 `probe_*_e2e.py` 逐条过，确认契约与连通性；任何 4xx/5xx
   先解决再往下走
3. **真后端 golden 回归**（层 6）：`langfuse_eval.py` 跑 B 桶全集，退出门见
   `docs/m3-m4-roadmap.md`（E3.1 总 PASS ≥ 92.5%；B 桶 ≥ 90% / C 桶 ≥ 80%）
4. **现场 smoke**：≥ 5 条真实业务流走通（E3.5 / #86），部署用
   `scripts/deploy-customer.sh`（自带预检 + smoke 自检）

已知坑（真后端联调前必读）：
- **#178** · 两个 GOATS 客户端对 `goats_base_url` 的 `/api` 前缀拼法矛盾，真实环境必有
  一方 404 且**静默降级不抛错**——联调前先澄清
- 后端 dedup：多轮 case 间隔太短会撞"正在处理，请勿重复提交"；workaround 只允许放在
  `scripts/langfuse_eval.py`（turn 间 sleep），**严禁进业务代码**（根 CLAUDE.md P0 红线）

## 五、失败了怎么排查

按根 `CLAUDE.md`"排查与修复流程"执行，速记：

1. **层 1-2 失败**：普通 TDD——先写复现测试（RED）→ 最小修复（GREEN）→ 全量回归
2. **层 3-4 失败**：看 Langfuse 富 output（score / judge_comment / turns[i] 逐字段定位），
   或 stdout 的 per-turn trace；按 `product_type` → `intent` → `tickers` → `place_params`
   → `api_result` 的顺序锁定错误层
3. **层 5-6 失败**：先分清是契约问题（对照 `docs/api-contracts/java-backend.md`）还是
   环境问题（VPN / 鉴权 / dedup）；契约问题回到 mock 复现后按 TDD 修

## 六、本目录的文档存放约定

| 放什么 | 命名建议 |
|---|---|
| 阶段性测试报告 | `report-<阶段>-<YYYY-MM-DD>.md`（如 `report-e3.1-2026-09-01.md`） |
| 现场 smoke checklist 与执行记录 | `smoke-checklist-<客户>-<日期>.md` |
| 测试环境配置记录（脱敏） | `env-<环境名>.md` |
| 专项测试计划 | `plan-<主题>.md` |

- 报告写完、行动项闭环后按归档纪律移入 `docs/archive/`（见 `docs/archive/README.md`）
- **不放**：golden case（去 `tests/fixtures/`）、测试代码（去 `tests/`）、
  含真实密钥的配置（严禁入库）
