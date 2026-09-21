# 标的识别由后端负责

2026-09-20，按用户指定的 `tmp/场外交易-test (20).yml` 对齐职责。该主工作流只提取原文、
处理引用选择、归一化参数并调用业务接口；独立标的工具由 Java 调用。

## 数据流

```text
互换文本 → 原文候选 → 证据校验/归一化 → 对手或引用标的选择 → swap-order/operate
图片/Excel → 转写/逐行候选 → 证据校验/归一化 → swap-order/operate
普通期权询价 → 原文候选 → 证据校验/归一化 → financial-orders/operate
```

Java 负责精确匹配、标的工具调用、多候选、权限及市场校验。LangGraph 不提前把名称或月份表达
改成证券代码，不做证券池预检，也不因本地未匹配而阻止后端。业务回复沿用后端回执契约。

引用序号选择只映射到对应订单的引用候选；直接换标的保留用户新表达，即使它不在候选列表中。
订单范围和证据仍须一致。来源记录是用户原文或引用，不冒充 GOATS 识别结果。

## 兼容与提示词

- Java DTO 和业务 HTTP 路径不变，`placeOrderWindCode`、`stockCode` 可以承载原始名称或代码。
- 旧 checkpoint 的 `tickers`、`ticker_hitl_candidates` 继续可读、在入口清理；当前业务不产生本地证券结果。
  HTTP `tickers` 保持空列表，不能将其解释为后端未匹配。本地不再生成证券零命中或 ticker 消歧卡。
- 15 个业务 PromptSpec 保留固定 system。生成的当前时间和机器人名称名单均不送入 LLM。
- `sources` 每个来源只展示一次，历史 ID 与原文保留，`source_roles` 标记角色，参考信息在 `context`。
- 原字段旁的 `CandidateDescription` 定义原文候选语义；业务 DTO 描述继续定义最终值语义。
  保留候选结构和证据校验，本次不裁剪历史或压缩候选 schema 的嵌套结构。

## 验证和观测

业务回归检查传给后端的原始表达和实际回复。`case-021` 的旧 `winners` 检查迁移到已有完整后端卡片
断言，其中仍必须包含 `标的代码：600519.SH`。历史工具数据中的 `winners` 不自动判为通过，
也不从用户输入填充 `tickers`。统一验收只使用显式 categories，不并入历史工具集。

`otc_agent_llm_cache_tokens_total{model,node,result="hit|miss"}` 记录缓存输入量；
`otc_agent_llm_cache_usage_total{model,node,status="reported|unreported|invalid"}` 记录统计覆盖。
缺少缓存字段不是零命中。系统、用户消息及工具 schema 都计入输入大小评估；字符数不等于 token。
后端 Dify 的时间注入和缓存属于另一条调用链，本次未修改 Java 或后端工作流。
