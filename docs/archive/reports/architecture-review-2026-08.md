# otc-agent 架构评估:FastMCP 封装与 A2A 协同的引入决策

> 编写:图灵科技 · 2026-08-28 · 基于分支 `feature/dify-dsl-migration`(DSL v2 迁移后)
> 评估准绳(按用户要求):**可维护性 / 简洁性 / 与 harness 评测台的契合度**
> 研究输入:LangGraph 1.x 生产实践、FastMCP/MCP 生态现状、A2A 协议一周年落地情况、
> "12-Factor Agents" 生产共识(文末 Sources)

---

## 0. 结论速览

| 议题 | 结论 | 一句话理由 |
|---|---|---|
| **FastMCP 封装 GOATS/OTC 后端接口** | **不建议现在做**(整体封装);保留一个窄场景选项 | 后端调用是图节点内的**确定性类型化调用**,不是 LLM 自选工具——MCP 解决的"跨框架工具共享"问题在本系统不存在,引入只会增加序列化边界、部署单元与 mock 复杂度 |
| **A2A 多 Agent 协同** | **暂缓**;定义清晰的触发条件后再评估 | A2A 解决"跨运行时/跨团队的独立 agent 互操作";本系统是单进程 LangGraph 单体图,第二个独立 agent 尚不存在,协议先行是倒置 |
| **当前架构 vs 2026 生产共识** | **高度对齐**,少量可改进项 | "确定性脚手架 + 局部嵌入 LLM"正是 12-Factor Agents 总结的存活模式;本仓的 typed state / Protocol 边界 / harness 闭环全部踩在共识上 |

核心判断:**这两项技术都是"互操作层"协议,而本系统当前的痛点在"业务正确性与评估闭环",不在互操作。** 在没有第二个消费方(另一个 agent 框架/另一个团队的 agent)出现之前,引入它们是为不存在的问题付维护税。

---

## 1. 现状盘点:被评估对象长什么样

DSL v2 迁移后的架构(2026-08):

```
企微 → FastAPI(Dify 兼容协议)
        └─ LangGraph 主图(单进程,AgentState 共享 TypedDict)
             ingest → [前置分流: 快速询价/存量兼容] → pre_route → intent_route(规则层+LLM兜底)
             → swap/option/close 子图(LLM 提取节点 + 确定性前后处理)
             → persist → render
        后端边界:OptionClient / SwapClient / TickerClient / GoatsAgentClient
                  (4 个 Protocol + Httpx 实现,Pydantic ReqVO 与 Java DTO 1:1)
        评测:harness(仅 import build_main_graph)+ langfuse_eval(DeepSeek Judge)
        部署:客户私有化(离线 wheel + docker save,单体进程 + MySQL)
```

与评估相关的 6 个既成事实:

1. **后端调用不经过 LLM 决策**:除 ticker resolver 内的 GOATS 校验外,所有后端调用都是图节点里的确定性代码调用(节点身份决定 operate 类型),不是 create_agent 式"LLM 从工具箱里挑"
2. **类型边界是 Pydantic ↔ Java DTO 1:1**(项目 P0 纪律),`extra="allow"` 兼容演进
3. **harness 的 mock 策略建立在 Protocol 上**:测试塞 FakeClient / patch 使用点,零网络、毫秒级
4. **私有化部署约束**:客户现场离线环境,部署单元越少越好(单体 + MySQL 已是极简)
5. **P95 延迟敏感**(长提示词已是主要延迟源,刚做完瘦身)
6. **确定性化是本仓的演进方向**:ticker ReAct→resolver 管线、5 个订单号节点去 LLM 化、规则层路由——都在把"能确定性做的事从 LLM 手里拿回来"

---

## 2. 议题一:FastMCP 封装 GOATS 后端

### 2.1 MCP 在 2026 年的定位(研究结论)

生态共识:MCP 的价值在**跨框架/跨宿主的工具共享**——"当工具需要被多个 agent 或框架复用、不同团队各自维护工具并希望解耦部署、或需要模型可移植性时用 MCP;单 agent + 自有 Python 函数时用原生工具"。工程上 MCP 每次调用增加 5-50ms 开销;生产级 MCP 服务器需要健康检查、优雅退出、进程管理——"本机能跑"到"生产能跑"之间是多数 FastMCP 项目搁浅的地方;端用户鉴权透传是公认痛点(FastMCP 3.0 的 OAuth 也只是缓解)。

### 2.2 对照三准绳逐条评估

**可维护性 —— 变差:**

- 现在:改一个后端字段 = 改一个 Pydantic ReqVO(mypy 全链路检查)。MCP 化后 = 改 MCP server 的 tool schema + client 侧适配 + 重新生成/校验 JSON Schema,**类型保真从 Pydantic 降级为 JSON Schema**(Decimal/枚举/嵌套 VO 的精度语义都要手工守护)
- 新增一个**独立部署单元**(MCP server 进程):客户离线环境的 wheel 打包、docker save、健康检查、日志、版本对齐全套翻倍;而它包裹的只是同机房的 4 个 HTTP 客户端
- GOATS 的 md5-16 签名/HMAC 双鉴权方案要在 MCP server 内再实现一层透传——正是社区公认的"significant time debugging auth flows"

**简洁性 —— 变差:**

- 调用链从 `节点 → Protocol → Java` 变成 `节点 → MCP client → (stdio/HTTP) → MCP server → Java`,多两跳序列化;每单 5-50ms × 多次后端调用,叠加在已经敏感的 P95 上
- 本系统的后端调用是**流程中的固定步骤**,不是"agent 探索性选工具"——MCP 的 tool discovery/progressive disclosure 能力全部用不上,属于为不使用的能力付复杂度

**harness 契合 —— 明显变差(最重的一票):**

- 现在 mock 一个后端 = `monkeypatch` 一个 Protocol(一行);MCP 化后要么起 mock MCP server(测试变慢、引入进程管理),要么 mock MCP client(那 MCP 层本身就没被测到)
- harness 的"business 子图 → 真 client → mock_api 全链路"验证模式、dry_run_backend 写类拦截(shadow 双跑安全阀)都实现在 Protocol 层——MCP 化需要整套重建

### 2.3 什么时候值得重新评估(触发条件)

以下任一成立时,MCP 封装从"维护税"变成"投资":

1. **出现第二个消费方**:公司内其他 agent/工具(IDE 助手、运营 Copilot、另一条业务线)也要调 GOATS/OTC 接口——此时 MCP 让接口"一次封装,处处可用"
2. **后端团队愿意自己维护 MCP server**:接口 owner 换人,类型契约的维护责任转移到接口提供方(这正是"不同团队各自维护工具"的 MCP 甜点区)
3. **需要把 otc-agent 自身的能力暴露出去**:反向场景——把"标的识别""询价"作为 MCP server 供人类桌面端(Claude/IDE)使用,这是**窄且低风险**的切入点,不动交易主链路

### 2.4 可选的窄场景(如果想练手 MCP)

若业务上想引入 MCP 积累经验,建议从**只读运维工具**开始:把 `canary_status.py`/`metrics_snapshot.py`/`llm_cost_report.py` 这类运维脚本用 FastMCP 包成 ops MCP server 给内部使用。零交易风险、不进主链路、不影响 harness,失败可随时扔掉。

---

## 3. 议题二:A2A 多 Agent 协同

### 3.1 A2A 在 2026 年的定位(研究结论)

A2A 捐入 Linux Foundation 一年,150+ 组织支持,进入 Google/Microsoft/AWS 平台,金融/保险/供应链有生产部署;LangGraph、CrewAI 已有原生支持——**不同技术栈的 agent 可以互相委派子任务而不共享内部记忆**。它的适用前提写在定义里:存在**多个独立运行时/独立团队维护的 agent** 需要标准化互操作。

### 3.2 对照现状:协同的"多 Agent"在哪里?

本系统的"多 Agent"是**同进程内的 LangGraph 子图**(swap/option/close/ticker),它们:

- 共享同一个 `AgentState`(typed、可检视——这正是生产实践强调的"state 是产品架构")
- 通过函数调用与 conditional edges 协同,**零网络跳数、零序列化、事务性 checkpoint 一致**
- 由同一团队维护、同一 harness 评估、同一进程部署

把它们拆成 A2A 互联的独立 agent,会得到:每跳一次网络与鉴权、分布式状态一致性问题(checkpoint 从单 MySQL 事务变成跨 agent 对账)、harness 从"ainvoke 一张图"变成"编排 N 个服务"、客户离线部署从 1 个单元变 N 个。**换回的互操作能力没有消费者。** 这与 2026 生产共识直接冲突:"最好的多 agent 系统通常是能产生可测量优势的最小系统;专家分工不能改善质量/延迟/覆盖/安全时,它们只是额外的故障面"。

### 3.3 触发条件(什么时候 A2A 变得有意义)

1. **第二个独立 agent 真实出现**:如风控审批 agent(合规团队维护,独立技术栈)、行情研究 agent、客户自建 agent 要与 otc-agent 互相委派任务——跨团队/跨栈边界出现时,A2A 是正确的标准化选择(优于自造 HTTP 协议)
2. **客户要求 agent 生态接入**:客户侧已有 A2A 网关/agent 注册中心,要求 otc-agent 以 A2A server 形式注册——那时用 LangGraph 的原生 A2A 支持暴露 **一个** 入口(整个主图作为单一 agent 卡片),而不是把内部子图拆开
3. 注意 **MCP 与 A2A 互补而非二选一**:届时"工具层用 MCP、agent 间用 A2A"的分层是生态主流画法——但两者都等真实边界出现再上

### 3.4 现在就该做的"多 Agent 卫生"(零成本预备)

不引入协议,但保持"未来可拆"的架构纪律(本仓已基本做到):

- 子图入口只依赖 `AgentState` 的声明字段(已是);子图不互相 import 内部实现(已是)
- 后端调用统一走 Protocol(已是)——未来任一子图拆出去,它的边界天然清晰
- 唯一建议:**主图入口的 Dify 兼容协议之外,预留一个"能力描述"文档**(agent card 的前身),把"本 agent 接受什么输入/产出什么"用一页说清——这页文档无论未来走 A2A 还是别的协议都要用

---

## 4. 对照 2026 最新实践的架构体检

| 2026 生产共识 | 本仓现状 | 评价 |
|---|---|---|
| "确定性脚手架 + 局部嵌入 LLM"(12-Factor Agents:自主循环式 agent 在生产存活率极低) | 规则层路由、确定性订单号提取、ticker resolver 管线、前后处理清洗;LLM 只做真需要语义理解的提取/分类 | ✅ **正是共识形态**;近期"去 LLM 化"演进方向正确 |
| Own your prompts / context / control flow / state | 提示词文件化 + 版本灰度 + 瘦身治理;控制流全在 graph 代码;TypedDict state 单一真源 | ✅ 对齐;提示词治理(错例转 golden)领先于多数团队 |
| "State 是产品架构,要 typed、minimal、inspectable" | AgentState 按业务对象聚合 + reducer 明确 + trace 全链路 | ✅ 对齐 |
| 最小多 agent 原则(专家分工必须换来可测量优势) | 子图按产品域分工,共享 state,无多余 agent | ✅ 对齐;**不要为"多 Agent"而多 Agent** |
| 评估驱动(eval loop 是第一公民) | harness + golden 三桶 + DeepSeek Judge + 按桶退出门 | ✅ 对齐,且是本仓最大资产——**一切架构变更先问"harness 怎么测"是正确的反射** |
| 可观测(node 级 trace + 成本监控) | TraceEntry + LangFuse + Prometheus + 成本报表 | ✅ 对齐 |
| HITL 在关键决策点 | 确认类意图二段式(业务层实现)+ interrupt 机制预留(ADR 0006 未启用) | 🟡 够用;若上 interrupt v2/durable execution 需求(如下单前强制人工卡点),LangGraph 1.x 原生能力现成,属增量启用而非重构 |
| Checkpointer 规模化(高吞吐场景 Redis 化) | MySQL(AIOMySQLSaver),企微群消息量级 | 🟡 当前量级 MySQL 足够;100K req/h 级别才需要重新评估——离该量级很远,不动 |

**结论:当前架构不需要为"新"而动。** 下一步的价值洼地仍在既定路线上:真后端联调跑通(复活地图 #127)、提示词 P1b/P2 瘦身、golden 扩充——而不是引入互操作协议。

---

## 5. 建议路线

**短期(0-3 个月)——零协议引入:**

1. 维持 Protocol 边界纪律(新后端接口一律 Protocol + Pydantic,这是未来任何 MCP/A2A 化的天然接缝)
2. 写一页 otc-agent 能力描述文档(输入/输出/意图清单),作为未来 agent card 的种子
3. (可选,练手)ops 只读脚本 FastMCP 化,内部使用,不进主链路

**触发式决策表(把"要不要上"变成客观判断):**

| 信号 | 动作 |
|---|---|
| 公司内出现第 2 个要调 GOATS/OTC 的 agent/工具 | 启动 MCP 封装评估,由接口 owner 团队维护 server |
| 客户/生态出现独立 agent 要与 otc-agent 互操作 | 用 LangGraph 原生 A2A 支持,把**整个主图**作为单一 agent 暴露 |
| 后端团队接手接口契约维护 | MCP server 交给他们,本仓退化为 MCP client |
| 吞吐接近 10K+ req/h 且 checkpoint 成为瓶颈 | 评估 Redis checkpointer / LangGraph Platform |
| 下单确认需要强制人工卡点(合规要求) | 启用 LangGraph interrupt(ADR 0006 路径),不引入外部协议 |

**反模式警示(评估中明确排除的选项):**

- ❌ 把 swap/option/close 子图拆成 A2A 互联的独立服务——违反最小多 agent 原则,摧毁 harness 与离线部署简洁性
- ❌ 把交易写类接口(下单/撤单)裹进 MCP 给 LLM 自由调用——本仓刚把"LLM 决定何时调后端"收敛为"节点身份决定",不能开倒车
- ❌ 为协议对齐重写 Protocol 层——4 个 Protocol 就是本系统的"接口稳定层",它比任何外部协议都先属于我们自己

---

## Sources

- [LangGraph in Production: Choosing and Building Multi-Agent Systems](https://subratpati.medium.com/langgraph-in-production-choosing-and-building-multi-agent-systems-c2b955f16429)
- [LangGraph Multi Agent Systems — Patterns That Work in Production](https://123ofai.com/articles/blogs/langgraph-multi-agent)
- [LangGraph Multi-Agent Architecture: State Control at 100K Requests/Hour](https://markaicode.com/architecture/langgraph-multi-agent-architecture/)
- [MCP vs Traditional API Calls in Production](https://bytebridge.medium.com/mcp-vs-traditional-api-calls-in-production-promises-pitfalls-and-proper-use-e0550c4b8065)
- [Build MCP in Python: FastMCP vs FastAPI-MCP vs Python SDK](https://mcp.directory/blog/fastmcp-vs-fastapi-mcp-vs-python-sdk-2026)
- [MCP server ecosystem: what's production-ready in 2026?](https://simorconsulting.com/blog/mcp-server-ecosystem-whats-production-ready-in-2026/)
- [7 FastMCP mistakes that break your agent in production](https://www.channel.tel/blog/fastmcp-7-mistakes-break-agent-production)
- [MCP vs LangChain Tools: When to Use Each (2026)](https://www.getknit.dev/blog/integrating-mcp-with-popular-frameworks-langchain-openagents)
- [langchain-mcp-adapters (GitHub)](https://github.com/langchain-ai/langchain-mcp-adapters)
- [A2A Protocol Surpasses 150 Organizations…First Year (Linux Foundation)](https://www.linuxfoundation.org/press/a2a-protocol-surpasses-150-organizations-lands-in-major-cloud-platforms-and-sees-enterprise-production-use-in-first-year)
- [Linux Foundation A2A Protocol Marks One Year (AIwire)](https://www.hpcwire.com/aiwire/2026/04/09/linux-foundation-a2a-protocol-marks-one-year-with-broad-enterprise-and-cloud-adoption/)
- [A2A Protocol Adoption: Where Things Stand in Mid-2026](https://agentndx.ai/blog/a2a-protocol-adoption-mid-2026/)
- [The 12-Factor Agents Guide](https://zenn.dev/babushkai/articles/2026-01-20-12-factor-agents?locale=en)
- [12-Factor Agents: A Framework for Building AI Systems That Actually Ship](https://tianpan.co/blog/2026-01-26-12-factor-agents-production-ai)
