# 架构

现行实现以每次合法调用为边界：规则准备上下文，一次联合模型解析，产品子图确定性执行，Java 负责业务校验和真实回执。改动的验证进度见[工作计划](../work-plan.md)，设计依据见 [ADR 索引](../adr/README.md)。

## 图文档

每个实际图独立成文，主图只展示产品子图入口。

| 图 | 流程 |
|---|---|
| 主图 | [main-graph-flow.md](./main-graph-flow.md) |
| 期权 | [option-graph-flow.md](./option-graph-flow.md) |
| 互换 | [swap-graph-flow.md](./swap-graph-flow.md) |
| 期权平仓 | [close-graph-flow.md](./close-graph-flow.md) |
| 普通期权询价内部图 | [option-inquiry-flow.md](./option-inquiry-flow.md) |
| 互换下单准备内部图 | [swap-place-flow.md](./swap-place-flow.md) |
| 平仓下单内部图 | [close-place-flow.md](./close-place-flow.md) |
| 节点调试执行图 | [node-execution-flow.md](./node-execution-flow.md) |
| 标的职责 | [backend-instrument-boundary.md](./backend-instrument-boundary.md) |

## 分层与职责

- `app/api/` 处理 HTTP、请求期限和观测上下文；`app/node_execution/` 提供独立节点准备与执行。
- `app/graph/main.py` 组装主图；`app/nodes/` 处理入口、联合解析和收尾；三个产品子图互不依赖。
- `app/parsing/` 定义产品输出、字段证据、PromptSpec 与 Excel 原文。子图消费同一个解析结果，不再次询问模型。
- `app/extraction/` 保留字段来源与锁定；`app/domain/` 保留订单身份、序号和本次动作检查。金额、期限、价格、比例及默认值不在后续代码里重算。
- `app/tools/` 用现有 Java Protocol 和 DTO 提交，业务回执保持权威。证券识别只由 Java 内部工作流完成。

主图和节点 HTTP 调用共用 `app/llm/budget.py` 的真实请求额度。SDK、模型节点和外层封装零重试，失败消耗额度；后端只读查询在独立节点有限重试。相同消息 ID 的再次合法调用重新执行，LangGraph 不占位、不回放旧响应、不管理交易幂等。

## 存储与回执

全项目只使用 `MYSQL_URI`。生产要求 MySQL checkpointer，启动只读校验表结构；节点审计和会话历史继续保留。订单状态以 Java 为准，确认只提交本次明确身份及增量，历史不替代本次授权。

旧 `langgraph_message_log` 历史表保持原状；本次重构移除运行时幂等和对账代码，不删除历史表或数据。不确定回执只描述当前执行结果，不能据此重试交易或伪造订单卡。

## 观测与评测

评测 Experiment → 用例 → HTTP 轮 → 服务端 LangGraph → 节点/模型共用一条 Trace 和一个规范化 Session。服务端仅在可信入口开启 `TRUST_INBOUND_TRACEPARENT`；业务会话 ID 原样保留，不合法的观测 Session ID 单独编码。

`/ready` 检查 MySQL、Java 传输连通及可选观测/模型依赖。Java 探针只建立 TCP 连接，不用缺少客户身份的业务请求当健康检查；TCP 可达不代表业务权限或交易验收通过。授权业务验收使用真实测试群、用户和业务接口。

业务和意图回归都从 HTTP 入口执行，比较明确的字段与文本断言；Langfuse Experiment 保存分数和差异，不调用 Judge。节点 Dataset 支持审阅发布、版本快照与 HTTP 回归，写节点只留存标注并 SKIP；没有有效标注时仍为待验收。业务参数标注缺口单列，不与现有断言的 PASS 混淆。
