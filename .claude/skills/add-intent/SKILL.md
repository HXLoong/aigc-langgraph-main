---
name: add-intent
description: 在某个业务子图中新增一个意图类型（如互换新增 "adjust_hedge"）。使用场景：业务新增场景，需要同步加意图枚举、路由、参数提取节点、提示词、测试。
argument-hint: <product:swap|option|close> <intent_name>
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# 新增一个业务意图

归属判定与执行清单以 [ADR 0007](../../../docs/adr/0007-subgraph-vs-intent-scope-rule.md) 为准；节点写法以
`.claude/rules/langgraph-patterns.md` 与 `.claude/rules/prompt-management.md` 为准。新增意图遵守 [ADR 0031](../../../docs/adr/0031-single-model-request-per-message.md) 的每消息一次模型请求上限，现有链路迁移见工作计划。本 skill 只给停顿点和改动清单。

## 参数
- `$1` = 产品类型：swap / option / close（close 子图的提示词目录是 `app/prompts/option_close/`）
- `$2` = 新意图名（snake_case，如 `adjust_hedge`）

## 执行流程

### Step 1：审查现状
- 读 `app/subgraphs/$1/`：`graph.py`（`_INTENT_TO_NODE` 与条件边）、`models.py`（`<Product>IntentType`）、`intent.py`、各意图节点
- 按 ADR 0007 四条规则确认它确实归现有子图；命中任一条就改走 `subgraph-builder`

### Step 2：跟用户确认（停顿点）
**改任何代码前，问用户**：
1. 业务含义与典型原话？
2. 对应后端 API 与 `type` 值是否已存在（对照 `docs/api-contracts/java-backend.md`）？
3. 要提取哪些字段？哪些能用正则 / 枚举 / 规则确定（归 Code），哪些必须 LLM 抽原文候选？
4. 是写动作吗？写动作走文本二阶段确认（ADR 0021），范围校验由 `app/domain/confirmation.py` 执行

等用户回答后再继续。

### Step 3：意图识别
- `app/subgraphs/<product>/models.py`：`<Product>IntentType` 加枚举值，意图输出模型的 `Field(description=)` 同步说明
- 更新本轮联合解析的产品/意图/候选契约及提示词；当前 `intent.md` 等资产作为迁移输入，不另加独立的分类或提取请求

### Step 4：参数节点
- 能由 Code 确定的字段：`@safe_node` 纯计算节点
- 需要 LLM 的字段纳入本轮唯一联合解析：`PromptSpec` + 原文候选契约 + `@safe_node`，零重试；不得在意图分类后增加参数模型请求。最终值由 Code 归一化节点决定
- 写后端的节点用 `@safe_node`，绝不自动重试；后端响应如实透传

### Step 5：接路由与登记
- `graph.py`：在 `_INTENT_TO_NODE` 登记新意图 → 节点（条件边由 `app/subgraphs/common.py` 的 `add_intent_dispatch` 自动生成；漏登记会静默走 unknown 兜底），加节点与汇合边
- 节点契约登记：`app/node_execution/catalog.py`；trace 中文名：`app/observability/node_labels.py`

### Step 6：测试（先 RED 再 GREEN，见 `test-driven-development` skill）
- `tests/subgraphs/<product>/test_graph_routing.py`：新意图的路由用例
- 节点单测：放在对应 `tests/subgraphs/<product>/test_<node>.py`；补全链路调用次数断言，模型失败后请求次数仍不超过一次
- 数据集：`tests/fixtures/biz/` 至少 2 条（`scripts/check_fixture_consistency.py` 守护）；意图集
  `tests/fixtures/intent/` 补对应逐轮标签
- 需要批量生成测试且用户已授权子代理时，可派 `test-generator`

### Step 7：跑验证（轻量）
```bash
USE_MYSQL_CHECKPOINTER=false REQUEST_IDEMPOTENCY=false ENABLE_LANGFUSE=false \
  pytest tests/subgraphs/$1/ tests/test_node_catalog_contract.py -q
python scripts/check_fixture_consistency.py
```
全量 pytest 与真实业务回归按根 `CLAUDE.md`「并行实施与验证范围」留到统一验收。

### Step 8：交付清单
- [ ] `models.py`：`<Product>IntentType` + 输出模型字段说明
- [ ] 联合解析提示词 + 产品/意图/候选契约，`prompt(<scope>)` commit
- [ ] 参数节点（Code / 候选 + 归一化）
- [ ] `graph.py`：`_INTENT_TO_NODE` + 节点 + 边
- [ ] `catalog.py` + `node_labels.py` 登记
- [ ] 测试 + biz ≥ 2 条 + 意图集标签
- [ ] 已运行 / 未运行的检查写明

## 禁止

- 跳过"跟用户确认"步骤
- 复用现有意图但改其语义（要新加，不要改旧）
- 让模型直接决定交易最终值，或把提示词正文写进 Python
- 在代码 / 配置里维护标的等业务数据字典（根 `CLAUDE.md` P0）
