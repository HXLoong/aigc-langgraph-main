# otc-agent 架构成熟度体检:对照 LangGraph 生产最佳实践

> 编写:图灵科技 · 2026-08-28 · 基于分支 `feature/dify-dsl-migration`(DSL v2 迁移后)
> 评估准绳:**可维护 / 简洁 / harness 契合 / 按时交付客户**
> 姊妹篇:[architecture-review-2026-08.md](./architecture-review-2026-08.md)(FastMCP/A2A 引入决策,结论:均暂缓)
> 本篇:全面对照成熟实践的体检 + 交付风险清单。研究出处见文末 Sources。

---

## 0. 执行摘要

**总体评级:健康,可按时交付。** 架构形态("确定性脚手架 + 局部嵌入 LLM"、typed state、Protocol 边界、评估闭环)与 2026 生产共识高度一致;工程度量全绿(零超限文件、测试:业务代码 1.46:1)。体检发现 **4 个具体改进点**,其中 2 个与客户现场长期运行直接相关(checkpoint 表无 TTL 清理、trace 携带 LLM 输出的膨胀风险),都是小改动,不构成交付阻塞。**交付的真正风险不在架构,在环境与决策依赖**(VPN/schema/业务拍板),已在复活地图 #127 上追踪。

## 1. 工程度量快照

| 度量 | 数值 | 评价 |
|---|---|---|
| 业务代码(app/) | 11,187 行 / 90 文件 | 单体可读;最大文件 592 行,**零超 800 行红线** |
| 测试代码 | 16,289 行 / 144 文件(1084 用例绿) | 测试:业务 = 1.46:1,行覆盖 82% |
| 评测台(harness/) | 1,963 行,仅 import `build_main_graph` | 解耦干净——架构变更的"守门员" |
| 图节点总数 | 39(主图 11 + 三业务子图 28) | 与 DSL v2 蓝图一致,无冗余节点 |
| 后端边界 | 4 个 Protocol(option/swap/ticker/goats_agent) | 类型契约 Java DTO 1:1 |
| 提示词资产 | 154K 字符(瘦身 v2 灰度中,-19% 待放量) | 治理机制已建(灰度+处置表+评估门) |
| 部署单元 | 1 进程 + MySQL(+ 可选 LangFuse) | 客户离线私有化的最简形态 |

## 2. 成熟实践对照体检(13 项)

| # | 成熟实践(2026 共识) | 本仓现状 | 判定 |
|---|---|---|---|
| 1 | State 小而 typed、accumulator 用 reducer、当前值用覆盖型 | `AgentState` 按业务对象聚合;`trace/history_messages` 用 `Annotated[list, add]`,其余覆盖型——教科书用法 | ✅ |
| 2 | 条件边只放在真实决策点,能简单就简单 | 一级路由 + 各子图 intent 分发 + cascade 守卫,无装饰性分支 | ✅ |
| 3 | 节点/图/应用三层错误处理 + 优雅降级 | `@safe_node`(节点)→ cascade 路由(图)→ fallback render + `default_reply`(应用);错误如实透传(P0 纪律) | ✅ |
| 4 | 结构化输出不手工解析 | 全部 `with_structured_output(Pydantic)`,失败重试 1 次 + safe_node 兜底 | ✅ |
| 5 | Own prompts/context/control flow/state | 提示词文件化+版本灰度+瘦身治理;控制流全在图代码 | ✅ |
| 6 | 评估驱动为第一公民 | harness + golden 三桶 + Judge 评估 + 按桶退出门 | ✅ **最大资产** |
| 7 | 可观测:节点级 trace + 成本 + 告警 | TraceEntry 全链路 + LangFuse + Prometheus + 成本报表 + P95 告警 | ✅ |
| 8 | 瞬态失败用 RetryPolicy;**写类操作不可盲目重试** | 节点级 RetryPolicy 0 处;写类(下单/撤单)无自动重试 | ✅*(见 2.1:写类不重试是**正确纪律**;读类可选加) |
| 9 | 每次 invoke 设 recursion_limit 防环 | **零处显式设置**(CLAUDE.md 有指引未落地);现图均为 DAG 无环,风险低 | 🟡 改进点 A |
| 10 | checkpoint 表增长治理(TTL/夜间清理) | **无清理机制**——客户现场长期运行 MySQL checkpoint 表只增不减 | 🟡 改进点 B(交付相关) |
| 11 | state 保持精瘦,勿把原始 LLM 响应塞进 checkpoint | `trace[].llm_output` 19 处写入完整 LLM 输出 dict——多轮长会话下每 checkpoint 携带全部历史 trace | 🟡 改进点 C(交付相关) |
| 12 | 流式按 UX 需要有意识选择 | 企微是整条消息回复,blocking 模式正确,**不需要**token 流式 | ✅(有意识不用) |
| 13 | HITL 在关键卡点 | 确认类二段式(业务层);interrupt 预留未启用(合规要求出现再增量启用) | ✅ 够用 |

### 2.1 关于重试的澄清(体检项 8)

后端 operate 类接口(下单/撤单/确认)的幂等性由 Java 侧 5 秒幂等锁保证,但重复提交仍会被 dedup 拒绝并产生"请勿重复提交"回复——**节点级自动重试写类调用会把网络抖动放大成用户可见的混乱**。当前"失败→cascade→友好降级+如实透传"是金融场景的正确选择。可选优化:仅对**读类**调用(查单/持仓/GOATS select)加 `RetryPolicy(retry_on=BackendUnreachableError, max_attempts=2)`,写类明确排除——收益是联调期网络抖动下少一些误报,非交付必需。

## 3. 简洁性审计:哪里还能更简

刻意找了三轮,可简化项很少(这本身是好信号):

1. **`app/graphs/main_graph.py` 兼容 shim** —— ~~可删~~ 已删(4 处引用迁至 `app/graph/main`)
2. ~~`app/state.py` shim~~ 勘误:该文件承载 `make_initial_state`/`WechatInput`,非纯 shim,保留
3. **swap 多模态链与文本链的字段规范重复** —— 已在提示词瘦身 P2 方案中(共享字段规范拆分),按既定门槛推进,不新增计划
4. **不建议再简的**:39 个节点各有业务职责;4 个 Protocol 是接口稳定层;三层测试金字塔是交付信心来源——这些"体积"都在产出价值

## 4. 交付视角:按时交付的架构风险清单

交付定义(复活地图 #127):真实 Java 后端上走通 ≥5 条业务流(swap 2 + option 2 + close 1),先本地 `aigc/api` 后客户环境。

| 风险 | 性质 | 缓解 | 阻塞交付? |
|---|---|---|---|
| VPN/schema/对接人未恢复 | **环境依赖,非架构** | 地图 #134/#136 追踪,唯一关键路径 | **是——最大风险** |
| golden 基线与 DSL v2 意图集漂移(option 7 意图/新增节点无 case) | 评估有效性 | 交付验收前重基线:按新意图补 case + 全量 eval 一轮(地图 #131 清单即种子) | 否,但影响"验收有据" |
| checkpoint 表无限增长(改进点 B) | 客户现场运维 | 交付包内附清理脚本/事件(如保留 30 天),写入 on-call runbook | 否,交付前 1 天工作量 |
| trace 携带 LLM 输出膨胀(改进点 C) | 长会话性能 | trace 写入截断(llm_output 摘要化或长度上限),不改 schema | 否,半天工作量 |
| recursion_limit 未显式设置(改进点 A) | 防御纵深 | `routes.py` ainvoke config 加一行(如 50) | 否,10 分钟 |
| 范围蔓延(新协议/新框架诱惑) | 交付纪律 | 姊妹篇已裁决:MCP/A2A 暂缓;瘦身 P1b/P2 门槛外不动主链路 | **纪律问题,已立规** |

**交付前行动清单(架构侧,合计 ≤2 人日):**

1. [10 分钟] `routes.py` 的 `graph.ainvoke` config 显式加 `recursion_limit`
2. [半天] TraceEntry 的 `llm_output` 写入截断策略(保留决策要素,截长文本)
3. [1 天] checkpoint 清理脚本(按 thread 时间保留 N 天)+ runbook 条目 + 交付包收录
4. [并行] golden 重基线计划:7 个新 option 意图 + swap 多模态/选择链 + close 引用链各补 case(种子在地图 #131 验收清单)

其余一切架构工作(瘦身 P1b/P2、MCP 练手、interrupt 启用)**押到交付之后**——按时交付的最大架构贡献是"不动"。

## 5. 结论

对照成熟实践,本架构的判定是:**该有的都有,不该有的没有。** 13 项体检 10 项达标、3 项小改进(合计 ≤2 人日);简洁性上主动可简化项仅两个 shim 文件;harness 契合是全仓最强项,也是交付信心的来源。按时交付的路径清晰:环境依赖(VPN/schema)是唯一关键路径,架构侧只需完成 4 项小清单并保持"不动主链路"的纪律。

---

## Sources

- [LangGraph State Management: Checkpointing & Recovery](https://activewizards.com/blog/langgraph-state-management-checkpointing-recovery-and-the-persistence-layer-decision/)
- [LangGraph Agent Error Handling in Production](https://focused.io/lab/langgraph-agent-error-handling-production)
- [LangGraph State: Checkpoints, Threads, and Recovery](https://eastondev.com/blog/en/posts/ai/20260424-langgraph-agent-architecture/)
- [LangGraph Best Practices](https://www.swarnendu.de/blog/langgraph-best-practices/)
- [LangGraph Production Configuration: 5 Patterns That Scale](https://markaicode.com/best/best-langgraph-configuration-production-guide/)
- [LangGraph in Production: StateGraph & Patterns for Real Agents](https://www.kalviumlabs.ai/blog/langgraph-in-production-stateful-multi-step-agents/)
- [The 12-Factor Agents Guide](https://zenn.dev/babushkai/articles/2026-01-20-12-factor-agents?locale=en)
- [LangGraph Multi Agent Systems — Patterns That Work in Production](https://123ofai.com/articles/blogs/langgraph-multi-agent)
- 另见姊妹篇 [architecture-review-2026-08.md](./architecture-review-2026-08.md) 的 14 篇 MCP/A2A 出处
