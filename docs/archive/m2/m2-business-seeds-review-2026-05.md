# 业务方种子候选池 Review 指南（2026-05）

## 来源

业务方 Google Sheet：[场外衍生品AI交易指令模块-功能测试用例](https://docs.google.com/spreadsheets/d/1fVI8WbzdeJ14ulrxv8ENzL8bQ-t5856QpBd5lx5VS9o/edit)

修改时间：2026-05-10

## 工程层处理

由 LangGraph 工程师从 Sheet 中提取「测试数据」字段作为 `raw_content`，按以下规则映射：

- 单条无引用 + 询价语义 → `option:new_inquiry`
- 含 quote_content + "确认下单"/"确认改单"/"确认撤单" → 对应 confirm 类
- "撤单" → `cancel_order_request`（swap）/ `request_cancel_order`（option）
- "改 / 改为 / 修改" → `place_order_request`（swap）/ `request_modify_order`（option）
- "平仓"/"平 X 成"/"平一半" → `option_close:close_order_request`
- 多步对话拆成多条 case，第二条用 `quote_content` 字段串联

**输出**：`tests/fixtures/golden_business_seeds_2026-05.jsonl` · 289 条候选

**已知工程层修正**：
- g304 `"改 限价6.3"` Agent 自动映射为 `confirm_modify_order`，工程师按 v1 prompt 第 168 行（`原 modify_order_request 已统一为 place_order_request`）修正为 `place_order_request`

**Schema 校验**：289/289 全部通过 `harness.golden.GoldenCase` Pydantic 验证

## 候选池统计

### 按 product_type

| 产品 | 条数 |
|---|---|
| option | 149 |
| swap | 117 |
| option_close | 23 |
| **合计** | **289** |

### 按 intent（top）

| Intent | 条数 |
|---|---|
| new_inquiry | 81 |
| place_order_request | 72 |
| confirm_order | 56 |
| place_order_from_quote | 26 |
| close_order_request | 21 |
| cancel_order_request | 16 |
| confirm_modify_order | 8 |
| request_modify_order | 2 |
| close_order_query | 2 |
| confirm_cancel_order | 5 |
| unknown_intent | 1 |

### 多轮对话覆盖

含 `quote_content`（多轮场景）：147 / 289（51%）

## 工程层未覆盖的子集

Agent 跳过的输入（共 26 条）：

| 类型 | 数量 | 跳过原因 |
|---|---|---|
| `#TRS` / `#一站通` / `#查询` 哈希指令 | 16 | 不在 swap/option/option_close/ticker 业务范围内（CLAUDE.md 规定）|
| 单字母 `C` | 7 | 多轮对话中选交易对手的回复，脱离 quote_content 上下文无法识别 |
| 短数字 `123` / `23` | 3 | 业务方意图不明（反例噪声 vs 订单号选择无法判断） |

如需要这些用例进入 golden，业务方请补充 quote_content 上下文或明确意图后单独提供。

## Review 流程（业务方操作）

### 阶段 1：抽样校验（优先级 P0，建议先做）

1. 从候选池随机抽 **30 条**（覆盖 intent 分布）
2. 对每条核对：
   - `raw_content` 是否就是用户实际输入（不是工程师改写）
   - `expected.intent` 是否符合业务期望
   - `quote_content` 是否准确对应上一轮机器人回复
3. 标记打勾 `[x]` 或叉 `[ ]`

### 阶段 2：批量合入（pass ≥ 90% 后）

抽样 PASS 率 ≥ 90% 视为映射规则可信，工程师将候选池**整体合入** `tests/fixtures/golden.jsonl`：

```bash
cat tests/fixtures/golden_business_seeds_2026-05.jsonl >> tests/fixtures/golden.jsonl
```

合入后跑：

```bash
python -m harness run                  # 全集真 LLM 验证
python -m harness run --category swap  # 按 product 子集
```

### 阶段 3：分桶 PASS 率（grill-with-docs 第 4 决策）

| 桶 | 阈值 | 当前候选 |
|---|---|---|
| business_seed | ≥ 90% | 289（全部新增）|
| llm_paraphrase | ≥ 80% | 60（前批 LLM 候选，独立 review）|
| 总 P0 golden | ≥ 80 条 | 候选 289 + 既有 30 = **319**（远超阈值）|

合入后即解锁 P0 退出门「golden ≥ 80 条」硬条件 ✅

## 文件位置

- 候选池：`tests/fixtures/golden_business_seeds_2026-05.jsonl`
- 现有生产 golden：`tests/fixtures/golden.jsonl`（30 条）
- LLM 对抗式候选：`docs/archive/m2/m2-llm-generated-cases.md`（60 条 paraphrase）

## 下次同步建议

业务方扩 Sheet 后：

1. 工程师重跑 Drive MCP 拉取 + Agent 转换流程
2. 输出新的 `golden_business_seeds_<YYYY-MM>.jsonl`
3. 业务方 review 后合入 golden.jsonl

避免直接覆盖既有候选池——保留时间序列便于追溯。
