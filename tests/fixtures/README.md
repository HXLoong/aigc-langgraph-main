# 基准数据职责与恢复来源

## 1. 职责矩阵

下表中的历史基准文件已迁入 `old_typing/`；`unified_golden.jsonl` 仍在本目录。
测试、合并脚本和一致性检查均读取迁移后的路径。

| 文件 | 用途 | 编号 | 记录数 |
| --- | --- | --- | ---: |
| `golden.jsonl` | 当前业务回归主集，保留现有编号、输入和预期 | `swap-` / `opt-` / `opt_close-` / `query-` | 535 |
| `unified_golden.jsonl` | 历史合并集及当前主集的累计归档 | 产品前缀 + 数字；兼容历史 `close-` / `unknown-` | 921 |
| `option_golden.jsonl` | 历史期权业务 QA 数据 | `opt-` | 131 |
| `golden_business_seeds_2026-05.jsonl` | 历史业务种子快照 | `g` + 数字 | 287 |
| `golden_ticker_2026-05.jsonl` | 标的回归数据 | `tk` + 三位数字 | 34 |
| `golden_rule_anchors.jsonl` | ADR 0015 原始规则锚点 | `g001`–`g030` | 30 |

## 2. 恢复来源

三个缺失文件恢复自 Git 提交 `68e11d5519e4d0e90546f4c4436293e9187b793b`，即删除提交 `e4c132a` 的父提交。

- `option_golden.jsonl`：131 条，恢复后与 Git blob 逐字节一致。SHA-256：`9b02c3f787c9c84a52429ded805098bc9bbe031dfef5f95c3f1ba4950715212a`。
- `golden_business_seeds_2026-05.jsonl`：287 条，恢复后与 Git blob 逐字节一致。SHA-256：`a178829cd8047b12ee285f49366cb9d5d11d7116cf04c27533eacc4df8f4c837`。
- `unified_golden.jsonl`：先恢复原始 325 条，再通过同步脚本追加数据；原始 325 条的编号和内容保持不变。
- `golden_rule_anchors.jsonl`：从同一提交的 `golden.jsonl` 原样抽取 `g001`–`g030`，保留输入、预期和编号。

当前主集已由历史的 `g` 编号、单轮平铺结构迁移为产品编号和 `conversation` 结构。恢复独立锚点文件，避免为了满足旧检查而覆盖当前主集或改写其编号。快照用于历史追溯，不代表其中所有旧意图仍适用于当前业务契约。

## 3. 现役加载器：`harness/golden.py`（ADR 0024 D6）

`harness.golden.load_golden()` 是唯一现役加载器（`python -m harness run` 与
`scripts/langfuse/langfuse_eval.py --local` 共用），默认发现 `categories/*.jsonl` + 本目录
`unified_golden.jsonl`，共 1310 条（多轮 260 条），三种方言归一化为同一 `GoldenCase`：

| 方言 | 文件 | 形状 | case 级 `expected` 落点 |
| --- | --- | --- | --- |
| A | `categories/*.jsonl` | `name/caseNo + send_text + sub_scenes[]`，每轮可带独立断言 | 首轮 |
| B | `unified_golden.jsonl` | `id + conversation[{raw_content, quote_desc}]` + `expected{product_type, intent, output}` | 单轮：首轮；多轮：`any_turn`（任一已执行轮同时命中 product_type + intent 即通过，因为 B 的 expected 描述的是焦点轮，可能是末轮或中间轮） |
| raw | 标的回归集 | `id + raw_content` 单轮 | 首轮 |

B 方言约定：后续轮 `quote_desc` 非空 → 引用上一轮实际回复；首轮的 `quote_desc`（198 条上下文
依赖 case）无回复可引，只保留在 `TurnSpec.quote_desc` 供概览与人工判读。某轮 `raw_content`
为空（当前 48 条，用户文本被写进了 `quote_desc`）的 case 会被标 `skip_reason`，加载计数照常但
runner / eval 跳过并打印数量；这类记录与 9 条 `product_type=query`（运行时无此取值）都在
`scripts/check_fixture_consistency.py --verbose` 的 WARNING 里列出，归 Issue #113 业务方 review。

一个文件只放一种方言：`categories/` 出现 `conversation` / `raw_content`、或 `unified_golden.jsonl`
出现 `send_text` / `sub_scenes` 都是 lint 错误；id 跨两份文件唯一。

harness 的判定口径：`PASS` / `FAIL` / `REJECTED`（后端业务拒绝且无其它 diff，单独成桶，不计入 PASS 率）；
早停（节点错误 / 业务拒绝 / 技术错误）后未执行的轮次逐轮记 `runtime` 失败，多轮 case 不会因早停静默通过。
`--backend dry-run` 要求服务端 `/health` 报告 `backend_mode=dry-run`（`DRY_RUN_BACKEND=true`），否则拒绝启动；
反之 `--backend real|mock` 打在 dry-run 服务端也会被拦，避免拿假结果当回归基线。

`scripts/ai_test_langgraph/` 是早期工作台，仍能读三种记录，但已不是 gate（ADR 0024 D6 标
deprecated），新增校验只进 `harness/`。

## 4. 一致性要求

- 所有文件必须存在、非空，编号唯一且符合各自命名约定。
- `unified_golden.jsonl` 的首轮输入集合必须覆盖当前 `golden.jsonl` 和规则锚点集。
- 规则锚点 `g001`–`g030` 必须全部存在。
- 合并脚本保留已有归档，只追加内容变化的记录；当前多轮消息及预期完整保留，不按首轮输入去重。
- 追加记录用 `source_fixture` 和 `source_case_id` 记录来源；分配归档编号以避免与历史记录冲突。重复执行同步不产生新记录。

## 5. 更新与检查

```bash
python scripts/check_fixture_consistency.py --verbose   # A + B 两份现役文件；WARNING 为业务方待修数据
python -m harness run --data tests/fixtures/unified_golden.jsonl --limit 5   # 只跑 B 方言
```

新增或修改业务回归记录时，按文件方言写入，再跑一致性检查（历史 `merge_golden.py` 已不存在，不再有"同步"步骤）。历史 QA 和业务种子快照保持可追溯，不用于覆盖当前业务预期。

## 6. 全新交易对手节点回归集

`golden_swap_fresh_counterparty.jsonl` 保存 6 条工程回归样例，覆盖完整名称／简称、
单笔补全、多笔补全及已有相同名称的订单。它由
`tests/subgraphs/swap/test_fresh_counterparty.py` 直接读取，运行真实节点及聚合校验。

`initial_counterparty_names` 表示进入节点前各笔订单的对手，`llm_response` 是模拟的结构化
模型响应，`expected.place_params` 是期望输出。测试通过既有 `fresh_state()` 提供唯一候选
“聚鸣价值精选”，并同时验证其余订单字段和输入 State 不变。

这组数据验证固定模型响应后的节点行为，不计入真实 LLM 准确率，也不代表真实后端验收。

## 7. 意图集：`intent/<product>.jsonl`

与 `categories/` 业务集分离（`docs/langfuse/workflow-guide.md` §8）。只评一级路由 `product_type`
与子图 `intent`，只依赖 LLM，配 `mock_api` 运行；不写任何 `response_*` 卡片断言。

- A 方言子集：`caseNo`（`intent-` 前缀）+ `category=intent/<product>` + `type=positive|negative`
  + `send_text/at_bot/quote_previous` + 逐轮 `expected.{product_type, intent}`；多轮用 `sub_scenes[]`
- `expected.intent` 取各子图 `models.py` 的枚举；`product_type=unknown` 的反案例不标 intent
- id 与 `categories/` / `unified_golden.jsonl` 共用唯一性约束（`scripts/check_fixture_consistency.py`）
- `harness.golden.discover_fixtures()` 默认**不**纳入该目录；显式 `load_golden(Path("tests/fixtures/intent"))`
  或 `langfuse_eval.py --local tests/fixtures/intent`
- 来源：`scripts/derive_intent_fixtures.py` 从业务集派生草稿，业务方补齐 intent 后 `--only-labeled` 写入
- 运行环境：只依赖 LLM 网关，后端由仓库内 `mock_api/` 顶替；GitHub Actions `intent-eval` 自动 / 手动跑，
  本地 `langfuse_eval.py --local tests/fixtures/intent --fail-under 0.95`。`categories/` 业务集依赖 Java 后端，只在开发环境跑
- 标的识别子集 `intent/swap_instrument.jsonl`（375 条，来自三份 `swap*.jsonl`）：`expected.instruments[]` 断言 LLM 提取的
  标的原文任一候选与交易品种候选，评估器 `det_instrument_match_pass`；见 `intent/README.md`
