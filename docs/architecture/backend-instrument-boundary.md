# 标的识别由 Java 调用工作流完成

标的识别由 Java 后端调用对应的标的识别工作流完成，工作流的选择、调用及结果处理均由后端负责。
LangGraph 提取标的原始表达或用户对引用候选的明确选择，通过现有业务接口提交给 Java，
并按回执契约呈现后端结果。决策与理由见 [ADR 0025](../adr/0025-instrument-resolution-delegated-to-backend.md)。

## 数据流

```text
LangGraph：从文本 / Excel / 引用中提取标的表达或选择（本阶段图片暂不处理）
    → 检查结构、来源与选择范围，按现有接口装配请求（ADR 0027 目标）
    → 提交 Java 业务接口（互换 swap-order/operate；普通期权询价 financial-orders/operate）
Java：按业务需要调用对应的标的识别工作流
    ← 工作流返回识别结果
    → 完成业务校验与处理，生成回执
LangGraph：按回执契约呈现 Java 返回结果
```

LangGraph 不调用或编排识别工作流，不承担证券匹配、代码补全、近月合约计算、证券池查询及
有效性或可交易性校验。名称、完整代码和月份表达均作为输入提交，不因本地未匹配而阻止后端。
证券查询接口在本地业务、测试、验收和探针中均禁止调用；`ticker_client.py` 仅保留授权对手列表用途。识别规则与数据源属于后端职责；Java 接收工作流结果，负责多候选业务处理、权限与市场校验。

引用序号选择只映射到对应订单的引用候选；直接换标的保留用户新表达，即使它不在候选列表中。
订单范围和证据仍须一致。提取与选择只表达用户输入，其来源记录不代表标的已完成业务校验。

## 兼容与提示词

- Java DTO 和业务 HTTP 路径不变，`placeOrderWindCode`、`stockCode` 可以承载原始名称或代码。
- 旧 checkpoint 的 `tickers`、`ticker_hitl_candidates` 继续可读、在入口清理；当前业务不产生本地证券结果。
  HTTP `tickers` 保持空列表，不能将其解释为后端未匹配；证券零命中与候选提示以 Java 回执为准。
- 14 个业务 PromptSpec 保留固定 system。生成的当前时间和机器人名称名单均不送入 LLM。
- `sources` 每个来源只展示一次，历史 ID 与原文保留，`source_roles` 标记角色，参考信息在 `context`。
- 原字段旁的 `CandidateDescription` 定义原文候选语义；业务 DTO 描述继续定义最终值语义。
  现有候选结构仍在；ADR 0027 已修订为保留结构与来源检查、移除本地数字校验及业务归一化，代码迁移见工作计划。

## 验证和观测

LangGraph 回归检查原始表达、引用选择与实际提交参数的一致性；端到端业务回归检查 Java 的真实
识别结果与回复是否符合数据集期望。名称、完整代码、月份表达及附件都遵循这一边界，不从用户输入
填充 `tickers`。统一验收只使用显式 biz，不并入历史工具集。

提交表达错误时排查 LangGraph 的提取与选择链；提交表达正确而识别结果错误时，排查 Java 调用记录
及对应标的识别工作流。LangGraph 的本地测试不替代识别工作流与后端业务验收。

`otc_agent_llm_cache_tokens_total{model,node,result="hit|miss"}` 记录缓存输入量；
`otc_agent_llm_cache_usage_total{model,node,status="reported|unreported|invalid"}` 记录统计覆盖。
缺少缓存字段不是零命中。系统、用户消息及工具 schema 都计入输入大小评估；字符数不等于 token。
后端 Dify 的时间注入和缓存属于另一条调用链，本次未修改 Java 或后端工作流。
