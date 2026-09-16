---
name: add-intent
description: 在某个业务子图中新增一个意图类型（如互换新增 "adjust_hedge"）。使用场景：业务新增场景，需要同步加意图枚举、路由、参数提取节点、提示词、测试。
metadata:
  source: .claude/skills/add-intent/SKILL.md
  argument_hint: <product:swap|option|close> <intent_name>
---

> 自动生成自 `.claude/skills/add-intent/SKILL.md`（python scripts/sync_agents_md.py），禁止手改。 文中 `$1`、`$2` 指调用本技能时用户按顺序给出的第 1、2 个参数。

# 新增一个业务意图

## 参数
- `$1` = 产品类型：swap / option / close
- `$2` = 新意图名（snake_case，如 `adjust_hedge`）

## 执行流程

### Step 1：审查现状
- 读 `app/subgraphs/$1/` 包（`graph.py` / `models.py` / `intent.py` / 各意图节点文件）
- 列出当前已有的意图和路由

### Step 2：跟用户确认（停顿点）
**在改任何代码前，问用户**：
1. 新意图的业务含义是什么？
2. 对应的后端 API 是否已经有了？用什么 `type` 值？
3. 参数提取的字段是什么？
4. 是否需要独立的 Pydantic 输出模型，还是复用现有？
5. 是否需要 `interrupt_before`（需要人工确认）？

等用户回答后再继续。

### Step 3：改 `app/subgraphs/<product>/models.py`
- 在 `IntentType` Literal 加新值
- 若需要新输出模型，加一个 `<Intent>Output` Pydantic 类

### Step 4：在 `app/subgraphs/<product>/` 加节点文件并接路由
- 新增 `@safe_node` 装饰的提取函数 `extract_<intent>`
  - 用 `load_prompt("<product>", "<intent>")` 加载提示词
  - 用 `with_structured_output(<Intent>Output)`
- 更新 `graph.py` 的 `_INTENT_TO_NODE` 路由表 **和** `add_conditional_edges` 的 path_map（两处都要改，漏一处会静默走 unknown 兜底）
- 更新 `build_<product>_graph()`：`g.add_node` + `g.add_conditional_edges` + 合流边

### Step 5：提示词
若有对应 Dify 提示词：
- 用 `/migrate-prompt <dify-yaml> <node-title> <product>` 导入

若无：
- **停下来问用户**是否要临时手写一段
- 不要擅自硬编码提示词到代码

### Step 6：测试
调用 `test-generator` subagent（或直接补测试）：
- `test_models.py`：新 Pydantic 模型的字段测试
- `test_models.py` 路由函数映射测试
- `test_e2e.py`：1-2 条 E2E 用例（mock LLM）
- `tests/fixtures/golden.jsonl`：2 条端到端 case

### Step 7：跑验证
```bash
pytest tests/ -v -k "$1"     # 只跑相关子图测试
```

全部通过才算完成。

### Step 8：最终清单
给用户一份改动清单：
- [ ] `<product>_models.py`: 加 `IntentType` + `<Intent>Output`
- [ ] `<product>.py`: 加 `extract_<intent>` 节点 + 路由 + 子图 edges
- [ ] `app/prompts/<product>/<intent>.md`: 提示词（源自 Dify 或新写）
- [ ] `tests/test_models.py`: 模型和路由测试
- [ ] `tests/test_e2e.py`: E2E 测试
- [ ] `tests/fixtures/golden.jsonl`: golden case
- [ ] `pytest tests/ -v` 全通过
- [ ] （可选）`app/state.py`：若需要新的 State 字段

## 禁止

- 跳过"跟用户确认"步骤
- 用 mock 提示词掩盖真实需求
- 复用现有意图但改其语义（要新加，不要改旧）
- 忘了更新 `route_by_intent`
