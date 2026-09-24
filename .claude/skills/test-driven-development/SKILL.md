---
name: test-driven-development
description: >
  TDD workflow: enforces Red-Green-Refactor cycle, test-first rules, and
  verification steps. Only trigger when the user explicitly invokes
  /test-driven-development or says "使用tdd" / "用tdd". Do NOT auto-trigger
  on general coding requests like "implement", "add", "fix", or "write".
---

# Test-Driven Development (TDD)

先写测试，看它失败，再写最小代码让它通过。

**核心原则：** 没亲眼看到测试失败，就不知道它测的是不是对的东西。

TDD 是根 `CLAUDE.md` 核心原则 5 的强制纪律；本 skill 给出完整步骤。测试规范（金字塔、Mock 陷阱、E2E 写法）
以 `.claude/rules/testing.md` 为准，本文不重复。

## 铁律

```
没有先失败的测试，就不写生产代码
```

先写了代码？删掉重来：不留作"参考"，不边写测试边"改造"它。

## 何时使用

**总是：** 新功能、bug 修复、重构、行为变更。

**例外（先问用户）：** 一次性原型、生成代码、纯配置文件、纯文档改动。

## Red → Green → Refactor

### RED：写一个失败测试

一个测试只表达一个行为，名字说清楚期望，尽量走真实代码（只在 HTTP / LLM 边界 mock）。

```python
async def test_place_order_rejects_missing_notional() -> None:
    state = {"raw_text": "买入 510300 看涨", "conversation_id": "c-1"}
    result = await swap_normalize(state)
    assert result["error"]["node"] == "swap_normalize"
```

### 验证 RED：看它失败（必做，不可跳过）

```bash
USE_MYSQL_CHECKPOINTER=false REQUEST_IDEMPOTENCY=false ENABLE_LANGFUSE=false \
  pytest tests/subgraphs/swap/test_normalize_fields.py::test_place_order_rejects_missing_notional -q
```

- 必须是**失败**（断言不成立），不是报错（导入失败、拼写错误）
- 失败信息要对应缺失的行为
- 一上来就通过？说明测的是已有行为，改测试

### GREEN：最小实现

只写让测试通过的最简代码；不顺手加功能、不重构别处。

### 验证 GREEN：看它通过（必做）

- 新测试通过
- 受影响模块的相关测试通过（同一命令前缀，按目录或 `-k` 选取）
- 全量 pytest、真实业务回归按根 `CLAUDE.md`「并行实施与验证范围」留到统一验收，交付时写明未运行项
- 测试失败？改代码，不改测试

### REFACTOR：清理

只在绿灯后做：去重、改名、抽 helper，保持测试全绿，不加新行为。

## 好测试的标准

| 维度 | 好 | 坏 |
|---|---|---|
| 粒度 | 一个行为；名字里有"和"就拆开 | `test_validates_and_submits_and_renders` |
| 清晰 | 名字描述期望行为 | `test_1`、`test_works` |
| 意图 | 体现期望的接口用法 | 围着实现细节断言 |

## 为什么顺序重要

**"写完再补测试也能验证"** —— 事后写的测试一上来就通过，证明不了任何东西：可能测错了对象、测了实现而非行为、漏了边界。先写测试迫使你看到失败，证明它真的在测东西。

**"已经手测过所有边界"** —— 手测是临时的、没有记录、改了代码无法复跑。

**"删掉 X 小时的代码太浪费"** —— 沉没成本。保留无法信任的代码才是浪费。

## 危险信号（出现任何一条：删代码，按 TDD 重来）

- 先写代码后写测试 / 测试一写就通过 / 说不清测试为什么失败
- "就这一次" / "太简单不用测" / "留着当参考" / "TDD 太教条"

## 卡住时

| 问题 | 解法 |
|---|---|
| 不知道怎么测 | 先写你希望存在的接口，先写断言；仍不行就问用户 |
| 测试太复杂 | 设计太复杂，简化接口 |
| 什么都得 mock | 耦合太紧；mock 只放在 HTTP 客户端 / LLM 工厂的使用点 |
| setup 太长 | 抽 helper / fixture；还复杂就简化设计 |

## 调试集成

发现 bug？先写复现它的失败测试，再走 TDD 循环。测试既证明修复，也防止回归。不写测试不修 bug。

## 测试反模式

加 mock 或测试工具前，读 [testing-anti-patterns.md](testing-anti-patterns.md)。

## 最后一条

```
生产代码 → 对应测试存在且先失败过
否则 → 不是 TDD
```

没有用户明确许可，不开例外。
