# otc-agent · Domain Context

场外衍生品 AI 指令助手（OTC Derivatives AI Instruction Agent）的领域语言、术语表和概念边界。
所有 issue / PRD / refactor 提案 / 测试命名都使用本文件定义的术语，不漂移到同义词。

## Language

### Engineering 术语

**联调修复优先级**：
用于开发与真后端联调阶段裁决失败项是否必须先修的优先级，不等同于 ADR 0019 的生产事故等级。P0 表示阻断全部联调；P1 表示阻断可靠验证；P2 表示不阻断当前里程碑，可带红推进。
_Avoid_: 用 ADR 0019 的 on-call P0/P1/P2 阈值给开发测试失败定级

**验收场景**：
真后端联调时作为一条业务流计数的端到端场景。一个验收场景可以包含多轮用户指令，并消费前序步骤产生的真实订单号、报价或持仓；计数单位是完整业务闭环，不是单条消息。
_Avoid_: 把一个多轮闭环中的每条用户指令分别计为一条业务流

**本地链路 PASS**：
GOATS 在开发机不可达时，验收场景仍完整经过 LangGraph 和真实 Java 业务代码，并由 Java 按真实 `integration_api_config` 实际尝试调用 GOATS；请求、集成日志和失败原因可核验，Java 与 LangGraph 如实表达失败，不伪造下单、撤单、成交或查询成功。GOATS 连接失败可以是预期结果；未进入正确业务分支、未发起 GOATS 请求、配置缺失、异常被吞掉或回复伪成功均为 FAIL。
_Avoid_: 本地业务交易 PASS、mock GOATS 成功、把“失败可观测”表述成“交易走通”

**业务交易 PASS**：
在可访问真实 GOATS 的客户环境中，验收场景获得 GOATS 的真实成功响应，且后续订单状态可以查询和追踪。它是业务闭环的最终验收，不由本地链路 PASS 替代。
_Avoid_: 仅凭 Java 已尝试调用 GOATS、集成日志存在或 mock 返回成功就宣称交易成功

**Harness（评测台 / Harness Engineering）**：
一套把 "case → 跑 LangGraph → 比对预期 → 结构化输出失败原因 → 喂给 AI 工具改代码 → 再跑" 做成全自动闭环的工具链。包含 golden set、replay 工具、结构化 diff 报告、可被 Claude Code 单命令调用的 CLI。
_Avoid_: 混沌工程（Chaos Engineering，不同概念）、可观测性平台（trace 只是 harness 的副产品之一）、单元测试（粒度更粗，跑端到端）

**Golden case**：
一条 harness 输入：用户原话 + 期望输出（intent / product_type / 关键参数）。集合（golden set）是 harness 的回归基线。按来源分四个桶：
- **B 桶**：业务方手写种子——主动构造、意图均衡的典型句式，expected 字段由业务方直接填写
- **C 桶**：LLM paraphrase——以 B 桶为种子做对抗式改写（换说法 / 边界 case），业务方 review pass 后合入
- **D 桶**：客户历史真实输入——从企微群抄录的原话，反映真实分布（含拼写错误、缩写、上下文依赖）；expected 字段**必须由业务方人工标注后才能合入** golden.jsonl，是持续增长的集合（M3 联调后持续补充，不是一次性交付物）
- ~~A 桶~~：历史企微日志抽样（暂搁，M3 shadow 阶段的线上流量会自然替代）

各桶退出门 PASS 率：B ≥ 90% / C ≥ 80% / D 无硬性阈值（样本量少，作为补充参考）。
_Avoid_: 测试用例（太泛）、fixture（语义不准）、anchor case（请用"B 桶代表性 case"代替）

**Shadow compare（双跑对照）**：
同一条 case 同时打到 Dify 和 LangGraph，diff 输出找差异。是 Dify→LangGraph 迁移期的**辅助参考工具**，**不是合格性判定的标准**——Dify 自己有"标的不准 / 参数 bug / 评估缺失"三大已知缺陷（迁移动机），不能作为 ground truth。LangGraph 是否合格的判定标准是 **Golden case PASS 率**，不是 shadow diff 率。Shadow 的实际用途是 M4 金丝雀切流前给业务方提供"Dify 与 LangGraph 在生产真实流量上的输出对比"作为决策辅助。
_Avoid_: A/B test（语义不准，不涉及流量切分）；ground truth 验证（Dify 不是 ground truth）

**Ground truth（合格性判定标准）**：
Golden case 的 expected 字段。LangGraph 输出与 expected 一致 = PASS；不一致 = FAIL。M3 退出门基于 PASS 率（≥ 阈值），不基于 shadow diff 率。
_Avoid_: 拿 Dify 输出当 ground truth（Dify 是参考竞品而非真理）

**节点（Node）**：
LangGraph 图中一个 `@safe_node` 装饰的 async 函数。在本项目语境下，节点和 Dify 的 LLM 节点 1:1 对齐（仅 3 个"确认 X"合并为 1）。
_Avoid_: step（太泛）、stage、handler

**LangFuse**：
本项目 Harness 的后台服务（self-hosted 部署在内网）。承载 trace / dataset / eval / annotation 四件套。**不**承载提示词的真理来源——`app/prompts/**/*.md` 是真理来源，LangFuse Prompts 仅作 staging 演练区。
_Avoid_: LangSmith（数据出境，已废止）、可观测性平台（窄了，LangFuse 还做评估和标注）

### 业务术语

**意图（Intent）**：
用户原话被识别后归类的二级动作，如 `place_order_request` / `cancel_order` / `query_order` / `close_position`。**一级路由是 product_type**（swap / option / close），二级才是 intent。
_Avoid_: action（与下单 algorithm type 的 "action" 字段冲突）、type（太泛）

**标的（Ticker / Instrument）**：
交易对象的唯一标识。在本项目内必须是经过 goats 库校验过的代码（`from_goats=True` 是绝对约束），不接受未经校验的字符串。
_Avoid_: stock（仅指股票）、symbol（不准确）、underlying（仅期权语境）

**Confirm 节点的 action 参数**：
合并版 `swap.confirm(action: "place" | "cancel" | "modify")`——同一个节点处理三种动作的二次确认，调用方传入 expected_action。
_Avoid_: 三个独立的"确认下单 / 确认撤单 / 确认改单"节点（已合并）

## Relationships

- 一份 **Golden case** 既被 **Harness** 用作回归基线，也可被 **Shadow compare** 用作双跑输入
- **Harness** 的失败报告会指向具体的 **节点（Node）**，让 AI 工具知道改哪里
- 一条用户原话先经一级路由到 **product_type**（swap / option / close），再由该子图内识别 **意图（Intent）**
- 任何 **标的** 出现在 LangGraph 输出前，必须经过 ticker 子图（ReAct Agent，4 个工具：tokenize / completeness / rank / infer_code）校验，最终输出 `from_goats=True`
- LangGraph 通过 3 个 **Protocol**（OptionClient / SwapClient / TickerClient）调用 Java 后端业务 API，契约定义见 `docs/api-contracts/java-backend.md`

**Context-dependent case（上下文依赖 case）**：
golden case 中，正确的 product_type 或 intent 只有在已知多轮对话历史时才能确定的一类 case（如裸"撤单"/"确认下单"）。
M2 / M3 阶段 harness runner 每条 case 独立跑，不注入 history_messages，这些 case 的失败属于**已知局限**，不作为 pass rate 的改进目标。M3 阶段靠真实流量 case（D 桶）自然补充。
_Avoid_: 把这类失败归因于"节点 bug"（根因是测试环境缺少对话历史，不是节点逻辑错误）

**紧急回滚（Emergency Rollback）**：
出现 P0 故障时，把企微群消息重新路由回 Dify 的操作。实现方式：企微管理员修改机器人的 Webhook 地址（LangGraph endpoint → Dify endpoint），约 1 分钟生效，无需 SSH 或重启服务。
_Avoid_: "流量层切换"（暗示需要 Nginx/网关操作）、"应用层特性开关"（需要重启）、"客户 IT 操作"（企微管理员即可完成）

**金丝雀切流（Canary Rollout）**：
M4 阶段按**群组**逐步把企微机器人 Webhook 从 Dify 切到 LangGraph 的过程（选项 B：按群组分配）。分三阶段：测试群（1-2 个）→ 更多测试群（~30% 群组）→ 全量。每阶段由企微管理员改 Webhook，不需要代码部署。故障影响范围天然隔离到已切群组。
_Avoid_: "按流量百分比分发"（企微不支持单群内流量分流）、"按会话 ID 哈希"（需要分流代理层，不必要）

## Flagged ambiguities

- 用户原话写"混沌工程"，英文写"Harness Engineering"——这两个**不是同一个概念**。本项目语境下统一指 **Harness**，混沌工程不在本项目范畴。
