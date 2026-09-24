# 意图集（intent suite）

只评 `product_type`（一级路由）与 `intent`（子图意图），不连 Java / GOATS；
业务操作（询价 / 下单 / 平仓的卡片与后端联动）在 `../categories/` 业务集里评。

## 两种执行模式（`harness/intent_context.py` 判定）

| 模式 | 判定 | 执行 | 依赖 |
|---|---|---|---|
| 冻结 `intent_chain` | 每轮上下文都写在 fixture（首轮以外 `quote_previous: false` 或带 `quote_content`） | `harness/intent_runner.py` 只跑 `ingest → pre_route → intent_route → {swap\|option\|close}_intent` | 只有 LLM |
| 主图 `main_graph` | 回放：任一子轮引用上一轮真实回复（`quote_previous` 非 false 且无 `quote_content`）或正文含 `{{previous_*}}`；或拒绝验收（`expected.rejection`，需检查用户可见的拒绝回复与未提交） | 主图，上一轮回复作引用 | LLM + `mock_api` |

目标是逐步把回放用例冻结；冻结后该用例即不再需要 `mock_api`（拒绝验收用例始终走主图）。报告里每条用例的 `mode` 字段标明走了哪条路。

### 冻结上下文

冻结用例每轮**独立执行**，意图节点读取的上下文全部写死在该轮 fixture 里，不依赖上一轮机器人回复
（那是后端生成的，回放它就等于测“LLM + 后端/mock 保真度”）：

| 字段 | 注入到 | 说明 |
|---|---|---|
| `quote_content` | `state.quote_content` | 用户引用的机器人消息原文（按 Java 卡片格式冻结） |
| `history` | `state.history_messages` | `[{role: user\|assistant\|system, content}]`，按生产 record_history 顺序 |
| `prev_product_type` | `state.product_type` | 上一轮产品，供 `intent_route` 第 3 层多轮粘性 |

- 同一用例不能混用冻结字段与回放（回放模式下冻结字段会被忽略，lint 报错）；要冻结就冻结每一轮
- 交易对手列表取仓库内 mock 授权上下文（`mock_api/backend/fixtures.py`，与回放模式在 CI 拉到的同源），进程内读取
- 不早停：前一轮识别错不影响后一轮输入，每轮按自己的期望独立计分
- `option_close.jsonl` 的 case-030 / 032 / 033 已冻结；冻结引用按 Java 真实卡片格式（持仓列表 / 平仓详情 / 参数需要完善 / 只能全部平仓 /
  已收到下单、撤单请求，格式样本见 `../unified_golden.jsonl` opt-092、opt-093 与 close 子图测试）编写，
  合约与金额取值和 `../categories/golden_option_close_case.jsonl` 的卡片断言一致；标的信息为示意值

```jsonl
{"caseNo":"intent-swap-001","name":"互换市价下单","category":"intent/swap","type":"positive","source":"derived:swap_prod_data#case_1",
 "send_text":"市价买一百万京东","at_bot":true,"quote_previous":false,
 "expected":{"product_type":"swap","intent":"place_order_request"},
 "sub_scenes":[{"send_text":"确认下单","at_bot":false,"quote_previous":true,"expected":{"product_type":"swap","intent":"confirm_order"}}]}
```

## 标的识别子集：`swap_instrument.jsonl`

从 `../categories/swap*.jsonl` 派生（`scripts/derive_instrument_fixtures.py`，抽取结果已逐条人工复核）。
LangGraph 只把用户原文里的标的表达逐字送给后端（`docs/architecture/backend-instrument-boundary.md`），所以期望值
不是证券代码，而是 **LLM 应提取的原文表达任一候选** + **市场限定词对应的交易品种候选**：

```jsonl
{"caseNo":"intent-swap-instrument-…","category":"intent/swap","type":"positive","source":"derived:swap_test_fuzzy_target_recog_data#…",
 "send_text":"港股市价买一百万京东 11125测试短名（张天琪专用）","at_bot":true,"quote_previous":false,
 "expected":{"product_type":"swap","intent":"place_order_request",
             "instruments":[{"expression":["京东"],"transaction_type":["HK_STOCK"]}]},
 "sub_scenes":[],"reference":{"backend_codes":["9618.HK","89618.HK"]}}
```

- `instruments[i].expression`：任一候选命中即可（"金力永磁300748.sz" / "300748.sz" / "金力永磁"）；按订单无序匹配，
  订单数以业务卡片 `标的代码：` 行数为准（拆单同标的重复出现）
- `instruments[i].transaction_type`：只在原文有 港股 / A股 / 美股 / 深港通 / 沪港通 时断言；只说“港股”严格要求 HK_STOCK；明确“沪港通”/“深港通”分别要求 SH_HK_CONNECT / SZ_HK_CONNECT（2026-09-23 用户确认）
- 名称与代码混写继续接受完整表达、代码或名称任一候选（2026-09-23 用户确认）。
- `reference.backend_codes`：原业务卡片 / 候选列表里的后端码，只供人工核对，不参与评分
- 评估器：`det_instrument_match_pass`（`harness/evaluators/instrument_match.py`）+ `det_intent_match_pass`

规则（`scripts/check_fixture_consistency.py` 强制）：

- 每轮必须有 `expected.product_type`（`swap | option | option_close | unknown`）和 `expected.intent`
  （各子图 `models.py` 枚举）；`product_type=unknown` 的反案例不标 intent
- 禁止 `response_contains` / `response_contains_any` / `response_not_contains`
- `caseNo` 以 `intent-` 开头，`category` 为 `intent/<product>`，`type` 为 `positive | negative`
- `expected.instruments` 只允许 `product_type=swap`；`expression` 非空 str/list，`transaction_type` 取 `SwapTransactionType`
- 文件按产品命名：`swap.jsonl` / `option.jsonl` / `option_close.jsonl`；子集加后缀：`swap_instrument.jsonl`
- 冻结上下文：不得与回放混用；`quote_content` 非空字符串；`history[i]` 为 `{role, content}` 且
  role ∈ user/assistant/system、content 非空；`prev_product_type` ∈ swap/option/option_close

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

- **冻结用例只依赖 LLM 网关**：`tests/harness/test_intent_runner.py` 用假 LLM + 封死网络跑完全部冻结用例，
  守护“零后端调用”；回放与拒绝验收用例仍需 `mock_api`（`uvicorn mock_api.server:app --port 8099`，`OTC_API_BASE_URL` 指向它）
- 标的子集（`expected.instruments`）额外跑 swap 参数抽取子图（候选抽取 → 归一化，纯 LLM + Code），提交节点不在图里
- **CI**：`.github/workflows/intent-eval.yml`——**仅手动触发**（Actions → intent-eval → Run workflow），不随 PR 自动跑，
  改提示词 / 路由意图节点 / 评估器 / 本目录后按需手动跑；评分在本地算（`intent_match` / `instrument_match`），
  `--fail-under 0.95` 拦截；仓库未配 `QWEN_API_BASE` / `QWEN_API_KEY` secrets 时直接失败
- **本地**：只跑冻结用例时配好 LLM 网关即可；含回放用例时先起 `mock_api`，
  `python scripts/langfuse/langfuse_eval.py --local tests/fixtures/intent --fail-under 0.95 --report .harness-runs/intent-eval.json`
- 依赖 Java 后端的业务集在 `../categories/`，只在开发 / staging 环境跑（`docs/testing/README.md` §一a）
