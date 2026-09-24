# 测试数据集说明

## 1. 目录与职责

| 路径 | 用途 |
| --- | --- |
| `categories/*.jsonl` | 现役业务验收集（A 方言），统一验收与 `harness run` 默认只加载这里 |
| `intent/*.jsonl` | 意图集：只评一级路由与子图意图，只依赖 LLM + `mock_api`（见第 5 节） |
| `nodes/<product>/<node>.jsonl` | 节点级 fixture，供 `python -m harness node-run` 回归（ADR 0029） |
| `unified_golden.jsonl` | 历史参考集（B 方言），仅在显式选择时加载 |
| `golden_swap_fresh_counterparty.jsonl` | 全新交易对手节点的工程回归样例（见第 4 节） |
| `swap_confirmation_cases.json` | 互换确认路径的单元测试数据 |
| `local_backend/` | 本地合成身份种子（见 `docs/testing/local-backend-seed.md`） |

## 2. 加载器：`harness/golden.py`（ADR 0024 D6）

`harness.golden.load_golden()` 是唯一加载器（`python -m harness run` 与
`scripts/langfuse/langfuse_eval.py --local` 共用），默认只发现 `categories/*.jsonl`。
历史参考集 `unified_golden.jsonl` 保留，通过 `python -m harness run --include-unified` 追加，
或用 `--data` 显式选择。Python 调用对应 `load_golden(include_unified=True)`；与显式 paths
组合时追加 root 下的历史文件，同一路径不重复追加。三种方言仍归一化为同一 `GoldenCase`：

| 方言 | 文件 | 形状 | case 级 `expected` 落点 |
| --- | --- | --- | --- |
| A | `categories/*.jsonl` | `name/caseNo + send_text + sub_scenes[]`，每轮可带独立断言 | 首轮 |
| B | `unified_golden.jsonl` | `id + conversation[{raw_content, quote_desc}]` + `expected{product_type, intent, output}` | 单轮：首轮；多轮：`any_turn`（任一已执行轮同时命中 product_type + intent 即通过，因为 B 的 expected 描述的是焦点轮，可能是末轮或中间轮） |
| raw | 标的回归集 | `id + raw_content` 单轮 | 首轮 |

B 方言约定：后续轮 `quote_desc` 非空 → 引用上一轮实际回复；首轮的 `quote_desc`（198 条上下文
依赖 case）无回复可引，只保留在 `TurnSpec.quote_desc` 供概览与人工判读。某轮 `raw_content`
为空（当前 48 条，用户文本被写进了 `quote_desc`）的 case 会被标 `skip_reason`，加载计数照常但
runner / eval 跳过并打印数量；这类记录与 9 条 `product_type=query`（运行时无此取值）都在
`scripts/check_fixture_consistency.py --verbose` 的 WARNING 里列出，待业务方复核。

一个文件只放一种方言：`categories/` 出现 `conversation` / `raw_content`、或 `unified_golden.jsonl`
出现 `send_text` / `sub_scenes` 都是 lint 错误；id 跨两份文件唯一。

harness 的判定口径：`PASS` / `FAIL` / `REJECTED`（后端业务拒绝且无其它 diff，单独成桶，不计入 PASS 率）；
早停（节点错误 / 业务拒绝 / 技术错误）后未执行的轮次逐轮记 `runtime` 失败，多轮 case 不会因早停静默通过。
`--backend dry-run` 要求服务端 `/health` 报告 `backend_mode=dry-run`（`DRY_RUN_BACKEND=true`），否则拒绝启动；
反之 `--backend real|mock` 打在 dry-run 服务端也会被拦，避免拿假结果当回归基线。

## 3. 一致性要求与检查

- 编号跨文件唯一；一个文件只放一种方言；`$ref` 结构断言在执行前校验声明形状。
- 新增或修改业务回归记录时按文件方言写入，再跑一致性检查：

```bash
python scripts/check_fixture_consistency.py --verbose   # 现役 categories / intent + 历史 unified；WARNING 为业务方待修数据
python -m harness run --data tests/fixtures/unified_golden.jsonl --limit 5   # 只跑 B 方言
```

## 4. 全新交易对手节点回归集

`golden_swap_fresh_counterparty.jsonl` 保存 6 条工程回归样例，覆盖完整名称／简称、
单笔补全、多笔补全及已有相同名称的订单。它由
`tests/subgraphs/swap/test_fresh_counterparty.py` 直接读取，运行真实节点及聚合校验。

`initial_counterparty_names` 表示进入节点前各笔订单的对手，`llm_response` 是模拟的结构化
模型响应，`expected.place_params` 是期望输出。测试通过既有 `fresh_state()` 提供唯一候选
“聚鸣价值精选”，并同时验证其余订单字段和输入 State 不变。

这组数据验证固定模型响应后的节点行为，不计入真实 LLM 准确率，也不代表真实后端验收。

## 5. 意图集：`intent/<product>.jsonl`

与 `categories/` 业务集分离（`docs/langfuse/workflow-guide.md` §8）。只评一级路由 `product_type`
与子图 `intent`，不依赖 Java / GOATS：冻结用例只跑意图子链（`harness/intent_runner.py`），回放用例配 `mock_api`；不写任何 `response_*` 卡片断言。

- A 方言子集：`caseNo`（`intent-` 前缀）+ `category=intent/<product>` + `type=positive|negative`
  + `send_text/at_bot` + 逐轮 `expected.{product_type, intent}`；多轮用 `sub_scenes[]`；冻结用例每轮上下文写在
  `quote_content` / `history` / `prev_product_type`，回放用例用 `quote_previous`（两种模式见 `intent/README.md`）
- `expected.intent` 取各子图 `models.py` 的枚举；`product_type=unknown` 的反案例不标 intent
- id 与 `categories/` / `unified_golden.jsonl` 共用唯一性约束（`scripts/check_fixture_consistency.py`）
- `harness.golden.discover_fixtures()` 默认**不**纳入该目录；显式 `load_golden(Path("tests/fixtures/intent"))`
  或 `langfuse_eval.py --local tests/fixtures/intent`
- 来源：`scripts/derive_intent_fixtures.py` 从业务集派生草稿，业务方补齐 intent 后 `--only-labeled` 写入
- 运行环境：冻结用例只依赖 LLM 网关，回放用例由仓库内 `mock_api/` 顶替后端；GitHub Actions `intent-eval` 仅手动触发，
  本地 `langfuse_eval.py --local tests/fixtures/intent --fail-under 0.95`。`categories/` 业务集依赖 Java 后端，只在开发环境跑
- 标的识别子集 `intent/swap_instrument.jsonl`（375 条，来自三份 `swap*.jsonl`）：`expected.instruments[]` 断言 LLM 提取的
  标的原文任一候选与交易品种候选，评估器 `det_instrument_match_pass`；见 `intent/README.md`

## 6. Excel 导出

`python scripts/convert_jsonl_to_excel.py` 默认读取 `categories/` 直属 JSONL，每个文件一张表。
`--dry-run` 只校验和统计，`--output` 可指定工作簿位置。

## 7. 结构断言引用实际卡片

业务 `expected` 可用 `$ref` 绑定本轮实际引用，避免把运行时订单号写死：

```json
{"confirm":{"orderList":[{"orderId":{"$ref":"quote.order_id"}}]}}
```

- `quote.order_id`：引用中的唯一单号；多笔时显式加 `"position": 2`，表示卡片出现顺序的第二笔，不是显示序号值。
- `quote.order_ids`：引用中去重后的完整单号列表，适用于确认范围。
- `quote.counterparty`：加 `"option": "A"`，取引用中该选项的完整对手名；重复且同名可合并，异名视为歧义。
- `quote.holding_contract`：引用的唯一合约编号，或加 `position` 选择对应持仓条目。

解析只读取实际传入本轮的完整 quote，从“例如”或“示例”起的尾部均不参与绑定，不读取本轮模型输出或未引用的历史。
多轮 B 方言的 case 级 `any_turn` 也逐轮使用该轮实际 quote，不跨轮拼接引用。
缺失、越界、歧义和非法声明均记为失败；fixture lint 在执行前验证声明形状。
HTTP harness / local_eval 支持这些结构断言；Langfuse Judge 评分不替代该确定性验收。
