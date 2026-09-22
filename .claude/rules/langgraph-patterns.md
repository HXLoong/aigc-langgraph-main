# LangGraph 模式

## 状态与边界

- 共享输入/输出字段在 app/graph/state.py 的 AgentState 声明；子图临时字段可放继承它的私有 TypedDict，output_schema 限制写回范围。
- 一轮唯一输入入口为 app/api/turn_state.py::inputs_to_state。per-turn 字段在 ingest 重置；跨轮记忆、会话活动时间遵循已实现的过期逻辑。
- trace 使用 merge_by_id，history_messages 使用 merge_history，field_records 使用 merge_fields；新并行通道选择明确的 reducer，不照搬累加以免重复。
- 节点返回 partial update，不原地修改输入；交易最终值由 Code 归一化和权威源校验。来源记录及锁定必须在实际后端请求边界生效。
- 子图已返回 CompiledStateGraph 时直接嵌入，不再次 compile；以 app/subgraphs/*/graph.py 当前函数签名为准。

## IO 与错误

- 纯计算及写类节点用 @safe_node；只读 IO 用 @io_node，并通过 add_io_node 注册 RetryPolicy。默认最多2次尝试，LLM SDK max_retries=0；写接口不自动重试。
- 错误由 ErrorInfo 和 cascade 路由处理；后端查询失败不能伪装成空记录继续交易。
- 条件路由为纯函数，错误优先转 fallback；副作用只在节点里执行。
- 业务请求通过 OptionClient/SwapClient/TickerClient Protocol。子图 backend.py 负责 DTO 构造、BotContext 身份、字段锁定和真实回复透传。
- 每条消息按既有产品与意图优先级进入一个业务分支，该分支识别出的多笔订单统一使用本轮动作；混合措辞不按分句拆成不同动作，也不新增多动作识别门禁。例如识别为撤单申请后，A、B 两笔订单都按撤单申请处理。原有身份、归属、状态和确认校验继续执行；提交保留原 messageId，遵守 Java 幂等与批量契约。

## 提示词

- 每个 LLM 节点声明 PromptSpec；模型使用 with_structured_output，字段说明由 Pydantic Field(description=) 提供。
- 原文候选含 evidence/confidence/source；Code 验证原文并做单位/枚举/身份解析。禁止手工 JSON 容错或模型直接决定交易最终值。
- 无新增 ReAct/ToolNode/bind_tools 路线；工具由 Code 节点选择调用。

## 持久化与运行

- 生产 checkpointer 使用 app/checkpointer/factory.py 的池及表前缀适配，唯一连接配置 MYSQL_URI。
- 首次通过 sql/init.sql 初始化；启动只读校验，不在节点调用 saver.setup 建表，不使用生产单连接 from_conn_string。
- 测试使用 InMemorySaver；没有跨轮要求的纯计算子图可显式 checkpointer=False。
- thread_id 固定为 conversation_id；消息、群、用户身份必须沿用真实入口，禁止截断数字ID。
- 确认采用文本两阶段：七条最终确认路径均须明确动作并引用当前订单，范围由 app/execution/confirmation.py 校验；历史记忆及程序生成的引用不能替代用户引用。
- 不引入 interrupt 确认；递归上限通过 API 的统一 config 设置。
- Langfuse callbacks 由请求入口统一注入，子图自然继承；本地审计写 langgraph_node_trace。

## 并行开发

依根 CLAUDE 中工作树分工执行。主代理统一管理共享字段、Settings、主图、API输出、数据库和服务；子代理先提出共享契约需求再集成。轻量验证遵循用户范围。
