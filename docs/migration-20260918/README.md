# 节点与字段迁移清单

由 `python -m scripts.export_migration_inventory --java-root <local-java-api>` 生成。
Java 只读。字段 JSON 是契约快照，运行时继续以 Pydantic 模型为真源。
Dify 节点 ID 未从原始 DSL 核实，不使用猜测 ID。旧字符数为本仓起点 c7be6f1 的 system 段。

| 活跃 PromptSpec | 输出契约 | 原文证据契约 | system 字符（前 → 后） |
|---|---|---|---|
| option/extract_inquiry | OptionInquiryRawParamsCandidates | 已接入 | 8472 → 462 |
| option/intent | OptionIntentOutput | 需逐项迁移/核对 | 6243 → 6243 |
| option_close/holding_query | HoldingQueryParams | 需逐项迁移/核对 | 6440 → 6440 |
| option_close/intent | CloseIntentOutput | 需逐项迁移/核对 | 7030 → 7030 |
| option_close/place_close | ClosePlaceParams | 需逐项迁移/核对 | 53202 → 53202 |
| router/unknown_intent | UnknownIntentOutput | 需逐项迁移/核对 | 8805 → 8805 |
| swap/excel_extract | SwapPlaceOrderParams | 需逐项迁移/核对 | 13974 → 13974 |
| swap/fresh_counterparty | SwapFreshCounterpartyOutput | 需逐项迁移/核对 | 720 → 720 |
| swap/image_extract | SwapPlaceOrderParams | 需逐项迁移/核对 | 66691 → 66691 |
| swap/image_ocr | 文本 | 需逐项迁移/核对 | 7300 → 7300 |
| swap/intent | SwapIntentOutput | 需逐项迁移/核对 | 12187 → 12187 |
| swap/place_order | SwapPlaceOrderParamsCandidates | 已接入 | 38898 → 557 |
| swap/select_counterparty | SwapSelectCounterpartyOutput | 需逐项迁移/核对 | 2817 → 2817 |
| swap/select_ticker | SwapSelectTickerOutput | 需逐项迁移/核对 | 2906 → 2906 |
| ticker/infer_code | InferCodeOutput | 需逐项迁移/核对 | 4888 → 4888 |
| ticker/judge_type | JudgeTypeOutput | 需逐项迁移/核对 | 801 → 801 |
| ticker/rank | RankOutput | 需逐项迁移/核对 | 6189 → 6189 |
| ticker/tokenize | SplitKeywordsOutput | 需逐项迁移/核对 | 10769 → 10769 |

| 当前业务模型 | 声明字段数 |
|---|---|
| SwapOrderItem | 26 |
| OptionOrderItemWithFastExec | 14 |
| OptionInquiryRawItem | 8 |
| CloseOrderItem | 9 |
| HoldingQueryParams | 7 |
| SwapOrderOpenApiBaseSaveReqVO | 11 |
| FinancialOrderOpenApiBaseSaveReqVO | 8 |

字段名、类型、描述及 Java 源码字段见 [field-contracts.json](field-contracts.json)。
数值/枚举/比例/时间归一化见 swap/normalize.py；期权确定性规则见 option/normalize.py 与 place_params.py。
尚未迁移的节点不能因为完成 PromptSpec 注册而计为符合节点迁移规范。
