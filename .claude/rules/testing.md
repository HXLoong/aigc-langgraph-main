# 测试规范

## 三层 TDD 准则

判据是**被测代码属于哪一层**，先定层再决定测试写法：

| 层 | 判据 | 测试方式 | TDD |
|---|---|---|---|
| **核心需求层** | 业务规则、状态机、路由、cascade 兜底、参数提取、回执契约 | 单元测试 | **严格先 RED** |
| **支撑层** | DB 访问、外部 API 客户端、文件 IO、评测台 | 集成测试（真 DB / 真 HTTP） | 不强制 |
| ↳ 纯计算函数 | 正则、中文数字、diff 引擎、AST 分析 | 单元测试 | **严格 TDD** |
| **契约层** | DTO、枚举、Pydantic 模型、配置常量 | —— | **不写测试** |

- **核心需求层**：删代码必须立刻让测试变红（证明受保护），再补新实现转绿。
- **契约层**只有状态没有行为，手写 getter/setter 式断言无价值；字段名与类型交 Pydantic 与 Java 契约保证。这里的"不写测试"**仅指纯数据容器**（只有字段声明和框架默认行为）；含自定义 `field_validator` / `field_serializer` / `model_validator` / factory 分支的模型已有行为，属**核心需求层或支撑层**，仍需测试。
- **支撑层**强行先写测试会陷入 Mock 地狱：Mock 掉 DB 与 HTTP 后无法证明真实环境可跑，且与实现强耦合；改用集成测试（如 `mock_api` ASGITransport、真 MySQL opt-in 用例）。
- **多层归属**：一段代码同时符合多层判据时，按 **TDD 要求最高**的层归类，优先级 `纯计算函数 > 核心需求层 > 支撑层 > 契约层`。例如 `differ.py` 既像"评测台支撑"又是纯计算，按纯计算处理；`has_error()` 既像工具又是路由兜底判据，按核心需求层处理。

测试放置（参考）：E2E `tests/integration/` + `tests/test_cascade_e2e.py`；子图 / 节点 `tests/subgraphs/` · `tests/nodes/` · `tests/graph/`；纯函数 `tests/domain/` · `tests/nodes/test_route_rules.py`；`/v1/workflows/run` 对 Java 的 wire 契约 `tests/api_wire/`。

## pytest 约定

- 所有测试在 CI 占位环境变量下必须 import 成功（不联网、不依赖真实 MySQL；占位 env 见 `.github/workflows/ci.yml` fast job）
- 异步测试用 `@pytest.mark.asyncio`（`asyncio_mode = "auto"` 已在 pyproject.toml 配置）
- Mock 必须 patch "where it's looked up"，不是定义处

## Mock 陷阱提醒

```python
# ❌ 错误：patch 原定义位置
monkeypatch.setattr("app.tools.option_client.OptionClientHttpx", factory)
# 因为 option/backend.py 与 close/backend.py 都 `from ... import OptionClientHttpx`
# 名字已绑到各自模块，改原模块不生效

# ✅ 正确：patch 所有使用点（先例：tests/test_inquiry_continuation.py）
for target in (
    "app.subgraphs.option.backend.OptionClientHttpx",
    "app.subgraphs.close.backend.OptionClientHttpx",
):
    monkeypatch.setattr(target, factory)
# swap 同理：app.subgraphs.swap.backend.SwapClientHttpx（标的识别已委托 Java，本地无 ticker 子图）
```

## E2E 测试

- **用 `InMemorySaver` 代替 MySQL Checkpointer**：避免依赖数据库
- **Mock LLM 要 Mock 到 `with_structured_output` 返回的对象**：
  ```python
  mock_intent_llm = MagicMock()
  mock_intent_llm.ainvoke = AsyncMock(return_value=CloseIntentOutput(type="..."))
  mock_std.return_value.with_structured_output.return_value = mock_intent_llm
  ```
- **后端调用**：单元测试 mock Client Protocol 的使用点；集成测试走 `mock_api`（`tests/integration/`，ASGITransport 内存直连）；真后端联调只用 `scripts/probe_*.py`，不进 pytest

## 评分口径

数据集批量评分只使用确定性断言（ADR 0005），不调用 LLM Judge；旧脚本路径待迁移时显式传 `--no-judge`，关闭 Judge 不代表字段断言覆盖已经完整。平台回归逐步接入 Langfuse Dataset / Experiment / Score，harness 与本地 CLI 共用同一比较逻辑（ADR 0029）。

## Golden Set

- 所有新增意图必须在 `tests/datasets/biz/` 加至少 2 条用例，并在 `tests/datasets/intent/` 补逐轮意图标签（`scripts/check_fixture_consistency.py` 校验一致性）
- case 格式沿用对应文件既有方言（详见 `tests/datasets/README.md`）
- 跑评估：意图集 `python scripts/langfuse/langfuse_eval.py --local tests/datasets/intent`；依赖 Java 的业务集按 `run-eval` skill 由主代理调度

## 验证范围

用户指定轻量验证时，只执行最小复现、受影响的关键测试和相关静态检查。全量 pytest、真实黄金集及性能测试留到统一验收，不循环重复；交付中明确未运行的检查。该范围调整不取消业务改动的 RED → GREEN。

## 提交前自检（CI fast job 同款）

```bash
T="USE_MYSQL_CHECKPOINTER=false REQUEST_IDEMPOTENCY=false ENABLE_LANGFUSE=false"
env $T pytest <受影响的测试路径> -q               # 全量 pytest 由 CI / 统一验收跑
ruff check app/ tests/ harness/ scripts/probe_goats/
python -m mypy app/ harness/
python scripts/check_alert_threshold_consistency.py
python scripts/check_fixture_consistency.py
python scripts/check_adr_refs.py
python scripts/check_docs_layout.py
python scripts/sync_agents_md.py --check
```

## 何时写测试

- ✅ 新增节点函数、路由规则、业务分支 → 单元测试（先 RED）
- ✅ 新增纯计算工具函数（正则 / 数字解析 / diff / AST 分析） → 单元测试（先 RED）
- ✅ 修 bug → 先写复现测试，再修
- ❌ 新增 / 修改 DTO、枚举、Pydantic 模型 → **不写测试**（契约层）
- ❌ 修改 CI / 配置文件 → 不写测试（由 CI 自身与 lint 保证）
- ❌ 只断言 CLI `--help` 文案、参数解析退出码或恒真条件 → 不写
- 🔄 代码从低 TDD 层升到高 TDD 层时（容器加 `field_validator`、支撑模块被核心依赖、纯函数被路由直接调用）→ **补对应层级的测试**，删除的旧断言不豁免新行为
- ⚠️ 改活跃提示词 → 直接改 `.md` + 普通 PR review，`prompt(<scope>)` commit；需要时自行跑 `scripts/langfuse/langfuse_eval.py` 验证

## 选择性运行

```bash
pytest -k "not e2e"             # 跳过 E2E
pytest -k "swap"                # 只跑互换相关
pytest --lf -x                  # 只跑上次失败的，遇错即停
pytest --cov=app.nodes          # 覆盖率
```
