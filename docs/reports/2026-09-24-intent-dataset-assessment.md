# 期权 / 互换意图识别数据集评估（2026-09-24）

> 目标：意图识别（一级 `product_type` + 子图 `intent`）只调大模型即可测试，不对接 Java / GOATS 后端与业务 API。
> 范围：`tests/fixtures/intent/`（意图集）、`tests/fixtures/categories/`（业务集，意图集派生来源）、
> `tests/fixtures/unified_golden.jsonl`（B 方言，921 条）、`scripts/langfuse/langfuse_eval.py --suite intent` 执行链路。
> 本次未调用真实 LLM（环境无模型网关凭据），结论基于数据统计、代码走读与离线 PoC。

## 一、结论

1. **链路层面可行**：意图识别路径 `ingest → entry_route → pre_route → intent_route → {swap|option|close}_intent`
   全部是“规则 + LLM”，没有后端调用。离线 PoC（假 LLM + 封死 httpx）跑 40 条 unified 单轮用例：
   40/40 产出意图，**后端调用 0 次**，LLM 调用 34 次（其余 6 条走确定性规则）。
2. **现行 intent 套件并没有做到“只调大模型”**：`langfuse_eval.py` 跑的是整张主图，意图之后还会执行参数抽取
   LLM、后端下单/查询、render、persist，所以 CI 必须起 `mock_api` 顶替 Java + GOATS。多轮用例第 2 轮起的
   `quote_content` 取自上一轮机器人回复，而回复由 mock 后端生成，**后续轮的意图标签实际依赖 mock 的保真度**。
3. **数据集覆盖严重不足**：期权意图集只有 **1 条**，互换意图集 375 条全部是 `place_order_request`（标的抽取子集），
   没有反案例，也没有跨产品混淆案例。3 个子图共 22 个意图枚举，意图集只覆盖到 7 个。
4. **现成可用的标注资产大多没用上**：`unified_golden.jsonl` 有 896 条标签合法（符合当前枚举），覆盖 22 个意图中的 21 个，
   但其中 311 条用例（480 轮）的引用内容是占位描述（如“用户引用上一条机器人消息”），多轮用例也只在最后一轮打了标签，不能直接搬进意图集。

## 二、现状盘点

| 数据源 | 用例 / 轮次 | 意图标签 | 能否只调 LLM |
|---|---|---|---|
| `intent/option.jsonl` | 1 / 1 | `new_inquiry` ×1 | 可（单轮） |
| `intent/option_close.jsonl` | 5 / 18 | request 10、query 3、confirm 3、cancel_request 1、cancel_confirm 1 | 首轮可；第 2 轮起的引用依赖后端回复 |
| `intent/swap_instrument.jsonl` | 375 / 375 | 全部 `place_order_request`（另评标的原文抽取） | 可（单轮） |
| `intent/swap.jsonl` | **不存在** | — | — |
| `categories/*.jsonl` | 391 条 | 仅 8 条有 intent 标签（`derive_intent_fixtures.py --dry-run`：383/391 待标注） | 否，靠卡片文本断言，依赖 Java |
| `unified_golden.jsonl` | 921 条（单轮 670，多轮 251） | 仅最后一轮有标签；896 条合法，25 条使用已退役枚举 | 部分可，见第四节 |
| `nodes/`（节点级 fixture） | 0 | — | `harness node-run` 已具备，但目录为空 |

`python scripts/check_fixture_consistency.py`：PASS（格式合法，但覆盖面不在它的检查范围内）。

## 三、意图覆盖矩阵

枚举以 `app/subgraphs/*/models.py` 为准。

| 产品 | 意图 | intent/ 轮次 | unified 可用条数 |
|---|---|---:|---:|
| swap | place_order_request | 375 | 265 |
| swap | cancel_order_request | 0 | 13 |
| swap | confirm_order | 0 | 18 |
| swap | confirm_cancel_order | 0 | 6 |
| swap | confirm_modify_order | 0 | 17 |
| swap | query_order_status | 0 | 6 |
| swap | unknown_intent | 0 | 13 |
| option | new_inquiry | 1 | 199 |
| option | place_order_from_quote | 0 | 111 |
| option | confirm_order | 0 | 17 |
| option | cancel_order_request | 0 | 1 |
| option | request_cancel_order | 0 | 26 |
| option | confirm_cancel_order | 0 | 4 |
| option | query_order_status | 0 | 1 |
| option | unknown_intent | 0 | 2 |
| option_close | close_order_query | 3 | 20 |
| option_close | close_order_order_query | 0 | 2 |
| option_close | close_order_request | 10 | 131 |
| option_close | close_order_confirm | 3 | 6 |
| option_close | close_order_cancel_request | 1 | 22 |
| option_close | close_order_cancel_confirm | 1 | 6 |
| option_close | unknown_intent | 0 | 0 |
| unknown | unknown_intent（一级路由反案例） | 0 | 10 |

尾部意图样本过少：option `cancel_order_request` / `query_order_status` / `unknown_intent`、close `order_query` 均不超过 2 条，
达不到每个意图 ≥ 2 条的门槛（`.claude/rules/testing.md`），更谈不上统计意义。

## 四、unified_golden 的质量问题（迁入前必须处理）

| 问题 | 数量 | 处理 |
|---|---:|---|
| 已退役枚举：`swap/request_cancel_order` 6、`swap/request_modify_order` 6、`option/request_modify_order` 4、`product_type=query` 9 | 25 | 业务方按现行枚举重标（swap 撤单请求 → `cancel_order_request`；改单 → `place_order_request`；`query` → 按产品归属） |
| 引用是占位描述而非真实卡片文本（“用户引用上一条机器人消息”“引用报价结果”“引用持仓列表”等） | 311 条用例 / 480 轮 | 用真实卡片样本（或 `mock_api` 卡片模板一次性渲染后冻结）替换为静态引用文本 |
| 空 `raw_content`（用户文本写进了 quote_desc，Issue #113） | 82 条 turn | 修正或剔除 |
| 多轮用例只标最后一轮 | 251 条 | 补齐逐轮标签，或把最后一轮拆成“冻结上下文 + 单轮”用例 |
| 同一输入被标成不同意图 | 2 组 | 人工裁决 |
| 输入完全重复 | 921 条仅 799 组唯一 | 迁入时去重 |
| 图片 / Excel 类用例 | 7 | 意图集不收（没有文件数据） |

另外：当前 runner 只把 `quote_desc` 当作注释（`harness/golden.py`：“首轮不可回放”），不会注入为 `quote_content`；
即便 unified 里有 120 条真实引用文本，也没有传给模型。

## 五、根因：执行模型与目标不匹配

意图节点读取的上下文只有 `raw_text`、`quote_content`、`history_messages`、`swap_counterparties / option_counterparties`
（由 `pre_route` 从入参解析，不查后端），以及多轮粘性用到的上一轮 `product_type`。这些都可以在数据里**静态冻结**。
现行做法却让 quote / history 由整图（含后端）现场生成，导致：

- 需要 mock_api 才能跑，也就是说测的是“LLM + mock 保真度”，不是纯 LLM；
- 每轮额外执行抽取 LLM 与后端节点，成本和耗时成倍增加；下游节点的 error 可能污染观测；
- 多轮标签无法稳定复现（mock 卡片文本和真实 Java 卡片不一致时，引用内容就变了）。

## 六、建议路线

**P0：意图级 runner（真正只调 LLM）** —— 已实现：`harness/intent_runner.py` + fixture 冻结上下文（`quote_content` / `history` / `prev_product_type`）；与 main 同期引入的回放用例（`quote_previous` / `{{previous_*}}`，绑定真实持仓）并存——冻结用例只调 LLM，回放用例仍走主图 + mock_api，逐步冻结后再删 mock_api；`tests/harness/test_intent_runner.py` 守护冻结用例零后端调用。
- `langfuse_eval.py --suite intent` 改为只跑意图子链：`ingest → entry_route → pre_route → intent_route → <product>_intent`
  （可用 LangGraph 子图，或复用 `app/node_execution/catalog.py` 已登记的 `intent_route / swap_intent / option_intent / close_intent`），
  不再构建整张主图、不再启动 mock_api；CI 的 `mock_api` 步骤与 `OTC_API_*` / `GOATS_*` 假环境变量随之删除。
- 每轮上下文静态化：新增 `quote_content`（冻结的引用文本）、`history`（冻结的历史消息）、`prev_product_type`（粘性），
  runner 直接注入 state，不再用上一轮回复拼接。`check_fixture_consistency.py` 同步校验。
- 本次 PoC 脚本（假 LLM + 封死网络，40/40 后端 0 调用）可直接改造为该 runner 的离线单测，守护“意图链路零后端”这一不变量。

**P1：补齐数据（先用现成资产）**
- 从 unified 直接迁入 479 条单轮用例（标签合法、原文非空、引用为空或为真实文本、非图片类，去重后计数）；占位引用和多轮用例补齐文本与逐轮标签后再迁入。
- 按意图建最低配额：每个意图正例 ≥ 10、易混反例 ≥ 5（如 option `cancel_order_request` vs `request_cancel_order`、
  swap `confirm_order` vs `confirm_modify_order`、close `close_order_query` vs `close_order_order_query`）；
  一级路由补跨产品混淆与 `unknown` 反例。
- 新建 `intent/swap.jsonl` 承载互换非下单意图；`swap_instrument.jsonl` 保持为标的抽取子集，统计时单独列出，避免 375 条同一意图稀释整体通过率。

**P2：评测口径**
- 报告按“产品 × 意图”输出混淆矩阵与逐意图召回率，不只看整体通过率（现在 381 条用例中 375 条是 swap 下单，整体 95% 门槛基本等于下单单项的门槛）。
- 同时记录决策来源（`rule` / `llm` / `sticky` / `deterministic`），区分“规则命中”和“模型判断”，
  防止规则层覆盖掩盖提示词退化。

## 附：复现命令

```bash
python scripts/derive_intent_fixtures.py --dry-run        # 383/391 待标注
python scripts/check_fixture_consistency.py               # PASS
# 覆盖统计 / unified 质量统计：见本文第三、四节，均由 fixture 直接计数得出
```
