# 意图集（intent suite）

只评 `product_type`（一级路由）与 `intent`（子图意图），只调 LLM，配 `mock_api` 运行；
业务操作（询价 / 下单 / 平仓的卡片与后端联动）在 `../categories/` 业务集里评。

```jsonl
{"caseNo":"intent-swap-001","name":"互换市价下单","category":"intent/swap","type":"positive","source":"derived:swap_prod_data#case_1",
 "send_text":"市价买一百万京东","at_bot":true,"quote_previous":false,
 "expected":{"product_type":"swap","intent":"place_order_request"},
 "sub_scenes":[{"send_text":"确认下单","at_bot":false,"quote_previous":true,"expected":{"product_type":"swap","intent":"confirm_order"}}]}
```

规则（`scripts/check_fixture_consistency.py` 强制）：

- 每轮必须有 `expected.product_type`（`swap | option | option_close | unknown`）和 `expected.intent`
  （各子图 `models.py` 枚举）；`product_type=unknown` 的反案例不标 intent
- 禁止 `response_contains` / `response_contains_any` / `response_not_contains`
- `caseNo` 以 `intent-` 开头，`category` 为 `intent/<product>`，`type` 为 `positive | negative`
- 文件按产品命名：`swap.jsonl` / `option.jsonl` / `option_close.jsonl`

生成与运行：

```bash
python scripts/derive_intent_fixtures.py --dry-run                      # 统计待标注
python scripts/derive_intent_fixtures.py --source tmp/intent_drafts --only-labeled --out tests/fixtures/intent
python scripts/check_fixture_consistency.py --verbose
python scripts/langfuse/langfuse_eval.py --local tests/fixtures/intent --concurrency 3   # 自动 suite=intent，不跑 Judge
```

Langfuse 侧：Dataset `intent-<product>`，评估器 `det_intent_match_pass`（`harness/evaluators/intent_match.py`），
详见 `docs/langfuse/workflow-guide.md` §8。
