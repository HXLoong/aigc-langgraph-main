# 测试规范

## 三层测试金字塔

```
   E2E 集成测试 (tests/test_e2e.py)     ← 慢，少，Mock LLM + Mock 后端
   ─────────────────────────────
   子图 / 节点测试 (tests/test_*.py)   ← 中等，覆盖关键路径
   ─────────────────────────────
   模型与路由测试 (tests/test_models.py) ← 快，多，纯函数单测
```

## pytest 约定

- 所有测试必须 import 时能成功（不联网、不依赖真实 MySQL）
- 异步测试用 `@pytest.mark.asyncio`（`asyncio_mode = "auto"` 已在 pyproject.toml 配置）
- Mock 必须 patch "where it's looked up"，不是定义处

## Mock 陷阱提醒

```python
# ❌ 错误：patch 原定义位置
monkeypatch.setattr("app.tools.otc_backend.OtcBackendClient", factory)
# 因为 swap.py 已经 `from app.tools.otc_backend import OtcBackendClient`
# 名字绑到 swap 模块了，改原模块不生效

# ✅ 正确：patch 所有使用点
for target in (
    "app.tools.otc_backend.OtcBackendClient",
    "app.subgraphs.swap.OtcBackendClient",
    "app.subgraphs.option.OtcBackendClient",
    "app.subgraphs.close.OtcBackendClient",
):
    monkeypatch.setattr(target, factory)
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

- 所有新增意图必须在 `tests/fixtures/golden.jsonl` 加至少 2 条用例
- golden 格式见文件顶部注释
- 跑评估：`python scripts/eval_golden.py tests/fixtures/golden.jsonl`

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
- ⚠️ 改 Dify 原始提示词 → 不许，只能改加载逻辑，配合 golden set 回归

## 跑慢测试的技巧

```bash
pytest -v -k "not e2e"          # 跳过 E2E（只跑快速测试）
pytest -v -k "swap"             # 只跑互换相关
pytest -v --lf                  # last-failed（只跑上次失败的）
pytest -v -x                    # 遇到第一个失败就停
pytest --cov=app.nodes.route    # 覆盖率
```
