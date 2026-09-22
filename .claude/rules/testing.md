# 测试规范

## 三层测试金字塔

```
   E2E 集成测试 (tests/integration/ + tests/test_cascade_e2e.py)   ← 慢，少，Mock LLM + Mock 后端
   ─────────────────────────────
   子图 / 节点测试 (tests/subgraphs/ · tests/nodes/ · tests/graph/) ← 中等，覆盖关键路径
   ─────────────────────────────
   模型与路由测试 (tests/subgraphs/*/test_models.py · tests/test_intent_route.py) ← 快，多，纯函数单测
```

## pytest 约定

- 所有测试必须 import 时能成功（不联网、不依赖真实 MySQL）
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
- **后端调用通过真实后端或集成测试环境**：E2E 测试直接对接真实后端（需真实后端 + VPN），单元测试 Mock 掉 Client Protocol

## Golden Set

- 所有新增意图必须在 `tests/fixtures/categories/` 加至少 2 条用例（现役数据源，`scripts/check_fixture_consistency.py` 校验一致性）
- case 格式沿用对应文件既有方言（详见 `scripts/ai_test_langgraph/README.md`）
- 跑评估：`python scripts/langfuse/langfuse_eval.py --local <fixture>`

## 验证范围

用户指定轻量验证时，只执行最小复现、受影响的关键测试和相关静态检查。全量 pytest、真实黄金集及性能测试留到统一验收，不循环重复；交付中明确未运行的检查。该范围调整不取消业务改动的 RED → GREEN。

## 提交前自检

```bash
pytest tests/ -v                              # 全部通过
ruff check app/ tests/                        # lint 零警告
mypy app/                                     # 类型无错
```

## 何时写测试

- ✅ 新增节点函数 → 加路由测试
- ✅ 新增 Pydantic 模型 → 加字段校验测试
- ✅ 新增业务逻辑分支 → 加 E2E 覆盖
- ✅ 修 bug → 先写复现测试，再修
- ⚠️ 改活跃提示词 → 直接改 `.md` + 普通 PR review，`prompt(<scope>)` commit；需要时自行跑 `scripts/langfuse/langfuse_eval.py` 验证

## 跑慢测试的技巧

```bash
pytest -v -k "not e2e"          # 跳过 E2E（只跑快速测试）
pytest -v -k "swap"             # 只跑互换相关
pytest -v --lf                  # last-failed（只跑上次失败的）
pytest -v -x                    # 遇到第一个失败就停
pytest --cov=app.nodes.route    # 覆盖率
```
