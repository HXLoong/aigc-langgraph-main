# 测试反模式

**何时读：** 写或改测试、加 mock、想给生产代码加"只给测试用"的方法时。

**核心原则：** 测代码做了什么，而不是 mock 做了什么。mock 是隔离手段，不是被测对象。
Mock 的落点规则（patch 使用点、`with_structured_output` 返回对象怎么 mock）见 `.claude/rules/testing.md`。

## 铁律

```
1. 绝不断言 mock 本身的行为
2. 绝不给生产代码加只给测试用的方法 / 开关
3. 没弄清依赖链之前绝不 mock
```

## 反模式 1：测 mock 的行为

```python
# ❌ 断言的是 mock 被调用了，而不是节点产出了正确结果
mock_llm.ainvoke.assert_awaited_once()

# ✅ 断言节点的 partial update（State 字段）
result = await option_intent(state)
assert result["intent"] == "new_inquiry"
```

`assert_awaited_*` 只在"是否调用"本身就是被测行为时才用（例如"写类节点绝不重试"）。

## 反模式 2：生产代码里的测试专用逻辑

```python
# ❌ 在 app/ 里加开关绕过真实路径
if settings.test_mode:
    return FAKE_RESULT

# ✅ 在测试里替换边界：mock HTTP 客户端 / LLM 工厂的使用点
monkeypatch.setattr("app.subgraphs.option.backend.OptionClientHttpx", fake_factory)
```

这正是根 `CLAUDE.md`「面向测试编程」的禁令：不加备用实现开关，不在 `conftest.py` 用 autouse 绕过业务路径。

## 反模式 3：没弄清依赖就 mock

mock 一个高层函数，可能顺带吃掉测试依赖的副作用（写 `state['error']`、trace、字段锁定），测试因此"通过"或莫名失败。

**先问：** 被 mock 的函数有哪些副作用？测试依赖其中哪些？
**做法：** mock 放到更低一层（HTTP / LLM 边界），保留业务代码的真实执行；先用真实实现跑一遍看清需要什么，再加最小 mock。

## 反模式 4：不完整的 mock

只 mock 了你以为会用到的字段，下游代码读到缺失字段才静默失败。

**做法：** 用真实的 Pydantic 模型（Java DTO / 节点 Output 模型）构造返回值，而不是手写半个 dict；
后端响应按 `docs/api-contracts/java-backend.md` 的完整结构构造。

## 反模式 5：测试事后补

"实现完了，再补测试"——测试一写就通过，证明不了任何东西。按 TDD：先写失败测试。

## mock 太复杂时

setup 比被测逻辑还长、每个测试都要 mock 一串对象 → 通常说明设计耦合太紧，或者该写的是集成测试
（`tests/integration/` 用 `mock_api` 的 ASGI 内存直连）。

## 危险信号

- 断言里出现 `mock` / `Mock` 的属性
- 生产代码里出现只有测试会走的分支
- 说不清 mock 为什么必要
- 删掉 mock 后测试依然通过（它没在测东西）
