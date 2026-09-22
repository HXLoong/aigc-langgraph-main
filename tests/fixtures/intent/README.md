# 意图集（intent suite）

只评 `product_type`（一级路由）与 `intent`（子图意图），只调 LLM，配 `mock_api` 运行；
业务操作（询价 / 下单 / 平仓的卡片与后端联动）在 `../categories/` 业务集里评。

```jsonl
{"caseNo":"intent-swap-001","name":"互换市价下单","category":"intent/swap","type":"positive","source":"derived:swap_prod_data#case_1",
 "send_text":"市价买一百万京东","at_bot":true,"quote_previous":false,
 "expected":{"product_type":"swap","intent":"place_order_request"},
 "sub_scenes":[{"send_text":"确认下单","at_bot":false,"quote_previous":true,"expected":{"product_type":"swap","intent":"confirm_order"}}]}
```

## 标的识别子集：`swap_instrument.jsonl`

从 `../categories/swap*.jsonl` 派生（`scripts/derive_instrument_fixtures.py`，抽取结果已逐条人工复核）。
LangGraph 只把用户原文里的标的表达逐字送给后端（`docs/backend-instrument-boundary.md`），所以期望值
不是证券代码，而是 **LLM 应提取的原文表达任一候选** + **市场限定词对应的交易品种候选**：

```jsonl
{"caseNo":"intent-swap-instrument-…","category":"intent/swap","type":"positive","source":"derived:swap_test_fuzzy_target_recog_data#…",
 "send_text":"港股市价买一百万京东 11125测试短名（张天琪专用）","at_bot":true,"quote_previous":false,
 "expected":{"product_type":"swap","intent":"place_order_request",
             "instruments":[{"expression":["京东"],"transaction_type":["HK_STOCK","SH_HK_CONNECT","SZ_HK_CONNECT"]}]},
 "sub_scenes":[],"reference":{"backend_codes":["9618.HK","89618.HK"]}}
```

- `instruments[i].expression`：任一候选命中即可（"金力永磁300748.sz" / "300748.sz" / "金力永磁"）；按订单无序匹配，
  订单数以业务卡片 `标的代码：` 行数为准（拆单同标的重复出现）
- `instruments[i].transaction_type`：只在原文有 港股 / A股 / 美股 / 深港通 / 沪港通 时断言；港股口语允许三种港股通取值
- `reference.backend_codes`：原业务卡片 / 候选列表里的后端码，只供人工核对，不参与评分
- 评估器：`det_instrument_match_pass`（`harness/evaluators/instrument_match.py`）+ `det_intent_match_pass`

规则（`scripts/check_fixture_consistency.py` 强制）：

- 每轮必须有 `expected.product_type`（`swap | option | option_close | unknown`）和 `expected.intent`
  （各子图 `models.py` 枚举）；`product_type=unknown` 的反案例不标 intent
- 禁止 `response_contains` / `response_contains_any` / `response_not_contains`
- `caseNo` 以 `intent-` 开头，`category` 为 `intent/<product>`，`type` 为 `positive | negative`
- `expected.instruments` 只允许 `product_type=swap`；`expression` 非空 str/list，`transaction_type` 取 `SwapTransactionType`
- 文件按产品命名：`swap.jsonl` / `option.jsonl` / `option_close.jsonl`；子集加后缀：`swap_instrument.jsonl`

生成与运行：

```bash
python scripts/derive_intent_fixtures.py --dry-run                      # 统计待标注
python scripts/derive_instrument_fixtures.py --dry-run --ignore-token "<测试对手名>"   # 标的识别抽取复核表
python scripts/derive_instrument_fixtures.py --only-reviewed --ignore-token "<测试对手名>" --out tests/fixtures/intent/swap_instrument.jsonl
python scripts/derive_intent_fixtures.py --source tmp/intent_drafts --only-labeled --out tests/fixtures/intent
python scripts/check_fixture_consistency.py --verbose
python scripts/langfuse/langfuse_eval.py --local tests/fixtures/intent --concurrency 3   # 自动 suite=intent，不跑 Judge
```

Langfuse 侧：Dataset `intent-<product>`，评估器 `det_intent_match_pass`（`harness/evaluators/intent_match.py`），
详见 `docs/langfuse/workflow-guide.md` §8。

## 在哪跑

- **不依赖 Java / GOATS**：后端由仓库内 `mock_api/` 顶替，唯一外部依赖是 LLM 网关
- **CI**：`.github/workflows/intent-eval.yml`——PR 触碰提示词 / 路由意图节点 / 评估器 / 本目录时自动跑，
  也可在 Actions 手动触发；评分在本地算（`intent_match` / `instrument_match`），`--fail-under 0.95` 拦截；
  仓库未配 `QWEN_API_BASE` / `QWEN_API_KEY` secrets 时 PR 上只做 lint、评估跳过并告警（不算通过）
- **本地**：起 `uvicorn mock_api.server:app --port 8099`，`OTC_API_BASE_URL` / `GOATS_BASE_URL` 指向它，
  `python scripts/langfuse/langfuse_eval.py --local tests/fixtures/intent --fail-under 0.95 --report .harness-runs/intent-eval.json`
- 依赖 Java 后端的业务集在 `../categories/`，只在开发 / staging 环境跑（`docs/testing/README.md` §一a）
