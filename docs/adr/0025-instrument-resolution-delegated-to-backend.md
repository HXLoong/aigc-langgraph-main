# ADR 0025 · 标的识别职责边界：Java 调用识别工作流

## 状态

- 状态：已采纳
- 日期：2026-09-20
- 记录方式：追认已有实现（commit `2f9ce65`）
- 关系：修订 [ADR 0001](./0001-rewrite-app-with-harness-first.md) D4、[ADR 0023](./0023-prompt-as-code-langgraph.md)、[ADR 0024](./0024-langgraph-native-rearchitecture.md) D2 / D3
- 执行说明：[docs/architecture/backend-instrument-boundary.md](../architecture/backend-instrument-boundary.md)
- 作者：图灵科技 + Tony

## 背景

提取交易指令中的标的表达，与识别该表达对应的真实标的是两项职责。前者由 LangGraph 完成，后者由 Java 后端调用对应的标的识别工作流完成。

识别规则与数据源由后端维护。LangGraph 再实现证券匹配或维护名称到代码的映射，会形成重复实现，并可能在提交前拦截后端能够识别的表达。职责应集中在后端，LangGraph 只对表达提取、用户选择和业务请求负责。

## 决策

### D1 · 识别工作流归 Java，表达提取归 LangGraph

- Java 后端负责选择、调用对应的标的识别工作流并处理识别结果；工作流的编排、识别规则及数据源均属于后端职责。
- LangGraph 提取用户的标的原始表达（名称、代码或月份描述），或用户对引用候选的明确选择，通过既有业务接口提交给 Java。来源记录保留原文、引用或附件证据；提取结果只表示识别输入。
- LangGraph 不调用或编排标的识别工作流，不承担证券匹配、代码补全、近月合约计算、证券池查询及有效性或可交易性校验，也不因本地未匹配而拦截请求。
- 引用序号选择只映射到对应订单的引用候选；直接换标的保留用户新表达。消息证据与选择范围校验不等于标的业务校验。

`app/tools/ticker_client.py` 保留用于授权对手列表；本地业务、测试、验收脚本和探针均不得直接调用证券查询接口 `/securities-instrument/select`。完整出站清单见 [Java 后端契约](../api-contracts/java-backend.md#langgraph-出站后端-api-清单)。

### D2 · 数据流

```text
用户文本 / Excel / 引用选择（本阶段图片暂不处理）
    → LangGraph：提取标的表达与交易参数，保留来源，校验结构与引用选择范围
    → Java 业务接口：接收原始表达或用户选择
        → 按业务需要调用对应的标的识别工作流
        ← 返回识别结果
        → Java 完成业务校验与处理，生成回执
    → LangGraph：按回执契约呈现后端结果
```

Java 接收工作流的识别结果，负责多候选业务处理、权限与市场校验；LangGraph 不根据本地参数推断识别或交易成功。业务回复沿用后端回执契约（[ADR 0026](./0026-request-idempotency-uncertain-receipts-reconciliation.md) D3）。

### D3 · 兼容边界

- Java DTO 与 HTTP 路径不变：`placeOrderWindCode` / `stockCode` 可承载原始名称或代码。
- HTTP 输出 `tickers` 保持空列表兼容字段，**不能解释为后端未匹配**；证券零命中与候选提示以 Java 回执为准。
- 识别工作流的内部接口与实现不属于 LangGraph 契约。Java 业务接口约定见 [Java 后端契约](../api-contracts/java-backend.md)。

### D4 · 验证口径

- LangGraph 回归检查表达提取、引用选择和实际提交参数的一致性，覆盖名称、完整代码、月份表达及附件；不以本地证券命中或 `tickers` 内容作为通过条件。
- 端到端业务回归检查 Java 的真实识别结果与回复是否符合数据集期望；统一验收只使用显式 `tests/datasets/biz/`。
- 提交表达有误，排查 LangGraph 的提取与选择链；提交表达正确而识别结果有误，排查 Java 调用记录及对应识别工作流。

## 备选方案

- **LangGraph 自行识别，再由 Java 校验**：重复维护识别规则与数据依赖，容易产生结果漂移。
- **LangGraph 直接调用识别工作流**：把工作流的编排与结果处理引入指令解析侧，拆散后端职责。
- **LangGraph 提交表达，Java 调用识别工作流（已选）**：通过业务接口隔离职责，识别规则与数据源集中在后端。

## 后果

- 正面：识别职责集中在 Java 及其调用的工作流，LangGraph 的代码与提示词无需维护证券事实清单或重复识别逻辑。
- 代价：LangGraph 本地测试只能证明表达提取与提交正确；识别准确性仍须结合真实后端与数据集验收，排错需要 Java 和识别工作流的记录。
- 未决：`tickers` 兼容字段何时从外部协议移除。
