# 2026-09-23 数据集标注决策

本次用户明确授权自主方案、默认评审通过。以下标注按原始用户输入、已存在的意图协议和Pydantic字段契约整理；没有以模型实际输出反抄expected。

## #226 八条意图补齐

- case-022/023/024：期权快速询价，业务意图为option/new_inquiry。
- case-025/026/027/028/029：首轮option/new_inquiry，后续各轮为option/place_order_from_quote；原用例均未包含最终确认，不新增confirm_order标签。
- 共8条16轮；沿用derive_intent_fixtures.derive_case投影，去除卡片文本断言，保留原始输入和引用开关。
- 意图目录由383增至391条；375条互换原文/市场候选和既有8条期权/平仓案例未为模型失败更改。

## #220 首批十二轮结构断言

| 用例/轮 | 依据原文确定的字段 |
|---|---|
| case-021/1 | 原文600519.SH、欧式看涨、1M、行权80 |
| case-025/2 | 当前引用订单、市价单 |
| case-025/3 | 当前引用订单、2000000、引用A对手 |
| case-026/2 | 两笔分别2000000/1000000、限价10/6、引用A/B；最大跟量只断言意图 |
| case-028/2 | 2500000、POV11、限价10、引用A |
| case-028/3 | 当前引用订单POV12；未重传的本金/限价为 null，返回卡片仍保留250万和限价10 |
| case-029-lifecycle/3 | place确认及当前引用单号 |
| case-030/2 | 引用第一笔合约、全平、限价10 |
| case-030/3 | close确认及引用完整CO订单范围 |
| case-031/2 | 引用合约、1000000、最大跟量意图 |
| case-034/2 | 引用合约、2000000、TWAP14:30–14:50、限价10 |
| case-034/5 | cancel_close确认及引用完整CO订单范围 |

动态单号、对手字母和持仓合约使用现有$ref协议，只读取本轮完整quote，不从本轮模型输出或未引用历史取值。不固化真实单号、后端默认比例、可用余额。原卡片文本断言全部保留。

这是已应用的首批标注；真实HTTP/Java与模型验收仍分别记录，不因标注提交而宣称业务流程通过。

## 拒绝验收单列（#227）

逐条复核原始输入与既有 `test_direction_remains_ambiguous_or_conflicting`、非正数量契约后，将 26 条暂定/历史动作和 1 条负数量样本从 `intent/swap_instrument.jsonl` 移至 `intent/swap_rejection.jsonl`。用户本轮明确授权自主方案、默认评审通过，因此按现有安全契约完成本次标注决策。

原始输入、案例 ID、来源与历史标的候选完整保留，历史候选移入 `reference.original_instrument_assertions`；categories 原文和断言没有因此改动。拒绝输入不应向 Java 提交标的订单，所以它们不再用“成功提交的标的列表”作为正确性标准。

新增 `expected.rejection` 只允许特定业务原因；拒绝评分必须同时满足对应节点与异常类型、非空用户回复、错误节点 trace、没有下单提交节点、没有 api_code/api_result/place_params。网络错误、LLM 错误、泛化 ValueError、后端拒绝和伪成功都不能冒充正确拒绝。

总数仍为 391：正向/普通意图 364，明确拒绝 27。质量门同时要求总体与正向组达到 95%，拒绝组达到 100%；不靠加入负例抬高正向通过率。旧的 347/391（88.75%）属于变更前标注，必须与新标注结果分别记录，不能将标注变化全算作代码提升。

| 原案例 ID（前缀 intent-swap-instrument- 保留） | 标注原因 |
|---|---|
| ai_trade_assist_prod_accept_order_case_77 | 非正数量 |
| ai_trade_assist_prod_swap_order_case_13 | 暂定或历史动作 |
| ai_trade_assist_prod_swap_order_case_14 | 暂定或历史动作 |
| ai_trade_assist_prod_swap_order_case_18 | 暂定或历史动作 |
| ai_trade_assist_prod_swap_order_case_19 | 暂定或历史动作 |
| ai_trade_assist_prod_swap_order_case_36 | 暂定或历史动作 |
| ai_trade_assist_prod_swap_order_case_42 | 暂定或历史动作 |
| ai_trade_assist_prod_swap_order_case_44 | 暂定或历史动作 |
| ai_trade_assist_prod_swap_order_case_50 | 暂定或历史动作 |
| ai_trade_assist_prod_swap_order_case_72 | 暂定或历史动作 |
| ai_trade_assist_prod_swap_order_case_74 | 暂定或历史动作 |
| ai_trade_assist_prod_swap_order_case_77 | 暂定或历史动作 |
| ai_trade_assist_prod_swap_order_case_81 | 暂定或历史动作 |
| ai_trade_assist_prod_swap_order_case_84 | 暂定或历史动作 |
| ai_trade_assist_prod_swap_order_case_85 | 暂定或历史动作 |
| ai_trade_assist_prod_swap_order_case_86 | 暂定或历史动作 |
| ai_trade_assist_prod_swap_order_case_87 | 暂定或历史动作 |
| ai_trade_assist_prod_swap_order_case_92 | 暂定或历史动作 |
| ai_trade_assist_prod_swap_order_case_93 | 暂定或历史动作 |
| ai_trade_assist_prod_swap_order_case_94 | 暂定或历史动作 |
| ai_trade_assist_prod_swap_order_case_96 | 暂定或历史动作 |
| ai_trade_assist_prod_swap_order_case_103 | 暂定或历史动作 |
| ai_trade_assist_prod_swap_order_case_104 | 暂定或历史动作 |
| ai_trade_assist_prod_swap_order_case_107 | 暂定或历史动作 |
| ai_trade_assist_prod_swap_order_case_111 | 暂定或历史动作 |
| ai_trade_assist_prod_swap_order_case_117 | 暂定或历史动作 |
| ai_trade_assist_prod_swap_order_case_125 | 暂定或历史动作 |

## 候选输入名称与 Java 字段分离

CI 原生 `deepseek-v4-pro` 持续把买卖动作填入旧字段名 `placeOrderTransactionType`，而本地网关别名的表现不同。除保持现有证据、否定与市场限制校验外，候选模型现在使用语义明确的 `market_selection` 输入名。`CandidateInputName` 元数据和统一候选工厂承担转换：模型输入名可以独立命名，候选及规范化输出的序列化仍为原 Java 字段名，既有字段记录路径保持不变。旧候选输入可恢复；不同别名同时给出矛盾值时拒绝，不能静默选一项。

这不是 Java DTO 或 HTTP 协议迁移，没有修改 Java。此项技术修复不修改数据标签或质量门槛；需要分别验证本地网关和 CI 原生模型，单侧通过不能替另一侧宣称通过。

## 2026-09-24 增量建仓参数标注纠正

case-028 第三轮只说“改POV12”。现行 `option/place_params.py` 的 A 类参数只从本轮原文提取；Java `PlaceOrderFromQuoteServiceImpl` 对本人本群订单从数据库回填本轮未提供的本金、限价等字段。因此请求断言改为 `notionalAmount=null`、`limitPrice=null`，仍严格检查当前引用单号、POV 和比例12；原返回卡片的250万本金、限价10、对手等文本断言全部保留。不是删除保留参数的业务要求，而是分别检查增量请求和最终订单状态。

真实复测在装载已有授权测试库中的 Dify 工具认证后，前三轮均进入期权链路，第三轮 Java 卡片保留本金与限价；原两项差异来自标注误把最终状态当成本轮请求。新增解析器→正式 fixture 断言复现测试先 RED，再修标注到 GREEN，并保留错误 POV 比例必失败的反例。认证只临时装载到独立真实联调库，脱敏种子不含认证。
