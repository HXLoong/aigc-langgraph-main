# 互换拒绝集与业务集出卡期望冲突 · 裁决输入件

日期：2026-09-30 · 状态：**已裁决（2026-09-30，选项 b：以 biz 出卡为准）**

范围：`tests/datasets/intent/swap_rejection.jsonl`（27 条，已按裁决删除）与它们 `source` 指向的 `tests/datasets/biz/` 同号用例。

## 裁决结论与执行（2026-09-30）

业务方裁决：**选项 b · 以 biz 出卡为准**。规则 A（`暫買入` / `已買` / `暫沽` 等繁体与省略方向词）与规则 B（`-34250` 非正数量）都按**正常下单**处理，不再存在"方向歧义 / 非正数量拒绝"契约。

支持该裁决的补充证据：`harness/evaluators/rejection_match.js` 映射的节点 `swap_extract_candidates` / `swap_normalize` 与错误类型 `AmbiguousActionError` / `NonPositiveQuantityError` 在 `app/` 中已不存在（全仓只有该 evaluator、其测试与 skills 示例提及），拒绝集**结构上不可能通过**。

已执行改动：
- 删除 `tests/datasets/intent/swap_rejection.jsonl`（27 条）→ 意图集 391 条变 364 条。
- 退役拒绝语义基础设施：`harness/evaluators/rejection_match.js`、`scripts/langfuse/definitions/evaluators.json` 的 `rejection-match` 定义、`harness/evaluators/evaluators.test.js` 拒绝块、`scripts/langfuse/upload_golden_to_langfuse.py` 绑定分支、`scripts/langfuse/langfuse_eval.py` 的 `has_rejections`、`harness/http_evaluation.py` 的 `expected_rejection` 与冻结例外、`scripts/check_dataset_consistency.py` 的冲突规则与 `swap_rejection.jsonl` 豁免、`docs/langfuse/workflow-guide.md` 的评分器说明。
- 未受影响：冻结/回放判定（`harness/intent_context.py`）、派生 `source` 存在性校验、`intent/swap_instrument.jsonl` 中同批语料的 positive 标签（它们现在与 biz 出卡期望一致）。

基线重定口径：
- 变更前基线：意图集 391 条、业务集 391 条；本轮未在真后端 / 真模型环境重跑，因此不改写任何历史 PASS 记录。
- 变更后基线：意图集 364 条。统一验收时用同一命令重跑并留档：意图集 `python scripts/langfuse/langfuse_eval.py --local tests/datasets/intent --concurrency 3`；业务集 `python scripts/local_eval.py --data tests/datasets/biz`。
- 平台侧：Langfuse 中 27 个旧 Item 会悬空（Item ID 由 `caseNo` 生成，见 `scripts/langfuse/upload_golden_to_langfuse.py`）；下次上传记一次数据集版本，不回删历史 Score。
- 观察项：真后端首次回归重点看这 27 条同号业务用例——它们现在是唯一覆盖这批语料的用例。

## 一、冲突事实（裁决前记录）

`intent/swap_rejection.jsonl` 的 27 条均为 `type: negative`，声明 `expected.rejection`：

| 规则 | 条数 | 声明 | 代表用例（文件:行） |
|---|---|---|---|
| A · `ambiguous_action` | 26 | 方向/动作歧义 → 不下单 | `swap_rejection.jsonl:2`（`3939hk 暫買入 38000 股 @ 7.4747`） |
| B · `non_positive_quantity` | 1 | 数量非正 → 不下单 | `swap_rejection.jsonl:1`（`601899 紫金矿业 卖出 -34250 … 一半持仓`） |

同号 biz 用例的期望是**正常出卡**：

| 意图集用例 | source | biz 期望 |
|---|---|---|
| `swap_rejection.jsonl:1` | `derived:swap_prod_acceptance_data#…accept_order_case_77` | `biz/swap_prod_acceptance.jsonl:76` 出卡「委托数量：244300股」+ 按比例取整温馨提示 |
| `swap_rejection.jsonl:2` | `derived:swap_prod_data#…swap_order_case_13` | `biz/swap_prod.jsonl:13` 出卡「价格类型：限价委托 / 限定价格：7.4747」 |

两组断言由不同执行路径评估，且都被实际使用：

- 拒绝集：`harness/evaluators/rejection_match.js` 与 `harness/http_evaluation.py` 会读 `expected.rejection`；Langfuse 侧按 `rejection-match` 评分器绑定（`docs/langfuse/workflow-guide.md` §8）。
- biz 集：`harness/differ.py::check_text_assertions` 校验卡片文本；`scripts/local_eval.py` 走真后端。

因此**两边不可能同时 PASS**，且 `scripts/check_dataset_consistency.py` 原实现不含跨文件语义检查，从未报出。

## 二、两侧证据强度（供裁决参考）

- 意图集侧：`review.basis` 自述「既有方向歧义/非正数量拒绝契约；用户授权自主方案、默认评审通过」（`swap_rejection.jsonl` 每条 `review` 字段），**不是业务方逐条确认**。
- biz 集侧：`swap_prod_data` / `swap_prod_acceptance_data` 是生产消息快照（`send_text` 含测试对手名），期望值是当时后端的真实出卡。
- 规律观察：26 条规则 A 的语料集中在繁体/省略方向词（`暫買入` / `暫買` / `已買` / `已沽` / `暫沽` / `暫入`）与「已改」「暫沒成交」前缀；`intent/swap_instrument.jsonl` 中同批语料被标为 `positive`（`place_order_request`），与该拒绝集自相矛盾。

## 三、业务方问题与答复（2026-09-30）

1. 规则 A：按**正常下单**处理（选项 b）。
2. 规则 B：按**正常下单**处理，出卡数值以 biz 期望为准。
3. 判定归属：不新增模型侧拒绝对照；业务参数由 Java 校验（ADR 0027）。

## 四、裁决后的改动面（按选项）

选项 (a) **拒绝契约为准**：
- 改 `biz/swap_prod.jsonl` 26 行 + `biz/swap_prod_acceptance.jsonl:76` 的出卡期望为拒绝期望；
- `intent/swap_rejection.jsonl` 的 `review.status` 升级为「业务确认（负责人 + 日期）」；
- `intent/swap_instrument.jsonl` 中同号用例（若确有 positive 版本）同步删除或改标签。

选项 (b) **biz 出卡为准**（已执行，见文首「裁决结论与执行」）：
- 收缩或删除 `intent/swap_rejection.jsonl`；
- 同步：`harness/evaluators/rejection_match.js`、`docs/langfuse/workflow-guide.md` §8 的评分器绑定、
  `scripts/langfuse/upload_golden_to_langfuse.py`（拒绝集分桶）、`harness/http_evaluation.py` 的 `rejection` 分支。

选项 (c) **按规则分别裁决**：A 与 B 各选一侧。

## 五、执行前置（与裁决同日完成）

1. **基线留档**：裁决前先跑并留存
   `python scripts/local_eval.py --data tests/datasets/biz`（真后端）与
   `python scripts/langfuse/langfuse_eval.py --local tests/datasets/intent` 的 `summary.json`；
   裁决后同口径重跑，按 ADR 0030 D3「PASS 率不低于前值」对比。
2. **数据集版本**：`caseNo` 是 Langfuse Dataset Item 稳定 ID（`scripts/langfuse/upload_golden_to_langfuse.py`），
   删除/改名会让旧 Item 悬空，需记一次数据集版本。
3. **lint 豁免**：裁决完成前，`scripts/check_dataset_consistency.py` 的 `PENDING_LINT_WAIVERS` 把
   `swap_rejection.jsonl` 的冲突与 `【待补充】` 占位降级为 WARNING；裁决后删除该条目并修复数据，
   同一规则立即恢复为 ERROR。
4. **占位数据**：`swap_rejection.jsonl:5,:9` 与 `intent/swap_instrument.jsonl` 5 处 `backend_codes: ["【待补充】"]`
   随裁决一起补齐或删除。

## 六、lint 状态（裁决后）

`python scripts/check_dataset_consistency.py` PASS；`--verbose` 现在列出：
- `intent/swap_instrument.jsonl` 5 处 `【待补充】` 占位（pending waiver，待业务补码）；
- 互换 3 个 biz 文件「无结构化 expected」按文件各 1 条汇总告警；
- 期权 15 条写类用例有 `expected` 但缺 `place_params` 的逐条告警。

裁决前的 26 条拒绝冲突告警随 `intent/swap_rejection.jsonl` 删除而消失。
