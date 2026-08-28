# 意图识别问题评估报告（客户反馈 bug 定位）

- 日期：2026-08-28
- 背景：客户反馈"意图识别存在 bug"；本报告针对当前分支（DSL v2 一级路由迁移后，`feature/dify-dsl-migration`）做系统性评估
- 方法：golden 535 条 × 802 轮离线过规则层（`is_swap_transaction`）+ 244 条规则未触发样本实测 LLM 兜底（DeepSeek-V4-pro）+ 代码结构分析 + 评估口径审计
- 结论级别按 [ADR 0019](./adr/0019-incident-severity-thresholds.md) 语义：P0 = 必修（客户可稳定复现的错误行为）；P1 = 应修；P2 = 观察

## 总览数字

| 口径 | 覆盖率（规则触发）| 触发精准率 | 落 LLM 兜底 |
|---|---|---|---|
| 首轮（单轮指令）| 478/520 = **91.9%** | 473/478 = **99.0%** | 42 条 |
| 全轮次（含多轮跟进）| 558/802 = **69.6%** | 513/558 = **91.9%** | 244 条（30%）|
| LLM 兜底实测（244 条）| — | **6.1% 正确**，229 条判 unknown → fallback | — |

**单轮指令的意图识别是好的**（99% 精准）。问题集中在**多轮跟进场景**（引用卡片后的续话、裸发"确认下单"）——这正是企微实际使用的主形态，与客户体感吻合。

⚠️ 口径声明：上表 quote 用的是 golden 的 `quote_desc`（占位描述，见 P0-2）；生产/主评估链路的 quote 是上一轮机器人真实回复。因此上表**低估**生产表现，但下述 P0-1 的错分与 quote 内容无关（结构性），P1-3 在无引用/卡片无产品词场景必然复现。

## P0-1 · 规则层高优先级分支不消费引用语境（结构性错分，生产可复现）

`route_rules.classify_trade_type` 的判定顺序：订单号 → **口语化平仓(step2)** → 互换系统引用 → **互换下单特征(step4)** → 平仓查询关键词 → 关键词计数(step6)。**step2/step4 只看 raw_text、完全不看 quote_content**，而它们排在唯一消费 quote 产品语境的 step6 之前。

后果（golden 实锤 45 条错分，典型样本）：

- 引用**期权持仓卡**后说「序号1市价全平」「序号1市价平一半」→ step2 口语化平仓命中 → **判互换**（27 条 option_close→swap）。最恶劣样本：「序号1 市价把这张期权平一半」——**raw 里明写"期权"仍判互换**（step2 在 has_explicit_option 检查之前）。
- 引用**期权询价卡**后说「本金200万，现在就按市价买入」→ step4 方向词+市价命中 → **判互换**（15 条 option→swap 中含方向词的部分）。
- 进错子图后 cascade 无救：close 二级 intent 的「序号N」规则（`close/intent.py:96`）再对也到不了。

生产口径的救回条件与边界：

- 引用卡含 CO-/Q-/OPT- 单号 → step1 救回（**持仓列表卡是否嵌单号取决于后端真实回复，待真后端 eval 验证**；本仓 `_render_close_card` 平仓申请卡含单号，期权**询价卡不含 Q- 单号**只含"期权"字样）。
- 无方向词、无"平X"的跟进（「200万 POV25 限价10」）可被 step6 计数救回（quote 含"期权"×N）。
- **必错场景**：含"平X/全平"或方向词的跟进 + 引用卡无单号——step2/step4 在 step6 之前截胡，quote 全文救不了。

修复方向（TDD，45 条错分作红例）：step2/step4 增加语境让位——raw 或 quote 含明确期权特征（"期权/看涨/看跌/雪球/CALL/PUT"或期权卡标记）时跳过该 step 交给后续层；即把现有 step4 的 `has_explicit_option` 检查前移并扩展到 step2、扩展到 quote。改动属 DSL 迁移的工程修正，须在 ADR 0015 DSL v2 落地段登记（原四层路由的 quote_marker 层正是修这类多轮 bug 的，1:1 迁移时被删）。

## P0-2 · 评估口径缺陷：规则层单测拿占位符当 quote（所有规则层质量数字失真）

golden 的 `quote_desc` 是**占位描述**（如"用户引用持仓消息回复"），不是卡片全文。`scripts/langfuse_eval.py`（主评估链路）口径正确——它把上一轮真实 reply 作为 quote 传入（:117-126）；但 `tests/test_intent_route.py::test_rule_layer_precision` 直接把 `quote_desc` 占位文本当 quote_content 用——**该测试通过（≥80%）不代表引用场景正确**：全轮次 91.9% 精准率下 45 条引用场景错分照样通过，80% 阈值形同虚设。

修复方向：单测构造**真实卡片文案 fixture**（询价卡/持仓卡/订单卡模板 + 各类跟进指令）替代占位 quote；引用场景单独断言（阈值应显著高于 80%）。

## P1-3 · LLM 兜底对上下文缺失样本近乎全判 unknown → fallback 打断对话

244 条规则未触发样本实测（DeepSeek-V4-pro + `router/unknown_intent.md`）：**6.1% 正确，229 条判 unknown**——落到 cascade fallback（"我没完全理解你的意思，能换种说法重新告诉我吗"）。样本几乎全是多轮跟进：「确认下单」「200万」「限价6」「临沂阿凡提」（补交易对手）「序号1市价平留300万」。

口径限定：生产上落 LLM 的集合比 244 小（quote 全文让 step6 命中）。但以下场景**必落此路径且必 fallback**：

1. **用户不引用、裸发跟进**（golden 后续轮 282 条中 14 条无引用；企微真实使用中更常见）——上一轮 `product_type` 明明在 checkpoint 里，`intent_route` 每轮全量重算且 LLM 兜底只喂 raw+quote，**不利用会话历史**；
2. 上一轮 reply 是后端错误短消息（eval 已专门规避该坑，`_is_unusable_quote`——生产没有这层规避）；
3. 引用卡无产品词/单号。

客户最易复现的体感 bug：**对着机器人说"确认下单"，得到"我没完全理解你的意思"**。

修复方向（需小型决策/ADR，属 DSL 之外的工程增强）：二选一或组合——(a) `intent_route` 增加多轮粘性：规则+LLM 均 unknown 且 checkpoint 有上一轮 `product_type` 时继承之（trace 记 `sticky→<pt>`）；(b) LLM 兜底带 `history_messages` 末 N 轮。方案 (a) 改动小、确定性强，推荐。

## P1-4 · `Q-` 单号归属分歧（业务裁决项）

DSL v2 按源工作流把 `Q-\d{8}-` 归 **option**（d5397af 明确记载）；golden `opt_close-064`（「撤单 Q-20260114-…」）期望 **option_close**。撤询价单究竟走 option 撤单链还是平仓撤单链，需业务方一句话裁决，然后统一 golden 或规则——否则该类 case 永远红。

## P2 · 观察项（不阻塞）

- `tests/test_api.py` 直连真实 DeepSeek（无 mock），全量跑受网络抖动影响偶发红（本次复现一次，单跑即绿）——建议 mock 或标记。
- golden 与 DSL v2 意图集漂移（凌晨架构体检已列，#131 重基线是种子）——二级意图（option 7 意图/新增节点）的量化评估依赖重基线 + 真后端全量 eval（#133/#135）。
- swap 二级 5 节点去 LLM 化（d7abc11）方向正确（幻觉面清零）；其确定性提取器已有 35 例测试覆盖，本轮未发现问题。
- LLM 兜底 prompt（391 行）语义保守是 DSL 原样——在 P1-3 修复后其压力会大幅下降，暂不动 prompt。

## 建议动作序（对齐 #85「只修 P0/P1」纪律）

1. **P0-1**：`route_rules` step2/step4 语境让位（TDD，45 条错分红例入 `tests/nodes/`）
2. **P0-2**：规则层单测换真实卡片 fixture + 引用场景独立断言
3. **P1-3**：多轮粘性小 ADR + 实现（推荐方案 a）
4. **P1-4**：业务裁决 Q- 归属（一句话），统一 golden/规则
5. 修复后跑 `langfuse_eval.py`（真 quote 口径）重量化多轮通过率——依赖 #133/#135 真后端

## 附录 · 数据来源

- 离线扫描脚本与 LLM 实测样本：session scratchpad（`rule_sweep.py` / `llm_fallback_eval.py`，244 条样本清单 `/tmp/llm_fallback_samples.json`）
- 错分明细 45 条完整清单可由扫描脚本复现（golden 全轮次口径）
