# Ticker 子图实施现状（issue #15-#20）

> 截至 2026-05-10 · feature/m2-ticker-subgraph 分支

## Issue 状态总览

| Issue | 状态 | Commit |
| --- | --- | --- |
| [#16] ticker 骨架 + ReAct + TickerClient | ✅ 完成 | 已早期提交（cascade/fallback 集成）|
| [#17] tokenize 真实现 | ✅ 完成 | `97c344f` |
| [#18] completeness + rank 真实现 | ✅ 完成 | `97c344f` |
| [#19] infer_code 真实现（含动态 prompt） | ✅ 完成 | `97c344f` |
| [#20] E2E + golden 30 + HITL + 双轨 | 🟡 部分完成 | 当前 commit |

## #20 部分完成范围

### ✅ 已完成

- **ticker-only golden 20 条** (`tests/fixtures/golden_ticker_2026-05.jsonl`)
  - 覆盖 6 类核心场景：完整代码 / 短名推断 / 多命中分差大/小 / 0 命中 / 多 ticker
  - 加 fixture 验证测试（24 parameterized cases）
- **4 工具协作单测** (`tests/subgraphs/ticker/test_tools_collaboration.py`)
  - 7 个端到端业务流场景（不依赖 ReAct LLM 推理质量）
  - 验证 tokenize → completeness → rank/infer_code 串联正确
- **0 命中 fallback 行为已定义**
  - `rank` 返回 `winner=None` + `reason="no_match"`
  - 调用方业务节点应渲染 "无法识别 X，能用更标准的名称吗"
- **HITL 触发条件已定义**
  - `rank` 返回 `needs_hitl=True` + `candidates` 列表
  - 业务节点应据此触发 LangGraph `interrupt`，企微卡片返回候选

### ❌ 未完成（保留至 M3 shadow 阶段）

- **ticker 子图集成到主图链路**
  - 当前生产仍走 `app/subgraphs/ticker/resolver.py`（白名单 50 条）
  - ReAct Agent 已就绪但未 wire 到 swap/option/close 业务节点
  - 风险：替换 resolver 影响所有业务子图的 ticker 解析路径
  - 建议：M3 shadow 阶段灰度切换（5% → 25% → 100%）

- **HITL LangGraph interrupt 主图实现**
  - `interrupt` 需要 checkpointer 支持（已就绪）+ 业务节点协作
  - 需要约定企微卡片格式 + 用户回复→恢复执行的 API 协议
  - 建议：与企微集成 PR 一起做

- **harness `--mock-ticker` flag**
  - harness CLI 加 env 切换让 resolver 强制白名单（绕过 ReAct + 真后端）
  - 用于 CI 跑 < 1 分钟约束
  - 当前 ticker 子图未进 harness 链路，flag 没有意义

- **真 LLM ReAct 多步推理验证**
  - 需配齐 GOATS 真 docs + LangFuse trace
  - 留 M3 shadow 阶段实证

## 测试覆盖（总 449 passed）

| 测试文件 | 数量 | 覆盖 |
| --- | --- | --- |
| `test_skeleton.py` | 8 | hard cap / 工具签名 / 编译 |
| `test_resolver.py` | 18 | 白名单 50 条命中规则 |
| `test_tools_real.py` | 28 | tokenize 规则 / completeness HTTP / rank 分差 / infer LLM 拼接 |
| `test_tools_collaboration.py` | 7 | 4 工具串联业务流（5 核心场景 + 2 复合）|
| `test_golden_ticker_fixture.py` | 24 | 20 fixture cases parameterized + 元数据校验 |
| **合计 ticker** | **85** | **#16-#20 主体** |

## 配套接入清单（业务方决定主图集成时使用）

### Step 1：替换 ticker_resolver

`app/subgraphs/swap/place_order.py`、`app/subgraphs/option/extract_inquiry.py`、
`app/subgraphs/close/place_close.py` 等业务节点目前调：

```python
from app.subgraphs.ticker.resolver import resolve_ticker
candidates = await resolve_ticker(state["raw_text"])
```

切换到 ReAct：

```python
from app.subgraphs.ticker.graph import build_ticker_graph
agent = build_ticker_graph()
result = await agent.ainvoke({"messages": [("user", state["raw_text"])]})
# 解析 result.messages 最后一条 → list[TickerCandidate]
```

### Step 2：HITL interrupt 接入

主图 `build_main_graph()` 调用 `g.compile(checkpointer=cp, interrupt_before=["ticker_hitl"])`。
新增 `ticker_hitl` 节点检查 `state["ticker_hitl_candidates"]`，向企微返回选项卡片。
用户回复后通过 `graph.ainvoke(None, config=cfg)` 从 checkpoint 恢复。

### Step 3：harness 双轨支持

```bash
# 走 ReAct + 真后端
python -m harness run

# 走白名单 mock
HARNESS_MOCK_TICKER=true python -m harness run
```

`harness/runner.py` 在 init state 时根据 env 决定调 resolver 还是 ReAct。

## 退出门状态（ADR 0001 D9.2 ticker 子图）

| 退出门 | 阈值 | 当前 |
| --- | --- | --- |
| ticker-only golden 总数 | ≥ 30 | 🟡 20（差 10 条 — 需要业务方补真实 case）|
| from_goats=True 比例 | 100% | ✅ 白名单全部 from_goats=True |
| CI 跑 `--mock-ticker` < 1 min | required | 🟡 待主图集成后验证 |
| 工具单测 PASS | required | ✅ 85/85 |

**建议**：剩余 10 条 golden 由业务方提供"真实场景未覆盖的 case"
（如生僻俗称 / 期货合约月份变体 / 错别字），工程层无法编造。

## 相关文档

- ADR 0008（ReAct 运行时约束）
- ADR 0010（thinking 模型选择）
- ADR 0013（动态 prompt 片段加载）
- `docs/archive/m2/m2-real-llm-run-guide.md`（harness 真 LLM 跑测指南）
