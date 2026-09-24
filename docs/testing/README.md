# 测试指南 · docs/testing 目录说明

> 本目录保存**仍在使用的测试说明**：测试分层与命令、数据集组织、测试环境与种子数据。
> 本文件是测试体系的**总入口与实操指南**；带日期的评估 / 测试报告放 [../reports/](../reports/README.md)。
>
> | 文档 | 用途 |
> |---|---|
> | 本文 | 测试分层、黄金集依赖矩阵、命令与失败定位 |
> | [local-backend-seed.md](./local-backend-seed.md) | 本地合成身份种子与验收边界 |
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
| 6 · 真后端数据集回归 | `scripts/local_eval.py` / `langfuse_eval.py`（指向真后端） | VPN + LLM key | 小时级 | 发版前（评测门见 ADR 0030 D3） |

原则：**低层绿了才上高层**。层 1-2 零外部依赖，是 CI 与日常开发的守卫；层 3-4 验证 LLM
真实效果；层 5-6 验证真实环境契约。

## 一a、黄金集依赖矩阵：哪些能进 CI

| 数据集 | 目录 | 外部依赖 | 在哪跑 | 评分 |
|---|---|---|---|---|
| **意图集**（路由 + 意图 + 标的原文提取） | `tests/fixtures/intent/` | 只有 LLM 网关；后端由仓库内 `mock_api/` 顶替，**不碰 Java / GOATS** | GitHub Actions `intent-eval`（PR 触碰提示词 / 路由意图节点 / 评估器 / 意图集时自动跑；也可手动 Run workflow）+ 本地 | `det_intent_match_pass` / `det_instrument_match_pass` 确定性评估器，本地算，不需要 Langfuse；`--fail-under` 给退出码 |
| **业务集**（询价 / 下单 / 平仓卡片与后端联动） | `tests/fixtures/categories/`；`unified_golden.jsonl` 为显式选择的历史参考集 | Java 后端 + GOATS + 授权测试账号 / 群 / 对手 / 持仓 | **只在开发 / staging 环境**手动跑（`scripts/local_eval.py` / `langfuse_eval.py --dataset business-*`），绝不进 CI | 三个文本断言 + `otc-option-judge` Judge |

```bash
# 意图集本地（与 CI 同一条命令；终端 1 起 mock_api）
uvicorn mock_api.server:app --port 8099
OTC_API_BASE_URL=http://127.0.0.1:8099 GOATS_BASE_URL=http://127.0.0.1:8099 \
  python scripts/langfuse/langfuse_eval.py --local tests/fixtures/intent --fail-under 0.95 --report .harness-runs/intent-eval.json
```

CI 用到的环境变量（全部指向 mock、只有 `QWEN_API_BASE` / `QWEN_API_KEY` 是 secrets）见 `.github/workflows/intent-eval.yml`。
未配置这两个 secrets 时，PR 触发只跑 fixture lint 并告警跳过评估（不算通过），手动触发则失败；配好后自动生效。

## 二、命令速查

### 提交前本地检查（与 CI fast job 一致）

```bash
ruff check app/ tests/ harness/ scripts/probe_goats/
python -m mypy app/ harness/
python scripts/check_alert_threshold_consistency.py
python scripts/check_fixture_consistency.py
python scripts/check_adr_refs.py
python scripts/sync_agents_md.py --check
pytest tests/ -q -k "not e2e"
```

以零失败、零告警为通过条件；保留本地 MySQL 等条件跳过，不新增 skip/xfail。
真实模型准确率与客户业务闭环须另行取得证据。

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
.venv/bin/python scripts/langfuse/langfuse_eval.py --local tests/fixtures/categories --limit 20 --concurrency 5
.venv/bin/python scripts/langfuse/langfuse_eval.py --local tests/fixtures/categories --ids case-025 --no-judge  # 单 case 冒烟

# 层 4a · 意图集（只调 LLM + mock 后端，确定性 product_type/intent 比对，不跑 Judge；见 docs/langfuse/workflow-guide.md §8）
.venv/bin/python scripts/langfuse/langfuse_eval.py --local tests/fixtures/intent --concurrency 3

# 层 5 · 真后端探针（需 VPN）
.venv/bin/python scripts/probe_real_backend_e2e.py     # 通用连通性
.venv/bin/python scripts/probe_swap_write_e2e.py       # 互换写
.venv/bin/python scripts/probe_option_write_e2e.py     # 期权写
.venv/bin/python scripts/probe_close_write_e2e.py      # 平仓写
```

## 三、本地 Mock 测试环境

`mock_api/` 是本地假后端（GOATS 22 端点 + Java 后端 10 端点，按真实 DTO 校验入参），
让全链路测试**不需要 VPN 和真实后端**。用法与 .env 配置详见
[`mock_api/README.md`](../../mock_api/README.md)，要点：

```bash
# .env 指向 mock（LLM 仍走真实 DeepSeek，只有后端是假的）
OTC_API_BASE_URL=http://127.0.0.1:8099
GOATS_BASE_URL=http://127.0.0.1:8099
```

- mock 返回**固定 stub**，验证的是"链路通 + 契约对 + 参数提取对"，不验证业务数值正确性
- 不想产生任何写副作用（即使对 mock）：叠加 `DRY_RUN_BACKEND=true`（写类 intent 在
  Client 层拦截，读类放行）
- ⚠️ macOS 下客户端务必用 `127.0.0.1` 而非 `localhost`（IPv6 解析陷阱，见 mock README）

## 四、切换到真实客户测试环境

1. **改 .env**：三个 URL 换成真实地址（内网格式参考 `.env.example` 注释），需 VPN 可达
2. **跑探针**（层 5）：四个 `probe_*_e2e.py` 逐条过，确认契约与连通性；任何 4xx/5xx
   先解决再往下走
3. **真后端数据集回归**（层 6）：`langfuse_eval.py` 跑 B 桶全集，退出门见
   ADR 0030 D3（总 PASS 率不低于上一基线；B 桶 ≥ 90% / C 桶 ≥ 80%）
4. **现场 smoke**：≥ 5 条真实业务流走通，部署用
   `scripts/deploy-customer.sh`（自带预检 + smoke 自检）

已知坑（真后端联调前必读）：
- **GOATS agent 路径** · 统一配置 `GOATS_BASE_URL`（主机根，或带 `/api` 尾缀，客户端会归一），
  客户端自动补全 `/api/internal/agent/*`；两种基址写法均有单测锁定
- 后端 dedup：多轮 case 间隔太短会撞"正在处理，请勿重复提交"；workaround 只允许放在
  `scripts/langfuse/langfuse_eval.py`（turn 间 sleep），**严禁进业务代码**（根 CLAUDE.md P0 红线）

## 五、失败了怎么排查

按根 `CLAUDE.md`"排查与修复流程"执行，速记：

1. **层 1-2 失败**：普通 TDD——先写复现测试（RED）→ 最小修复（GREEN）→ 全量回归
2. **层 3-4 失败**：看 Langfuse 富 output（score / judge_comment / turns[i] 逐字段定位），
   或 stdout 的 per-turn trace；按 `product_type` → `intent` → `place_params`
   → `api_result` 的顺序锁定错误层（标的问题核对传给后端的原文与后端工具日志）
3. **层 5-6 失败**：先分清是契约问题（对照 `docs/api-contracts/java-backend.md`）还是
   环境问题（VPN / 鉴权 / dedup）；契约问题回到 mock 复现后按 TDD 修

## 六、本目录的文档存放约定

本目录只放仍在使用的测试说明（如 `local-backend-seed.md`）。一次性的评估、测试报告按 `YYYY-MM-DD-<topic>.md`
放 [../reports/](../reports/README.md)，结论吸收后删除；评测运行输出写 `.harness-runs/`，不进 `docs/`；
golden case 放 `tests/fixtures/`，测试代码放 `tests/`，含真实密钥的配置严禁入库。总规则见 [../README.md](../README.md#存放规则)。
