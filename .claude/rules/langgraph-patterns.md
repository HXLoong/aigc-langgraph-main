# LangGraph 模式

## 状态与边界

- 共享输入/输出字段在 app/graph/state.py 的 AgentState 声明；子图临时字段可放继承它的私有 TypedDict，output_schema 限制写回范围。
- 一轮唯一输入入口为 app/api/turn_state.py::inputs_to_state。per-turn 字段在 ingest 重置；跨轮记忆、会话活动时间遵循已实现的过期逻辑。
- trace 使用 merge_by_id，history_messages 使用 merge_history，field_records 使用 merge_fields；新并行通道选择明确的 reducer，不照搬累加以免重复。
- 节点返回 partial update，不原地修改输入；LangGraph 保留提取值与来源，不做业务归一化或数字校验；Java 校验业务值与默认值（ADR 0027，代码待迁移）。来源记录及锁定必须在实际后端请求边界生效。
- 子图已返回 CompiledStateGraph 时直接嵌入，不再次 compile；以 app/subgraphs/*/graph.py 当前函数签名为准。

## IO 与错误

- 纯计算、LLM 和写类节点用 @safe_node；仅独立的后端只读查询用 @io_node + add_io_node 注册 RetryPolicy。单次调用内 LLM 的 SDK、图层与外层封装均零重试；后端查询失败不得连带重跑模型。每次工具调用独立计数，额度与失败边界见 ADR 0031；当前代码迁移状态见 docs/work-plan.md。
- add_io_node 在最后一次可重试失败时由原节点返回 ErrorInfo，沿原图边完成汇合、回复和审计；with_error_handler=False 才在耗尽后继续抛出。主图与并行错误收尾由 tests/graph/test_retry_recovery.py 守护。
- 错误由 ErrorInfo 和 cascade 路由处理；后端查询失败不能伪装成空记录继续交易。
- 条件路由为纯函数，错误优先转兜底：主图 `_route_after_intent` 等转 `fallback` / `render`，子图内 `_route_after_<p>_intent` 转 `<p>_unknown`（先查 `has_error`）；副作用只在节点里执行。
- 外部请求只经 `app/tools/*_client.py` 的 Protocol（OptionClient / SwapClient / MessageClient / GoatsAgentClient）+ `app.tools.http_pool` 单例池，不在节点里 new `httpx.AsyncClient`；TickerClient 只供授权对手查询；业务、测试、验收与探针都禁止调用证券查询接口。子图 backend.py 负责 DTO 构造、BotContext 身份、字段锁定和真实回复透传。
- 每条消息按既有产品与意图优先级进入一个业务分支，该分支识别出的多笔订单统一使用本轮动作；混合措辞不按分句拆成不同动作，也不新增多动作识别门禁。例如识别为撤单申请后，A、B 两笔订单都按撤单申请处理。本次身份与选择范围沿用输入契约，归属、状态和后续流程由 Java 校验；不在 LangGraph 强制二阶段；提交保留原 messageId，遵守 Java 幂等与批量契约。

## 提示词

- 新增或重构模型节点时先读 `docs/adr/0031-single-model-request-per-message.md`：单次工具调用的主图与全部子图共享最多一次真实模型请求额度，产品/意图/候选联合解析，Excel 批量输入；本阶段统一 deepseek-v4-pro，图片暂不处理，不安排 OCR / 多模态链路；保留独立确定性节点，不逐行、逐图、逐订单追加模型调用。

- 每个 LLM 节点声明 PromptSpec；模型使用 with_structured_output，字段说明由 Pydantic Field(description=) 提供。
- 提取值保留原文与 evidence/confidence/source；Code 检查结构、来源和引用选择，按现有 DTO 传输，不做单位换算、数值校验或业务默认值补齐。Java 校验业务参数，不手工 JSON 容错或让模型宣称交易成功。
- 无新增 ReAct/ToolNode/bind_tools 路线；工具由 Code 节点选择调用。

## 持久化与运行

- 请求职责遵循 ADR 0026：消息防重、并发调度、重投与重复通知归调用端，交易执行幂等归 Java；LangGraph 每次合法调用独立处理，message_id 仅用于业务传递和审计关联。现有占位、回放与对账实现待清理，见 docs/work-plan.md；checkpointer 和节点审计独立保留。
- 生产 checkpointer 使用 app/checkpointer/factory.py 的池及表前缀适配，唯一连接配置 MYSQL_URI。
- 首次通过 sql/init.sql 初始化；启动只读校验，不在节点调用 saver.setup 建表，不使用生产单连接 from_conn_string。
- 测试使用 InMemorySaver；没有跨轮要求的纯计算子图可显式 checkpointer=False。
- thread_id 固定为 conversation_id；消息、群、用户身份必须沿用真实入口，禁止截断数字ID。
- 递归上限通过 API 的统一 config 设置。
- Langfuse callbacks 由请求入口统一注入，子图自然继承；本地审计写 langgraph_node_trace。
- 节点公共契约只维护在 app/node_execution/catalog.py；执行平台负责 schema 与客户端注入，harness 负责展示和回放策略。暴露范围可不同，写节点保持禁止回放。

## 确认指令职责

- 按 ADR 0021，LangGraph 不做二阶段处理，不强制申请后等待确认，也不把普通动作自动改成确认。每次识别动作、订单号及本次适用的显式增量参数，Java 读取订单、合并参数、校验并执行；普通确认不从历史或卡片重建完整订单。现有代码待收敛项见 docs/work-plan.md。
- 现有确认类输入按本次动作与引用范围处理，当前 app/domain/confirmation.py 是旧实现核对入口；历史记忆与程序生成的引用不代替用户选择。保留 Java 确认 type 与补参契约，业务状态和后续流程由 Java 决定，目标收敛不新增本地强制二阶段。
- 确认不依赖 LangGraph 保存待确认订单或 interrupt 恢复；checkpointer 的会话持久化配置要求独立适用。
