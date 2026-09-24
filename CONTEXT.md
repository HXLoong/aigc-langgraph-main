# otc-agent · Domain Context

场外衍生品 AI 指令助手（OTC Derivatives AI Instruction Agent）的领域语言、术语表和概念边界。
所有 issue / PRD / refactor 提案 / 测试命名都使用本文件定义的术语，不漂移到同义词。

## Language

### Engineering 术语

**联调修复优先级**：
用于开发与真后端联调阶段裁决失败项是否必须先修的优先级，不等同于 ADR 0019 的生产事故等级。P0 表示阻断全部联调；P1 表示阻断可靠验证；P2 表示不阻断当前重构任务，可带红推进。
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
一套把 "case → 跑 LangGraph → 比对预期 → 结构化输出失败原因 → 喂给 AI 编码工具改代码 → 再跑" 做成闭环的工具链。三层粒度：HTTP 端到端回归（业务验收集）、意图子链（意图集）、节点级回归（节点 fixture 已退役，ADR 0029 仅保留 `app/node_execution` 节点调试 API）；配结构化 diff 报告与 CLI（`harness/README.md`）。
_Avoid_: 混沌工程（Chaos Engineering，不同概念）、可观测性平台（trace 只是 harness 的副产品之一）、单元测试（harness 跑的是数据集而非代码单元）

**Golden case**：
一条 harness 输入：用户原话 + 期望输出。集合（golden set）是 harness 的回归基线；业务验收集 `tests/fixtures/biz/` 以 Java 卡片文本断言为主、可选结构化 `expected`，意图集 `tests/fixtures/intent/` 逐轮断言 product_type / intent。按来源分三个桶（目标口径；当前 biz 与 intent 未标注桶，B 方言历史参考集 `unified_golden.jsonl` 已退役）：
- **B 桶**：业务方手写种子——主动构造、意图均衡的典型句式，expected 字段由业务方直接填写
- **C 桶**：LLM paraphrase——以 B 桶为种子做对抗式改写（换说法 / 边界 case），业务方 review pass 后合入
- **D 桶**：客户历史真实输入——从企微群抄录的原话，反映真实分布（含拼写错误、缩写、上下文依赖）；expected 字段**必须由业务方人工标注后才能合入**数据集，是持续增长的集合

各桶目标 PASS 率：B ≥ 90% / C ≥ 80% / D 无硬性阈值（补充参考）。现行评测门以 ADR 0030 D3 为准。
_Avoid_: 测试用例（太泛）、fixture（语义不准）、anchor case（请用"B 桶代表性 case"代替）

**Shadow compare（双跑对照）**：
同一条 case 同时打到 Dify 和 LangGraph，diff 输出找差异（`scripts/shadow_compare.py`）。是**可选的辅助参考工具**，**不是合格性判定的标准**——Dify 输出本身有已知缺陷，不能作为 ground truth；合格性以 **Golden case PASS 率**为准。实际用途是切流前给业务方提供两边输出对比作为决策辅助。
_Avoid_: A/B test（语义不准，不涉及流量切分）；ground truth 验证（Dify 不是 ground truth）

**Ground truth（合格性判定标准）**：
Golden case 的 expected 字段。LangGraph 输出与 expected 一致 = PASS；不一致 = FAIL。评测门基于 PASS 率（ADR 0030 D3），不基于 shadow diff 率。
_Avoid_: 拿 Dify 输出当 ground truth（Dify 是参考竞品而非真理）

**节点（Node）**：
图中的一个可独立执行、记录状态和追踪结果的步骤，可以承担识别、确定性处理或后端调用。节点划分以当前职责为准，不要求与历史 Dify 节点一一对应。
_Avoid_: step（太泛）、stage、handler

**LangFuse**：
本项目 Harness 的后台服务（self-hosted 部署在内网）。承载 trace / dataset / eval / annotation 四件套。**不**承载提示词的真理来源——`app/prompts/**/*.md` 是真理来源，LangFuse Prompts 仅作 staging 演练区。
_Avoid_: LangSmith（数据出境，已废止）、可观测性平台（窄了，LangFuse 还做评估和标注）

### 业务术语

**消息轮次**：
从收到一条用户消息到完成该条消息回复的一次处理；该消息引用的历史、附件和同一动作下的多笔订单都属于这一轮。用户随后发送的确认或补充消息属于新一轮，同一会话可以包含多轮。
_Avoid_: 把一笔订单、一张附件或一个处理分支各算一轮；把完整多轮验收场景算作一轮

**意图（Intent）**：
用户原话在业务产品内对应的具体动作，如询价、申请下单、确认下单、撤单或查询。意图以产品 `product_type`（swap / option / option_close）为范围，产品与意图可联合判定；产品路由与整个工作流的入口路由是两个层次。
_Avoid_: action（与下单 algorithm type 的 "action" 字段冲突）、type（太泛）

**入口路由**：
将输入分为快速询价、存量指令查询、LLM 指令三类。LLM 指令分支按既有优先级选择一个产品和一个业务动作，不再进行多动作编排。
_Avoid_: 将产品分类或已退出的多指令编排称为额外的一级入口分支

**单业务动作**：
一条消息只采用一个业务动作，该业务分支识别到的多笔订单共用这个动作。订单数量可以多于一笔，动作数量仍为一个；混合措辞也不再按分句为订单分配不同动作。例如识别为撤单申请后，识别到的 A、B 两笔订单均按撤单申请处理。各订单的权限、状态与最终确认要求继续适用。
_Avoid_: 将多个订单等同于多个动作；识别到订单就视为交易已确认或已完成

**标的（Ticker / Instrument）**：
交易指令指向的证券、基金、期货等交易对象。输入表达可以是用户原始名称、代码或月份描述，标准代码及可交易性由 Java 权威识别。用户原文与引用候选选择本身不等于 GOATS 已验证的标的。
_Avoid_: stock（仅指股票）、symbol（不准确）、underlying（仅期权语境）

**标的表达**：
用户原话或引用消息中的证券名称、代码或月份表达；它是识别输入，不等同于已经校验的标的。
_Avoid_: 把提取到的名称或引用候选直接当作后端已校验结果

**确认动作（expected_action）**：
写动作二次确认时期望用户确认的动作，写入 AgentState 顶层 `expected_action`（`place` / `modify` / `cancel` / `inquiry` / `close`，ADR 0024 D2）。互换的确认由同一个 `swap_confirm` 节点处理下单 / 撤单 / 改单三种动作，动作由 intent 推导（`_expected_action`）。
_Avoid_: 三个独立的"确认下单 / 确认撤单 / 确认改单"节点（已合并）

**文本二阶段确认**：
写动作先回复待确认卡片，用户下一条消息明确确认具体动作并引用当前订单后才提交（ADR 0021）。七条最终确认路径的范围校验统一在 `app/domain/confirmation.py`；`last_confirmed_params` 只作上下文，不能替代用户引用。
_Avoid_: interrupt 确认（已不用）、把历史记忆里的订单当作本轮确认对象

**快速询价 / 存量指令**：
入口路由的两个前置分支。快速询价由请求标志 `fast_query=1` 决定，走 GOATS 解析后以 `optionRfq` 提交；存量指令走 GOATS `instruction/query` 做存量兼容查询。文本里出现"雪球""快速询价"等词不改变入口。
_Avoid_: 按关键词判断是否快速询价

**交易对手（Counterparty）**：
互换指令里的交易对手方。LangGraph 从授权对手列表中识别用户表达或引用选择（`swap_select_counterparty` / `swap_recognize_fresh_counterparty`），不自行扩充对手清单。
_Avoid_: 客户（太泛）、用户（指发消息的人）

**字段证据 / 字段锁定**：
模型只产原文候选（`FieldCandidate`，含 evidence / confidence / source），Code 归一化后记为 `FieldRecord` 并按来源锁定；交易最终值不由模型直接决定（ADR 0027，`app/extraction/`）。
_Avoid_: 让模型直接输出最终下单参数

**请求幂等 / 不确定回执 / 对账**：
同一 `message_id` 的请求只执行一次；写后端超时等无法确认结果时记为不确定回执，由运维对账核实 Java 原始回复后落库，写接口绝不自动重试（ADR 0026，`app/api/idempotency.py` / `reconciliation.py`）。
_Avoid_: 超时后重发写请求、把不确定结果当失败或成功

**业务拒绝（REJECTED）**：
后端或业务规则如实拒绝了指令（如数量非正、无权限）。评测里单独成桶，不计入 PASS 也不算代码 FAIL（ADR 0024 D6）。
_Avoid_: 把拒绝改写成成功卡片，或把拒绝当作 LangGraph 缺陷

**意图集 / 冻结上下文 / 回放**：
意图集（`tests/fixtures/intent/`）只评产品与意图，不依赖 Java。冻结用例把每轮上下文写在 fixture 里、只跑意图子链；走主图 + `mock_api` 的是拒绝验收用例和引用上一轮真实回复的回放用例（当前多轮用例已全部冻结，`harness/intent_context.py` 判定）。
_Avoid_: 把意图集与依赖 Java 的业务验收集混跑

**节点级 fixture（已退役）**：
节点级 fixture 已随 ADR 0029 的 fixture 部分退役；节点级调试改由 `app/node_execution` 的单节点执行 API 承担。
_Avoid_: 用节点 fixture 代替端到端业务验收

### 运维与评测术语

**Context-dependent case（上下文依赖 case）**：
golden case 中，正确的 product_type 或 intent 只有在已知多轮对话历史时才能确定的一类 case（如裸"撤单"/"确认下单"）。
单轮 case 不携带对话历史，这类场景必须写成多轮 case（`sub_scenes` / `conversation`），由 harness 按轮次依次请求；单轮写法下的失败不作为 pass rate 的改进目标。
_Avoid_: 把这类失败归因于"节点 bug"（根因是测试环境缺少对话历史，不是节点逻辑错误）

**紧急回滚（Emergency Rollback）**：
出现 P0 故障时，把企微群消息重新路由回 Dify 的操作：由客户侧 Java 配置管理员把 Java 侧 `agentUrl` 从 LangGraph 改回 Dify（ADR 0001），企微入口与 LangGraph 代码都不动；服务侧善后（清空 `CANARY_ROOM_IDS`、审计记录）由 `scripts/rollback_canary.sh` 完成。具体操作步骤以 `docs/operations/on-call-runbook.md` §7 为准。
_Avoid_: "应用层特性开关"（需要改代码或重启才生效的方案）

**金丝雀切流（Canary Rollout）**：
按**群组**逐步把企微群从 Dify 切到 LangGraph 的过程，切换动作同样是改 Java 侧 `agentUrl`（能否按群配置在部署前环境调研中核实）。分三阶段：测试群（1-2 个）→ 更多测试群（~30% 群组）→ 全量；服务侧用 `CANARY_ROOM_IDS` 白名单标记已切群（`ALL` 表示全量），非白名单流量触发 `non_canary_traffic` P0 告警。不需要代码部署，故障影响范围天然隔离到已切群组。
_Avoid_: "按流量百分比分发"（企微不支持单群内流量分流）、"按会话 ID 哈希"（需要分流代理层，不必要）

## Relationships

- 一份 **Golden case** 既被 **Harness** 用作回归基线，也可被 **Shadow compare** 用作双跑输入
- **Harness** 的失败报告会指向具体的 **节点（Node）**，让 AI 工具知道改哪里
- 用户原话先经 **入口路由** 分流；LLM 指令分支内按 **product_type** 和 **意图（Intent）** 处理
- LangGraph 保留 **标的** 原文及用户引用选择，Java 负责权威识别与校验；空 `tickers` 兼容字段不表示零命中，原文不标记为 `from_goats=True`。职责见 [标的识别后端边界](docs/architecture/backend-instrument-boundary.md)
- LangGraph 经 `app/tools/` 的 Client Protocol 调用外部系统：OptionClient / SwapClient（Java 业务）、MessageClient（意图写回）、GoatsAgentClient（快速询价 / 存量指令）；TickerClient 只供本地验收脚本拉授权对手列表。Java 契约见 `docs/api-contracts/java-backend.md`
- 业务卡片与订单执行结果来自 Java 后端，原始回执是业务核查依据。
