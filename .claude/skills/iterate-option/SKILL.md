---
name: iterate-option
description: 期权链路批量评估与迭代。批量跑→按失败 trace 归类根因→TDD 修复→重跑验证。连续自驱动循环，直到全部通过或用户叫停。
argument-hint: [--limit N] [--filter 期权询价] [--dry-run]
allowed-tools: Read, Bash, Write, Edit, Grep
---

# 期权链路批量迭代

## 核心流程（自驱动循环）

```
┌─────────────────────────────────────────────────┐
│ 1. 跑 eval 批次（后台 + 阻塞等待）                │
│ 2. 读失败 case 的 per-turn trace，找根因          │
│ 3. 用 TDD 修根因：先写失败测试，再改代码           │
│ 4. pytest 守卫（全量回归）                        │
│ 5. 重跑受影响的 case 验证修复                      │
│ 6. 扩大批次，回到步骤 1                            │
└─────────────────────────────────────────────────┘
```

**绝对禁止停下来问用户。不允许 pause/suspend。你是一个持续的自动化循环。**

## 环境

```bash
# 在仓库根目录运行；Python 用仓库 venv
# Windows: .venv/Scripts/python.exe；macOS / Linux: .venv/bin/python
```

## 命令速查

```bash
# 评测批次（本地 fixture 模式）
python scripts/langfuse_eval.py --local tests/fixtures/categories --limit 10 --concurrency 5
python scripts/langfuse_eval.py --local tests/fixtures/categories --limit 30 --concurrency 10
python scripts/langfuse_eval.py --local tests/fixtures/categories --concurrency 10   # 全量

# 只重跑失败的 case
python scripts/langfuse_eval.py --local tests/fixtures/categories --ids case-025,case-026 --concurrency 2

# 按意图类型聚焦
python scripts/langfuse_eval.py --local tests/fixtures/categories --filter option/place_from_quote --concurrency 5

# 跳过 Judge（只检查 reply_text 非空，跑得快）
python scripts/langfuse_eval.py --local tests/fixtures/categories --ids case-025 --no-judge

# pytest 守卫
python -m pytest tests/ -q --tb=line 2>&1 | tail -5
```

## 跑 eval 的正确方式

```python
# 1. 后台启动 eval
Bash(command="python scripts/langfuse_eval.py --local tests/fixtures/categories --limit 20 --concurrency 10 2>&1",
     run_in_background=True, timeout=600000, description="Run eval batch N")

# 2. 等待完成（background task 完成时自动通知，不需要 Monitor/Poll）
# 3. 从输出中提取分析数据
```

## 读 Trace：定位死在哪个节点

eval 失败报告每条 case 输出 per-turn 详情（**stdout 文本格式**）：

```
[0.7] opt-018: 第2轮路由错误，返回了互换参数而非期权下单确认
  期望: 机器人返回期权下单确认信息...
  第1轮 [option/new_inquiry] | quote=无
    trace : ingest → intent_route[rule:keyword[kw:看涨]→option] → option_intent[intent=new_inquiry] → ...
    reply : -----场外期权询价详情-----...
  第2轮 [option/place_order_from_quote] | quote=120c '-----场外期权询价详情-----...'
    trace : ... → intent_route[rule:quote_marker→option] → option_extract_place_or_modify → render
    reply : -----互换订单参数-----  ← 这里出错
```

**关键字段说明：**

| 字段 | 含义 | 看什么 |
|---|---|---|
| `[product_type/intent]` | 本轮路由结果 | 是否路由正确 |
| `quote=Nc 'preview'` | 传入的引用内容（N 字符） | quote_content 是否正确传入 |
| `trace: node[decision] → ...` | 节点决策链（累积，本轮在末尾） | 哪个节点做了什么决策 |
| `reply` | 机器人实际回复 | 和期望对比 |

> **注意**：`trace` 是累积的（LangGraph reducer add），多轮 case 的 trace 包含所有历史轮。  
> 本轮节点决策在 trace 末尾，往前找分界点（第一个 `ingest` 是新一轮的开始）。

## Langfuse 富 output（AI 查错的最高效路径）

每个 eval case 都同步写到 Langfuse Cloud（https://us.cloud.langfuse.com），outer span
的 `output` 字段是**结构化富集 JSON**，比 stdout 文本格式信息更全：

```jsonc
{
  "expected": "机器人返回期权订单已确认提交，并提示订单已接收、等待交易员审核。",
  "score": 0.0,
  "judge_comment": "第三轮确认意图未被识别，未执行确认下单操作",
  "turns": [
    {
      "turn": 1, "raw": "600519.SH，欧式看涨,1M,80%", "reply": "-----场外期权询价详情-----...",
      "product_type": "option", "intent": "new_inquiry",
      "tickers": [{"wind": "600519.SH", "desc": "贵州茅台", "goats": true}],
      "place_params": {"action": "inquiry", "orderList": [{"stockCode": "...", "optionType": "欧式看涨", ...}]},
      "api_result": null, "api_code": null,
      "error": null,
      "trace": "ingest → intent_route[rule:keyword[kw:看涨]→option] → option_intent[...] → ...",
      "quote_passed": ""
    },
    {"turn": 2, ..., "api_result": "正在处理，请勿重复提交", ...},
    {"turn": 3, ..., "error": {"node": "option_extract_confirm", "type": "...", "message": "..."}}
  ]
}
```

**AI 查错 SOP**（用 Langfuse trace URL 比读 stdout 快得多）：

1. **eval 跑完看 stdout**：`LangFuse 写入成功  run=local-YYYYMMDD-HHMMSS  host=...` 这行带 run name
2. **打开 Langfuse Cloud**：按 run name 过滤，找到失败 case
3. **点开 case trace**：
   - 顶层 output：`expected` / `score` / `judge_comment` 一眼锁定差异
   - `turns[i]` 数组：每轮的路由 / 抽取参数 / 后端响应 / 错误 / 节点路径
   - 左侧子 span 树：每个 LLM 调用的 prompt / completion / token / latency（CallbackHandler 自动嵌套）
4. **快速判断错误层**：
   - `product_type` 错 → router 问题（[app/nodes/intent_route.py](app/nodes/intent_route.py)）
   - `intent` 错 → 子图 intent.py 提示词或 LLM 漂移
   - `tickers` 缺失或错 → ticker 子图（[app/subgraphs/ticker/](app/subgraphs/ticker/)）
   - `place_params.orderList` 字段漏 → 子图 extract_*.py 提示词
   - `api_result` 含"正在处理"/"请勿重复" → 后端 dedup，看 [app/nodes/render.py](app/nodes/render.py) 软错误回退是否触发
   - `error` 非空 → 节点抛异常，看 `error.node` + `error.message`
5. **写 TDD 测试**：直接复用 Langfuse 上看到的 `turns[i].raw` + 期望行为，写最小复现

**这套富 output 怎么生成的**（[scripts/langfuse_eval.py:289-340](scripts/langfuse_eval.py#L289-L340)）：
- `run_langgraph_pipeline` 每轮收集 product_type/intent/tickers/place_params/api_result/error 简化版
- `_run_one` 在 `lf.start_as_current_observation(as_type="chain")` 上下文里：
  1. 调 graph.ainvoke 跑业务流（CallbackHandler 自动嵌套子 span）
  2. 调 judge_by_deepseek 评分
  3. `span.update(output={...富集 dict...})` 一次写完
  4. `lf.create_score(trace_id=span.trace_id, ...)` 挂分到同一 trace
- 全程不再要看 stdout，Langfuse UI 一处看全部

## 根因归类模板

### Step 1: 提取统计
```
用例数: N | 通过率: X/N (Y%) | 平均分: Z
```

### Step 2: 失败归类（看 trace 和 Judge comment）

| 失败模式 | trace/reply 特征 | 高频文件 | 优先级 |
|---|---|---|---|
| 路由到错误 product_type | `intent_route[llm→swap]` 但期望 option | `app/nodes/intent_route.py` | P0 |
| quote_content 未触发 quote_marker | 第2轮 `intent_route[llm→swap]` 而非 `rule:quote_marker→option` | `app/nodes/intent_route.py` | P0 |
| 零命中误触发 | reply 含"无法识别" 但未经历 ticker 解析 | `app/nodes/render.py`, `app/state.py` | P0 |
| 期权走互换渲染 | reply 含"-----互换订单参数-----" 但 product_type=option | `app/nodes/render.py` | P0 |
| 意图识别错误 | `option_intent[intent=wrong_intent]` | `app/prompts/option/intent.md` | P1 |
| 参数提取缺字段 | Judge 说"参数遗漏" | `app/subgraphs/option/extract_*.py` + 提示词 | P1 |
| 后端返回错误 | reply 含"请求失败：" | 后端集成 / 参数传递 | P1 |
| 多轮 tickers 丢失 | 第2轮 `tickers=[]` 但 turn1 已解析 | `app/state.py` make_initial_state | P0 |
| 反案例穿透 | Judge 说"不应执行但执行了" | `app/subgraphs/option/` | P2 |
| Judge JSON 解析失败 | comment="JSON解析失败" | 非代码 bug，重跑 | - |

### Step 3: TDD 修根因（必须遵守）

调用 `/test-driven-development` skill，按其 workflow 执行。**禁止跳过。**

## 常见根因与修法（本项目经验）

### 路由类
- `intent_route` quote_marker 层失效 → 检查 `_QUOTE_MARKERS` 列表，确认标记字符串精确匹配
- 订单号前缀关键词（OPT-/CO-/H-）被送到 GOATS → `app/subgraphs/ticker/resolver.py` 过滤
- LLM 兜底误判 → 在 `app/nodes/route_rules.py` 加关键词 / 正则，或补 quote_marker

### render 类
- 期权 place_order 走互换渲染 → `render.py` 第3分支必须加 `product_type == "swap"` 条件
- 零命中误触发 → render 依赖 `tickers is not None` 语义，`make_initial_state` 不能设 `tickers=[]`

### state 传递类
- 多轮 tickers 丢失 → `make_initial_state` 里 `tickers` 字段不应设默认值（会覆盖 checkpoint）
- 多轮 place_params 丢失 → 同理，只在子图节点里设，不在 make_initial_state 里初始化

### 提示词类
- 意图误分类 → 改 `app/prompts/option/intent.md`（先建 _v2 副本，A/B 验证）
- 参数漏提取 → 改对应 extract_*.md

## pytest 守卫

修改 `app/` 下任何代码后必须先通过：

```bash
.venv/bin/python -m pytest tests/ -q --tb=line 2>&1 | tail -5
```

全部通过才能继续 eval。

## 迭代节奏

```
Round 1: --limit 20 --concurrency 10
  → 读 trace 归类，用 TDD 修 P0 根因
  → pytest 守卫
  → --ids 重跑受影响 case

Round 2: --limit 40 --concurrency 10
  → 修剩余 P0 + P1 根因

Round 3+: --concurrency 10（全量）
  → 直到全部通过或用户叫停
```

**不要手动逐条 debug**。批量归类 → trace 定位 → TDD 修根因 → 验证。

## 禁止事项

- **禁止先改代码再写测试**：必须先 RED 再 GREEN
- **禁止硬编码期望值**：不能在 `app/` 里针对特定 case 返回特定结果
- **禁止加模式开关**：不能在业务代码里加 `if TEST_MODE` 或环境变量切换逻辑路径
- **禁止改测试用例**：`tests/fixtures/categories/` 的 case 不能动
- 合法的修法只有两种：**修 bug**（代码逻辑错误）或**改提示词**（LLM 理解偏差）

## 关键文件

| 文件 | 用途 | 可改？ |
|---|---|---|
| `scripts/langfuse_eval.py` | 评估脚本（含 per-turn trace 输出）| ✅ 只改 trace/report 展示，不改评分逻辑 |
| `tests/fixtures/categories/` | fixture case 集（现役）| ❌ 不准改 case，可新增 |
| `app/state.py` `make_initial_state` | 每轮初始 state | ⚠️ 慎改：字段默认值影响多轮 checkpoint 传递 |
| `app/nodes/intent_route.py` | 产品路由（4层）| ✅ |
| `app/nodes/render.py` | 最终回复生成 | ✅ 改分支时必须带 product_type 条件 |
| `app/subgraphs/option/` | 期权子图（8个节点文件）| ✅ |
| `app/subgraphs/close/` | 平仓子图（7个节点文件）| ✅ |
| `app/prompts/option/intent.md` | 期权意图提示词 | ✅ 改前建 _v2 副本 |
| `app/prompts/option/extract_*.md` | 期权参数提取提示词 | ✅ 改前建 _v2 副本 |
| `app/prompts/option_close/*.md` | 平仓提示词 | ✅ 改前建 _v2 副本 |

**提示词改法**：
1. 复制 `xxx.md` → `xxx_v2.md`
2. 在节点代码中 `load_prompt("option", "intent_v2")` 加载新版
3. eval 对比验证后，确认优于原版再覆盖
