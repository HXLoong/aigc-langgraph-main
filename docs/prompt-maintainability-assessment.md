# 提示词可维护性专题评估（全域）

> 编写：图灵科技 · 2026-09-15 · 分支 `claude/gallant-hopper-c7ju7v`
> 背景：客户反馈从 Dify 迁移过来的提示词"太臃肿、冗余多"。2026-08-28 的 `docs/swap-prompt-slimming-assessment.md` 只覆盖 swap 域；本报告把评估扩到 option / option_close / ticker / router 全域，并把重点从"内容"移到"代码迁移完成后提示词怎么管才易于维护"。
> 方法：动态工作流 7 路并行评估（5 个提示词域 + 治理层 + 代码-提示词契约）→ 每路独立对抗核证（只采信 confirmed / partial 的发现）→ 完整性批评。字符数口径：Python `len()`（Unicode 字符）；token 为估算（字符 ÷ 1.6，与 swap 报告同口径）。
> 决策落点：[ADR 0022](./adr/0022-prompt-governance-after-code-migration.md)。
> **2026-09-16 更新**：本报告落地的 manifest / prompt_inventory 治理机制已随 ADR 0022 废弃而全量移除（见 ADR 0022 废弃说明）；保留本文作为评估历史记录。

---

## 一、执行摘要

**结论一句话**：提示词"臃肿"是真的，但它是**症状**；病根是代码迁移完成后提示词仍按"Dify 镜像"管理——Dify 由工作流引擎渲染占位符、由 code 节点做前置分流，LangGraph 没有这两层，于是同一份原文搬过来后出现悬空规则、丢失分流、双份真源；而逐字锁定测试又让本地不能改。本次评估把重点放在**管理模型**上，先把"能改、改了有守护"的机制落地，内容瘦身按档推进。

**规模**：41 个 `.md`、system 段 48.4 万字符（≈30 万 tokens）；生产活跃 28 个 / 29.4 万字符。三条 3 万 tokens 以上的请求路径（互换图片下单 54K、平仓下单 37K、互换文本下单 36K）是延迟与成本主单点。

**核证后的发现总量**（7 路评估 + 逐路对抗核证，只采信 confirmed / partial）：

| 严重度 | 条数 | 其中本次已修 |
|---|---:|---:|
| P0 | 8（另 2 条经批评员裁决降为 P1） | 7（代码级 5 + 红线 2）；open 1（C-01 需业务确认改法） |
| P1 | 49 | 8（治理机制） |
| P2 | 45 | 6（文档口径） |

**P0 的共性**：全部是"迁移丢东西"而非"提示词写得差"——

1. **注入变量丢失**：`holding_query` 对手列表、`infer_code`/`rank` 当前日期在 Dify 由上游节点注入，迁移后占位符原样发给 LLM（OC-01 / TRJ-01，已修）
2. **前置分流丢失**：09-11 回归 Dify 原文时 `swap/intent.md` 删掉了 `confirm_order` 枚举（Dify 靠 code 节点前置分流），app 未移植 → 互换确认下单链路不可达（SW-INC-01 / GOV-02，已修）
3. **契约移交未同步**：09-11 版 `select_counterparty.md` 把简写唯一性交给代码，代码却按列表顺序取首项 → 多命中错配对手（SW-INC-06，已修）
4. **代码规则层与提示词矛盾**：`close/intent.py` 写入枚举外的值落 `close_unknown`（OC-02，已修）
5. **红线**：`dify/sync.py` 默认值里的内网账号密码（GOV-03，已删，**密码需轮换**）；`router/unknown_intent.md` 代码↔公司名（C-02，已删）；`ticker/infer_code.md` 名称→windCode / 命名指数→ETF 清单（C-01，唯一 open 的 P0，需业务确认改法）。`holding_query.md` 的真实账户名 / 契约魔数经批评员裁决为 P1（不是"会膨胀的业务字典"）
6. **真源之争**：ADR 0014 说 git 是真源、`test_prompt_governance.py` 把 7 个最重文件锁成 Dify 逐字镜像、客户要瘦身——三者互斥（GOV-01；批评员裁决：无现存生产错误故为 P1，但是路线图第一道闸，待用户拍板 ADR 0022 D1）

**已落地的管理层改进**（见第八节）：manifest 三态清单 + 四条不变量 lint 进 CI、v2 漂移防护（结构化 ack + expires）、版本化收敛为一种、晋升脚本产物契约修复、灰度节点 trace 写 prompt_name、规则页重写、去凭据。

**2026-09-15 用户拍板**：① ADR 0022 D1 采用模型 B（git 为真源、Dify 降为上游输入），逐字锁定测试已退役、上游漂移告警已上线；② 零风险瘦身批已直接落 v1（`--strict` 零违反），C-01 名称→代码清单已改格式占位；③ governance CI job 已加（push/PR 触发）。剩余：报告第七节步骤 5 的业务问题、步骤 1 的度量基线、步骤 4 的去 LLM 化。

## 二、全域盘点（`python scripts/prompt_inventory.py` 生成）

| 提示词 | 状态 | 加载点 | system 字符 | ≈tokens | JSON 禁令行 | Dify 占位符 | user 段字符 |
|---|---|---|---:|---:|---:|---:|---:|
| `judge/option_judge` | active | `scripts/langfuse_eval.py` | 427 | 267 | 1 | 0 | 0 |
| `option/extract_cancel` | active | `app/subgraphs/option/extract_cancel.py` | 1,344 | 840 | 0 | 0 | 44 |
| `option/extract_cancel_place` | active | `app/subgraphs/option/extract_cancel_place.py` | 1,116 | 698 | 0 | 0 | 44 |
| `option/extract_confirm_cancel` | active | `app/subgraphs/option/extract_confirm_cancel.py` | 1,325 | 828 | 0 | 0 | 44 |
| `option/extract_confirm_place` | active | `app/subgraphs/option/extract_confirm_place.py` | 3,171 | 1,982 | 0 | 0 | 73 |
| `option/extract_inquiry` | active | `app/subgraphs/option/extract_inquiry.py` | 11,281 | 7,051 | 0 | 0 | 0 |
| `option/extract_place` | active | `app/subgraphs/option/extract_place.py` | 4,056 | 2,535 | 0 | 1 | 0 |
| `option/extract_query` | active | `app/subgraphs/option/extract_query.py` | 1,320 | 825 | 0 | 0 | 44 |
| `option/intent` | active | `app/subgraphs/option/intent.py` | 7,257 | 4,536 | 0 | 5 | 162 |
| `option/intent_extract` | inactive | `-` | 65,711 | 41,069 | 0 | 0 | 0 |
| `option/param_limit` | inactive | `-` | 8,171 | 5,107 | 0 | 1 | 31 |
| `option_close/cancel_close` | active | `app/subgraphs/close/cancel_close.py` | 4,497 | 2,811 | 1 | 2 | 79 |
| `option_close/confirm_cancel` | active | `app/subgraphs/close/confirm_cancel.py` | 7,815 | 4,884 | 1 | 2 | 79 |
| `option_close/confirm_close` | active | `app/subgraphs/close/confirm_close.py` | 3,224 | 2,015 | 1 | 2 | 79 |
| `option_close/holding_query` | active | `app/subgraphs/close/holding_query.py` | 6,471 | 4,044 | 1 | 2 | 36 |
| `option_close/intent` | active | `app/subgraphs/close/intent.py` | 7,135 | 4,459 | 0 | 3 | 31 |
| `option_close/place_close` | active | `app/subgraphs/close/place_close.py` | 52,702 | 32,939 | 0 | 12 | 687 |
| `option_close/query_status` | active | `app/subgraphs/close/query_status.py` | 492 | 308 | 0 | 1 | 38 |
| `router/unknown_intent` | active | `app/nodes/intent_route.py` | 8,836 | 5,522 | 0 | 2 | 90 |
| `swap/cancel_order` | inactive | `-` | 1,360 | 850 | 2 | 2 | 91 |
| `swap/confirm` | inactive | `-` | 1,063 | 664 | 2 | 0 | 104 |
| `swap/confirm_cancel` | inactive | `-` | 1,063 | 664 | 2 | 2 | 91 |
| `swap/confirm_modify` | inactive | `-` | 1,188 | 742 | 2 | 2 | 91 |
| `swap/confirm_order` | inactive | `-` | 1,572 | 982 | 2 | 2 | 91 |
| `swap/excel_extract` | active | `app/subgraphs/swap/multimodal.py` | 14,775 | 9,234 | 5 | 0 | 0 |
| `swap/excel_extract_v2` | gray | `swap/excel_extract` | 9,111 | 5,694 | 0 | 0 | 0 |
| `swap/image_extract` | active | `app/subgraphs/swap/multimodal.py` | 67,246 | 42,029 | 18 | 0 | 0 |
| `swap/image_extract_v2` | gray | `swap/image_extract` | 55,266 | 34,541 | 0 | 0 | 0 |
| `swap/image_ocr` | active | `app/subgraphs/swap/multimodal.py` | 7,312 | 4,570 | 0 | 1 | 0 |
| `swap/image_ocr_v2` | gray | `swap/image_ocr` | 6,404 | 4,002 | 0 | 0 | 0 |
| `swap/intent` | active | `app/subgraphs/swap/intent.py` | 12,314 | 7,696 | 1 | 4 | 250 |
| `swap/intent_v2` | gray | `swap/intent` | 4,516 | 2,822 | 0 | 3 | 250 |
| `swap/place_order` | active | `app/subgraphs/swap/place_order.py` | 39,046 | 24,404 | 2 | 3 | 216 |
| `swap/place_order_v2` | gray | `swap/place_order` | 33,309 | 20,818 | 0 | 3 | 799 |
| `swap/query_order` | inactive | `-` | 1,337 | 836 | 2 | 2 | 91 |
| `swap/select_counterparty` | active | `app/subgraphs/swap/select_counterparty.py` | 2,817 | 1,761 | 0 | 3 | 137 |
| `swap/select_ticker` | active | `app/subgraphs/swap/select_ticker.py` | 2,906 | 1,816 | 0 | 3 | 143 |
| `ticker/infer_code` | active | `app/subgraphs/ticker/tools.py` | 7,291 | 4,557 | 1 | 4 | 26 |
| `ticker/judge_type` | active | `app/subgraphs/ticker/tools.py` | 609 | 381 | 1 | 1 | 26 |
| `ticker/rank` | active | `app/subgraphs/ticker/tools.py` | 6,198 | 3,874 | 1 | 5 | 160 |
| `ticker/tokenize` | active | `app/subgraphs/ticker/tools.py` | 10,562 | 6,601 | 2 | 1 | 31 |

| 状态 | 文件数 | system 字符合计 | ≈tokens |
|---|---:|---:|---:|
| active | 28 | 293,545 | 183,466 |
| gray（v2 灰度位，0 流量） | 5 | 108,606 | 67,879 |
| inactive | 8 | 81,465 | 50,916 |

**单请求提示词开销（按调用链累加 system 段）**：

| 请求路径 | system 字符 | ≈tokens |
|---|---:|---:|
| 互换图片下单（intent + image_ocr + image_extract） | 86,872 | 54,295 |
| 平仓下单（intent + place_close） | 59,837 | 37,398 |
| 互换文本下单（intent + place_order + select_counterparty + select_ticker） | 57,083 | 35,677 |
| 互换 Excel 下单（intent + excel_extract） | 27,089 | 16,931 |
| 标的识别（infer_code + tokenize + judge_type + rank，并行） | 24,660 | 15,412 |
| 期权询价（intent + extract_inquiry） | 18,538 | 11,586 |
| 平仓确认撤单（intent + confirm_cancel） | 14,950 | 9,344 |
| 期权下单（intent + extract_place） | 11,313 | 7,071 |
| unknown 兜底 | 8,836 | 5,522 |

三个 3 万 tokens 以上的路径（图片下单 / 平仓下单 / 文本下单）是延迟与成本的主要单点；option 域相对健康。

## 三、管理层现状（评估前已核实的事实）

| # | 事实 | 证据 |
|---|---|---|
| 1 | 所有节点只用 `prompt.system`；`.md` 的 `[user]` 段与 `Prompt.render_user()` 在 `app/` 内零调用点（合计 4,158 字符仍被同步与逐字断言） | `grep -rn "prompt.system\|render_user" app/` |
| 2 | 2026-09-11 e72ee2d 把 7 个文件回归为 `dify/yaml/场外交易-test.yml` 原文，并用 `tests/test_prompt_governance.py` 逐字锁定 | `git show --stat e72ee2d` |
| 3 | 与此同时 `swap/intent_v2` / `place_order_v2`（08-28 切出）未同步 v1 的更新 → 灰度位已漂移 | v1 system sha 在 1664739 / adcc436 与 HEAD 不同 |
| 4 | `compose_prompt` + `swap/v2/` 子目录形态零调用点、目录不存在；`Settings.swap_prompt_version` 死配置 | ADR 0003 #159 待裁决项 |
| 5 | `app/prompts/CLAUDE.md` 手写清单引用了不存在的 `swap/place_order.dify_original.md`、`swap/v2/` | 目录 `find` |
| 6 | Dify 有两份 YAML（`主干工作流.yml` / `场外交易-test.yml`），`select_counterparty` / `select_ticker` 两处内容不同；`场外交易-test.yml` 新增 LLM 节点「互换-全新下单交易对手识别」在 `app/prompts` 无对应文件 | 解析 YAML `llm` 节点 |
| 7 | 评估守护断裂：2026-09-10 f37ac0d 把 golden 移到 `tests/fixtures/old_typing/`，`scripts/check_fixture_consistency.py` 恒 exit 2、`check_adr_refs.py` 报 3 处路径不存在；CI 自 05-12 起仅 `workflow_dispatch` 触发，无人发现。瘦身的"eval PASS ≥ v1 基线"门槛当前没有可自动运行的载体（`plan0909.md` 正在重建） | 本地运行两脚本 |
| 8 | ticker 4 个提示词走 `_call_ticker_llm` 原文 JSON 解析（`<result>` 标签），非 `with_structured_output` | `app/subgraphs/ticker/tools.py:491-600` |

## 四、按域评估（核证后）

判定口径：health 红 = 结构性问题（悬空/矛盾/双份真源），橙 = 重复与错例回填为主，黄 = 可局部瘦身，绿 = 紧凑范本，灰 = 非活跃。`est` 为核证员认可的零/低风险可压缩比例。

### 4.1 option（8 活跃 + 2 非活跃，活跃 system 31K）

| 文件 | health | est | 核心问题 |
|---|---|---:|---|
| `intent` | 黄 | 30% | 撤单/确认撤单区分写 4 遍、数据源约束写 4 遍；`{{#…keywords#}}` 悬空；代码 4 条确定性快路径（"-"、"确认下单"、"撤单"+quote）使提示词规则 0/3/4 不可达且语义相反（OPT-11，deterministic_cancel 零测试） |
| `extract_inquiry` | 橙 | 45% | 同一规则三层陈述 + 94 个「→」示例；tenor/百分号/名义本金归一化交 LLM 且代码零校验（OPT-07）；示例围绕单一测试账户「11125测试短名（张天琪专用）」堆 8 组正反例（OPT-06，需业务确认匿名化，且被逐字锁定） |
| `extract_place` | 黄 | 30% | `hasFastExecutionIntent` 规则本体是未渲染占位符 `{{#17797951842080.output#}}`（OPT-02 / C-07）——09-11 回归时丢掉了本地写好的说明；「覆盖客户实测 bug 场景」正例是错例回填 |
| `extract_confirm_place` | 黄 | 45% | 70% 与 `extract_place` 逐字重复，一个被锁一个没锁 → 已漂移（OPT-09） |
| `extract_cancel` / `cancel_place` / `confirm_cancel` / `query` | 橙 | 60% | 唯一任务是 Q- 单号正则，swap 域同型节点 08-28 已去 LLM 化、option 未跟进（OPT-08）；13 字段 null 模板 ×7 + type/operate 输出要求对 schema 是死的（OPT-10） |
| `intent_extract`（非活跃） | 灰 | 100% | 65K 旧快照，Dify 侧已无对应原文，无消费者；占 option 目录 62% 字节（OPT-13，manifest 已写归档条件） |
| `param_limit`（非活跃） | 灰 | 100% | 4 份 Dify YAML 均无此节点，核心是「标的×执行价×期限 ≤10」整数乘法（OPT-14） |

跨文件：机器人过滤规则 ≈330 字符 ×8 份，且 7 个 extract 根本不注入 `bot_name_list`（OPT-01 / C-09，零风险删）。

### 4.2 option_close（7 活跃，system 84K，全部逐字等于 Dify 原文、未锁定也未登记 D5）

| 文件 | health | est | 核心问题 |
|---|---|---:|---|
| `place_close` | 红 | 55% | 全仓第二大活跃提示词。`hasFastExecutionIntent` 占 12% 篇幅但 `CloseOrderItem` 无此字段、`extra=ignore` 静默丢弃（OC-03 / C-05）；「POV 默认由后端兜底」说了 8 遍，代码却本地写死 25 并跨 leg 套用（OC-04 / C-04，需业务确认归属）；让 LLM 做 floor/分数/单位换算等算术（OC-06）；§A 前提三处、"不重数候选"五处、29 行自检表（OC-07）；中英混杂补丁块 + 示例编号断档（OC-08） |
| `confirm_cancel` / `cancel_close` / `confirm_close` | 橙 / 橙 / 黄 | 60/50/40% | 三文件共享 ≈8K 骨架与同一组示例单号，只有被投诉的那个加了 UUID/引号规则 → 已漂移（OC-09）；「必填至少一个」vs「可输出空列表」自相矛盾（OC-13）；代码兜底把 Q-/OPTG-/会话上一单塞进 `cancelOrderNoList`，打破提示词「CO- 开头、不可编造」契约（OC-18，P1） |
| `query_status` | 黄 | 100% | 提示词里已写明正则 `CO-\d{8}-[A-Za-z0-9]{8}`，整个节点 = 一次 LLM 调用跑正则 + 去重（OC-10） |
| `intent` | 橙 | 45% | 「关键区分」47 行逐条复述前文（29%）；system 内 3 个字面占位符（OC-14）；与 `place_close` 对裸数字语义相反（OC-15，限无 quote 场景）；~~代码写入枚举外值~~（OC-02，已修） |
| `holding_query` | 橙 | 30% | ~~对手列表占位符未注入 → 99999999 哨兵发后端~~（OC-01，已修）；示例含真实测试对手 / 员工名 / 公司全称 + 标的代码格式字典 + 哨兵魔数只在提示词（OC-17 / C-03，需业务确认） |

核证员补充：close 域存在 **5 套互不一致的 CO- 单号正则**（reference_parser 仅十六进制、place_close/cancel_close `[A-Z0-9]{4,16}`、confirm_close `[A-Z0-9]+`、query_status.md `{8}`），同一单号在链路不同环节被接受/拒绝；序号兜底正则只认阿拉伯数字，「第一笔」在兜底路径不匹配。

### 4.3 ticker（4 活跃，24.7K）+ router（1，8.8K）+ judge

| 文件 | health | est | 核心问题 |
|---|---|---:|---|
| `ticker/infer_code` | 红 | 45% | ~~当前日期未注入，期货月份推断失锚~~（TRJ-01，已修；但 :24/:209/:213 仍有「当前 2026-05 → CU2606」硬编码日期锚点与注入日期竞争）；`transactionTypes`/`inferencePrompt` 从未注入，41% 篇幅描述永远为空的变量（TRJ-02 / C-08，零风险删）；枚举表含 `CROSS_OTHER` 而代码 `GoatsTransactionType` 无（已漂移）；示例区 6 组不可推导的 名称→windCode / 命名指数→ETF 事实清单，与自身「不要硬编码具体代码」矛盾（TRJ-03 / C-01，P0 红线，需业务确认改法） |
| `ticker/tokenize` | 橙 | 55% | 与代码 `tools.tokenize()` 三条主规则重复且在文件自己的示例上行为不一致（`600519.SH贵州茅台` → `.SH贵州茅台`，≥5 组）（TRJ-05）；前缀词规则与示例正反两说（TRJ-06）；总示例块 22% 全是前文重复（TRJ-07） |
| `ticker/rank` | 黄 | 30% | ~~日期未注入~~（已修）；「用户期望品种」恒空、5 个 GOATS 字段契约文档未声明（TRJ-09 / C-24）；「相关性永远首要」说 4 遍、「临时补丁」无到期条件（TRJ-10） |
| `ticker/judge_type` | 绿 | 20% | 最轻一路，FUND/FUTURE 可正则化（TRJ-17，可选） |
| 4 文件共性 | — | — | 走 `<result>` 原文 JSON 解析而非 structured output，≈4.3K 字符格式协议 + 3 个正则解析器 + 静默 `{}` 降级（TRJ-04） |
| `router/unknown_intent` | 橙 | 45% | 38 组 few-shot 中 16 组被 `route_rules` 正则前置截获、永远到不了 LLM（TRJ-11）；Q- 引用撤单两组示例给出相反标签（TRJ-12）；~~港/美股代码↔公司名字典~~（C-02，已删）；「禁止 JSON」与 structured output 契约相反（TRJ-13 / C-18） |
| `judge/option_judge` | 绿 | 0 | 内容精炼；放在 `app/` 业务包、共用 LangFuse 优先加载分支、名字与范围不符（TRJ-15，归位问题） |

### 4.4 swap（增量：09-11 回归之后）

08-28 报告的病灶（护栏 0、🇮🇹 emoji、闭集词表、重复禁令、JSON 禁令、测试账户名）在回归后的 v1 中**全部原样残留**，且因逐字锁定不可本地修改（SW-INC-08）。增量发现：

- ~~回归只搬了提示词没搬拓扑：Dify 把「确认下单」交给 code 节点前置分流，app 未移植~~（SW-INC-01 / GOV-02，已修：移植同款词表为确定性前置）
- ~~`aggregate.shortname_from_pick` 多命中取首项~~（SW-INC-06，已修）
- `intent_v2` / `place_order_v2` 与 v1 已是业务规则代差（v1 新增护栏 0.5 等 12 处引用，v2 仍含 `confirm_order`），**不可放量，应废弃后从新 v1 机械再生**（SW-INC-03；manifest 已标注 + expires）；excel/image/ocr 三个 v2 无漂移
- Dify `场外交易-test.yml` 新增 LLM 节点「互换-全新下单交易对手识别」不是遗漏迁移，而是三处并行实现同一件事（Dify 小 LLM + code 唯一性 / app `_complete_counterparties` / LLM-C 护栏 0.5），需业务拍板一个归属（SW-INC-04）
- 两份 YAML 是同一 Dify app（`name: 场外交易-test`）的两次快照（`select_counterparty` system 2446→2817、`select_ticker` 2503→2906 字符）：`sync.py` 更新的文件不被治理测试锁，被锁的文件工具不更新（SW-INC-05 / GOV-09）
- 6 个去 LLM 化后的非活跃文件零引用、Dify 侧同类节点也已去 LLM 化，「行为规约参照」理由失效；`harness/reporter.py:89` 与 sync skill 的映射仍指向它们（SW-INC-07）
- `place_order.py` 手拼 user 消息里硬编码 ≈300 字符规则文本，不受任何治理覆盖（SW-INC-02 / C-25）

## 五、跨域病灶汇总（沿用 swap 报告五分类）

| 病灶 | 跨域证据（核证后） | 档位 | 估算可压缩 |
|---|---|---|---:|
| ④ 死重与悬空 | 7 个文件共 10 个悬空占位符 + 5 个 structured output 文件 27 行 JSON 禁令（`--strict` 共 12 项；option / option_close 其余文件的 JSON 禁令因 manifest 尚未登记 output_model 未计入）；JSON 格式禁令 36 行分布在 structured output 节点；option 机器人过滤块 ×7 引用不存在变量；infer_code 41% 描述永远为空的范围变量；`[user]` 段 4.2K 字符无调用点 | 零风险 | ≈25K |
| ③ 重复陈述 | option intent 撤单区分 ×4；extract_inquiry 三层陈述；place_close §A ×3 / 不重数 ×5 / 后端兜底 ×8；option_close intent 复述 29%；tokenize 总示例 22%；rank 首要主键 ×4 | 零风险 | ≈30K |
| ② LLM 干确定性活 | option 4 个 Q- 单号节点、close 4 个 CO- 单号节点（≈21K + 8 次 LLM 调用）；tenor/百分号/名义本金归一化；place_close 算术与 holdingMap 查表；tokenize 与代码分词双实现 | 低风险（eval + 单测） | ≈35K + 8 次调用/请求 |
| ① 错例回填 | 「覆盖客户实测 bug 场景」正例、🇮🇹/UB斯 幻觉复现、豁免优先于上面两条、place_close 中英混杂补丁块、confirm_cancel 五个单次错例各成规则、rank「临时补丁」 | 低风险（错例转 golden） | ≈15K |
| ⑤ 硬编码业务数据 | infer_code 名称→windCode / 命名指数→ETF；router 代码↔公司名（已删）；holding_query / extract_inquiry / swap intent 真实测试对手与员工名；holding_query 标的代码格式字典；99999999 哨兵只在提示词 | 需业务确认 | ≈5K |
| 新增 ⑥ 双份真源 | 提示词枚举 vs Pydantic Literal（swap transactionType 三份互不相同 C-22、option/close 13 字段骨架 ×8 C-19）；代码规则层 vs 提示词规则（option/close intent 快路径、place_close POV25、cancel_close 兜底）；5 套 CO- 正则 | 结构性 | — |

合计零/低风险档约 **10 万字符（活跃总量的 1/3）**，与 swap 报告的 -55% 口径一致；真正的收益不在字符数，在于每条规则只剩一处真源。

## 六、治理层评估与目标模型

### 6.1 核证后的治理层发现

| # | 发现 | 状态 |
|---|---|---|
| GOV-01 | 真源三方冲突（ADR 0014 git / 锁定测试 Dify / 客户瘦身） | **已拍板 B**：manifest `dify` 映射 + `check_upstream` 告警，锁定测试退役 |
| GOV-02 | 锁定测试守的是文本相等，不是「提示词枚举 ⊆ Literal 且 Literal 每个值可达」 | 症状已修（SW-INC-01，核证员在 HEAD 上判 refuted）；守护待加 |
| GOV-03 | `dify/sync.py` 硬编码内网账号密码；且 `DIFY_BASE` 是 `http://`，登录走明文 | 已删默认值；**密码需轮换**；明文 HTTP 需内网评估 |
| GOV-04 | 所有治理守护挂在 05-12 起只能手动触发的 CI 上 | 已加 `.github/workflows/governance.yml`（push/PR 触发，lint + strict 清单 + 提示词/意图测试） |
| GOV-05 | `promote_langfuse_prompt.py` 产物 loader 解析不了、不登记 manifest；ADR 0014/0022「已落地」失实 | 已修 |
| GOV-06 | 「占位符保留原样」规则在无渲染层的 LangGraph 里有害 | 规则已反转（prompt-management.md）；`--strict` 可见 |
| GOV-07 | 5 个灰度位 4 个不写 `prompt_name`，违反 ADR 0003 硬前置 | 已修（place_order / multimodal） |
| GOV-08 | `drift_acknowledged` 是永久静默开关 | 已改结构化 `{at_base_sha, note}` + `expires` |
| GOV-09 | 哪份 Dify YAML 是生产无机器可读声明；上游新增 LLM 节点无提示 | manifest `dify:` 映射已登记 31 条；`sync.py` 主干 app 导出名改为治理读取的 `场外交易-test.yml`；新增节点 1786439000001 现为常驻告警 |
| GOV-10 | D5 手写处置表历史上两次漏登记、无机制 | 资产状态已由 manifest 接管；改写记录改为 manifest `changelog`（本批 18 条） |
| GOV-11/12 | `.claude/rules` 教人做已废弃的事；ADR 0013 描述已删除链路 | 已重写 / 已改状态 |
| GOV-13 | `.md` 契约 1/3 是运行时不消费的内容（`[user]`、model、node_id） | ADR 0022 D5 登记，随 D1 一并收缩 |
| GOV-14 | lint 判定过弱 | 已收紧（真实加载调用 / loader_call / injects / --strict） |
| GOV-15/16 | `_versions.yaml` 98% 是注释；四套命名并存；judge 混在业务目录 | P2，随下次大 PR |

### 6.2 目标治理模型（ADR 0022 D1 推荐 B）

```
git app/prompts/*.md ── 唯一生产真源 ──► load_prompt → 节点渲染 injects → LLM
        ▲                                   ▲
        │ 人工 diff 选择性合入               │ manifest: status / loader / injects / output_model
        │                                   │           gray: base_sha + drift ack + expires
Dify YAML（上游输入，sync.py 拉取）          │ lint: prompt_inventory --check [--strict]
        │                                   │ 守护: 提示词枚举 ⊆ Literal；Dify 节点 sha 变化 → 告警
        └── test_prompt_governance：逐字锁定 ──► 改为「上游快照漂移告警」（切换动作只此一处）
```

切换前提只有一个需要业务方确认：M4 后 Dify 工作流不再是生产路径，并指明生产 app_id。在此之前维持现状，瘦身只能走 `*_v2.md`（且 v2 需随 v1 变化重新 ack）。

## 七、实施路线（完整性批评员精修版，按风险递增）

| 步 | 内容 | 退出门 | 状态 |
|---|---|---|---|
| 0 ✅ | **让守护真正生效**：恢复 `ci.yml` push + pull_request 触发并拆一个 <2 分钟 governance job（ruff + `prompt_inventory --check` + `tests/test_prompt_*.py` + 各子图 `test_intent.py`）；修 `check_fixture_consistency.py` 指向 `categories/`；确认 eval 入口可跑 | 空 PR 上 CI 自动绿；`langfuse_eval.py --local tests/fixtures/unified_golden.jsonl --ids <swap confirm 子集>` 在现场跑通 | governance.yml 已加；主 CI 恢复触发与 fixture lint 修复待 plan0909 |
| 1 | **建立度量基线**：`prompt_inventory` 增加按调用路径聚合的 tokens 报表（本次手算基线：互换文本 47.5K / 互换图片 62K / 期权询价 27K / 平仓下单 37.4K system tokens，含 ticker 三路）；`METRIC_LLM_TOKENS` 加 node 标签；`summarize_by_prompt_version` 对 5 个灰度位都能分桶；每个待瘦身 `.md` 能反查 ≥10 条命中它的 golden id | 仓库内有可复现基线文件；没有这一步，所有"eval 回归"门槛无载体 | 待做 |
| 2 ✅ | **裁决真源**（一次拍板解锁全部瘦身）：ADR 0022 D1 写定 git 为唯一真源、Dify 为上游输入，前提证据挂到 roadmap「业务方书面同意 Dify 下线」邮件；业务方指明生产 Dify app_id，`sync.py` 只保留它；`test_prompt_governance.py` 改为漂移告警；manifest 补 `dify: {file, node_id, system_sha256}` | D1 状态改「已采纳」；本地改任一 v1 文件后测试仍通过（只告警）；上游未映射 LLM 节点（1786439000001）有告警 | 已落地（2026-09-15） |
| 3 ◐ | **零风险瘦身批**：`--strict` 的 12 处（10 个悬空占位符整段删、structured output 节点 JSON 禁令）；option 机器人过滤块 ×7；重复陈述收敛；不可达 few-shot（TRJ-11 守卫测试）；`[user]` 段退出运行时契约；infer_code 硬编码日期锚点与范围段 | `--strict` 零违反并在 CI 默认开启；活跃 system 总字符降 ≥25%（互换文本 ≤38K tokens、平仓 ≤28K）；全量 eval PASS ≥ 步骤 1 基线且分桶无单桶下降 | `--strict` 项与机器人过滤块、infer_code 范围段已落（活跃 system 293.5K → 279.7K）；重复陈述收敛与不可达 few-shot 待 eval 基线 |
| 4 | **低风险档**：option 4 个 Q- 节点与 close 4 个 CO- 节点按 `swap/order_id.py` 去 LLM 化（先 `query_status`），先把 5 套 CO- 正则统一为一处；归一化下沉 validator；错例转 golden；示例压缩；`extract_confirm_place` 复用 `extract_place` | 每项先 RED 后 GREEN（含 `第一笔` 中文序数、多命中简写等本次发现的边界）；对应意图桶 PASS 不降；串行 LLM 调用数按 node 级 token 计数证明各 -1 | 待 3 |
| 5 | **需业务确认档**（每项一个明确问题）：(1) infer_code 名称→代码示例与基金管理人名单改占位/删除（P0）；(2) option `intent.py` "撤单" 快路径 vs 提示词 request_cancel_order（operate 取消 vs 交易）留哪处；(3) place_close POV 默认 25 归后端还是网关；(4) `hasFastExecutionIntent` 是否下传（Dify 侧 schema 也无此字段）；(5) 全新单对手召回三实现选一；(6) 裸数字语义；(7) 测试账户/员工名示例匿名化；(8) 99999999 哨兵归代码常量；(9) `param_limit` 是否需要 ≤10 组合校验；(10) `intent_extract` 归档 | 每问在 ADR 0022 附录有「问题 / 答复 / 日期 / golden id」一行；答复转 ≥3 条 golden 后再改；纳入 M3.3 E3.7 sign-off 清单 | 待业务方 |
| 6 | **治理固化**：manifest `changelog` + "改 `.md` 必须同步 manifest" 校验；`prompt(<scope>)` commit 类型 CI 检查；三条最重路径设 `max_system_chars` 冻结；一页提示词写作规范（语言、示例匿名、不写自检/JSON 骨架）；judge 迁 `harness/`；四套命名收敛 | 连续两次 Dify 上游同步后 `--strict` 持续零违反；manifest 无过期 gray；新人按规范能独立加一个节点 | 待 3 |

**评估守护前置条件**：09-10 golden 迁到 `old_typing/` 后 `check_fixture_consistency.py` 恒 exit 2、`harness run` 跑在归档数据上（`plan0909.md` 正在重建）；本报告与 CLAUDE.md 的 eval 入口已改指 `unified_golden.jsonl`。第 3 步之前必须先有一条能自动跑的 eval 基线。

## 八、本次已落地的改进

| 改动 | 说明 | 对应发现 |
|---|---|---|
| `app/prompts/_manifest.yaml` | 41 个 `.md` 的 active / gray / inactive 登记；inactive 写保留理由与可删条件；gray 记 v1 快照 sha + 结构化漂移 ack + expires；`loader_call` / `output_model` / `injects` | GOV-08/14, D2 |
| `scripts/prompt_inventory.py` + 测试 | 清单 + 四条不变量 lint（`--check` 进 CI）+ `--strict`（悬空占位符 / JSON 禁令）+ 到期警告 | GOV-06/14 |
| 删 `compose_prompt()` / `Settings.swap_prompt_version` | #159 遗留死路径；ADR 0003 / handbook 8.7 改口径；测试防复活 | D3 |
| `close/holding_query.py` | 对手列表占位符按 Dify 同口径渲染 | OC-01 P0 |
| `close/intent.py` | 删写入枚举外值的规则；规则层字面量 ⊆ 枚举守护 | OC-02 P0 |
| `swap/intent.py` | 移植 Dify `has_confirmation_keyword` 前置分流 | SW-INC-01 / GOV-02 P0 |
| `swap/aggregate.py` | 简写唯一性：精确 → 唯一子串 → None | SW-INC-06 P0 |
| `ticker/tools.py` | 注入 Asia/Shanghai 当前日期 | TRJ-01 P0 |
| `dify/sync.py` | 删默认凭据 | GOV-03 P0 |
| `router/unknown_intent.md` | 删 代码↔公司名 字典 | C-02 P0 |
| `scripts/promote_langfuse_prompt.py` | 产物按加载器契约渲染 + 自动登记 manifest gray | GOV-05 |
| `swap/place_order.py` / `multimodal.py` | trace 写 `prompt_name` | GOV-07 |
| `.claude/rules/prompt-management.md` 重写、`testing.md`、ADR 0000/0001/0003/0013、`app/prompts/CLAUDE.md`、handbook | 陈旧口径与已删文件引用 | GOV-11/12, OPT-15 |
| ADR 0022 + ADR README + ADR 0001 D5 登记 | 治理模型决策 | — |
| **D1 落地**：manifest `dify:` 上游映射 ×31 + `check_upstream` 告警；`test_prompt_governance.py` 逐字锁定退役 | git 为唯一真源 | GOV-01/09 |
| **零风险批**（18 条 manifest changelog）：烘焙 Dify 常量节点 keywords/output（5 处悬空占位符）、删 JSON 禁令、删 option 7 个机器人过滤块、infer_code 范围段 + C-01 事实清单改占位、image_ocr 对手列表渲染、删 `intent_v2`/`place_order_v2` | `--strict` 零违反 | C-01/07/08/09/27, OC-14, OPT-01/02 |
| **ADR 0023 试点**：`app/prompts/spec.py` PromptSpec + `blocks.py` 积木；option 8 / option_close 2 / swap 2 节点迁移；69 个输出字段补 description；删 option 7 份 JSON 骨架与 close intent 代码内追加指令；`swap/place_order` user 规则文本迁回 `.md` | 高代码范式契约层（第十节） | C-18/25, OPT-04 |
| `.github/workflows/governance.yml` | push/PR 触发的 <2 分钟守护 | GOV-04 |
| `.claude/skills/sync-dify-prompts/SKILL.md` 映射表、`docs/on-call-runbook.md` 热修口径、CLAUDE.md / README eval 入口 | 批评员补出的陈旧口径 | 第九节 |

**未能在本环境完成**：eval 回归（无 LLM 密钥、golden 迁移中）——所有提示词相关改动（router 红线、holding_query 渲染）需现场用 `scripts/langfuse_eval.py` 补跑对应子集；Dify 账号密码轮换。

## 九、完整性批评：六路评估都没覆盖的维度

批评员对全部核证结果做了"缺什么"检查并自行到仓库核实，补出五个维度（均带证据）：

| 维度 | 发现 | 处置 |
|---|---|---|
| **延迟 / 成本量化** | 仓库没有按节点的 token / 延迟计数器（`metrics.py` 的 `otc_agent_llm_tokens_total` 无 node 标签；reporter 只聚合整 run），瘦身收益无法被任何现有工具核算；路线图 05-12 以"128K 上下文够大"为由**跳过**了 C1.4 瘦身，而 `troubleshooting-sop.md` 仍把长 prompt 列为高风险——客户抱怨与团队"跳过"之间缺的正是一张按路径的 token 账 | 路线图步骤 1 |
| **LangFuse 运行时路径** | `on-call-runbook.md` 与 roadmap F4.6 承诺"LangFuse 在线切版本热修"，但 `load_prompt` 在 production 硬闸门直接 raise；仓库没有任何把 `.md` 写入 LangFuse 的工具，LangFuse 提示词名不在 manifest 任何字段 | runbook 已改口径（本 PR）；上传工具与命名登记为后续项 |
| **Dify 反向同步** | `dify/sync.py` 只有下载，不存在 git→Dify 通道——两种真源模型下"同步"都是单向人工；`sync-dify-prompts` skill 映射表 5 行指向非活跃文件、1 行指向已删文件、12 个活跃文件无映射；`sync.py --push` 在无 `feature-yaml` 分支时走 orphan + `git rm -rf .`，会删掉开发者工作树中全部已跟踪文件（默认关闭，但 CLAUDE.md 把它列为常规命令） | skill 映射已改指 manifest（本 PR）；`--push` 加脏树保护为后续项 |
| **评估集对瘦身的守护能力** | 文档化的 eval 入口 `tests/fixtures/golden.jsonl` 已不存在（本 PR 改指 `unified_golden.jsonl`）；按意图回推的用例覆盖极不均衡（option cancel_order_request 1 条、query_order_status 1 条 vs swap place_order_request 265 条）；**最大的提示词 `image_extract`（活跃总量 23%）与 `excel_extract` 在 golden 里零图片/文件输入**，三个多模态 v2 灰度位到期前无法用 eval 证明等价；本环境无 LLM 密钥 | 路线图步骤 1 / 3 的前置 |
| **团队协作流程** | `app/prompts` 22 次提交 6 位作者，用 `prompt(<scope>)` 类型的只有 2 次，影响最大的 e72ee2d 无类型前缀；无 CODEOWNERS；没有提示词写作规范（`place_close.md` 全英文 + 中文补丁块，其余 27 个活跃文件中文；示例用真实账户还是虚构、要不要写自检清单全凭作者习惯）——这是病灶随下一次同步长回来的机制性原因 | 路线图步骤 6 |

批评员的**跨路仲裁**也改变了三处评级：`holding_query.md` 真实账户名 / 哨兵魔数从 P0 降 P1（不是"会膨胀的业务字典"）；GOV-01 真源之争降 P1 但列为第一道闸；`infer_code.md` 名称→代码清单维持 P0（严重度与"需业务确认"的风险档是两个维度）。另指出 option `intent.py` 还有第 4 条确定性快路径（单个 `-` 即确认下单）在提示词中零对应，且 `deterministic_cancel` 分支零测试——与 close 域已修的 OC-02 同型，option 域仍 open（步骤 5 问题 2）。

## 十、高代码范式重评估：提示词管理与 AgentState / Pydantic 契约（2026-09-15 增补）

用户在 ADR 0022 落地后提出：提示词管理要按 **LangGraph 高代码范式**（AgentState 显式输入、Pydantic 显式输出、节点纯函数）重新评估，而不是停留在"文本文件 + 加载器"。按此口径重新核实 `app/subgraphs` 与 `app/nodes` 的 24 个 LLM 节点，结论：ADR 0022 治理的是**资产**，没有触及**契约**；契约层的缺失才是"冗余删不掉"的根因。

### 10.1 证据（代码迁移完成时 HEAD 实测）

| 维度 | 实测 | 后果 |
|---|---|---|
| 节点 → AgentState 输入契约 | 19 份 `_build_user_message`、9 份逐字相同 `_format_history`、3 份 `_format_*_list`，无任何声明 | 一个节点读哪些 State 字段只能读函数体；改字段名不会变红 |
| 输出契约 | 24 个输出模型 `Field(description=)` 为 **0**，语义全部在 `#:` 注释 | function calling schema 只带字段名 / 类型，`.md` 被迫维护 JSON 骨架 / 字段表（option 7 个 extract 各一份）→ 两份真源漂移（`hasFastExecutionIntent`） |
| 规则文本进 Python | `swap/place_order.py` user 拼装硬编码"核心护栏 6"+"hasFastExecutionIntent 最终判定"（C-25）；`close/intent.py` 后置追加 `_JSON_OUTPUT_INSTRUCTION`（C-18） | 不在 manifest changelog / eval 门视野内；违反核心原则 1 |
| 占位符渲染 | `holding_query` / `ticker/tools` / `multimodal` 各自 `str.replace` 常量 | manifest `injects` 与代码一致性靠人工 |
| 确定性前处理 | `quote_hints` / `prewash` / `order_id` / `pre_route` 已是"代码先算、LLM 后判"的先例 | 说明团队已经在按高代码范式做输入侧，只是没有形成契约对象 |

### 10.2 目标模型（ADR 0023）

一个 LLM 节点 = 一个 `PromptSpec`（`app/prompts/spec.py`）：`inputs`（AgentState 字段，构造期校验）+ `output_model`（Pydantic，`Field(description)` 是输出语义唯一真源）+ `injects`（system 占位符 → 渲染器）+ `user_builder`（只拼变量，规则文本住 `.md` `[user]` 段）+ `gray`。共享积木 `app/prompts/blocks.py` 替代各节点复制。注册表与 `_manifest.yaml` / AgentState 交叉核对，`prompt_inventory.py --check` 把 `PromptSpec(category=, name=)` 视为加载点。

### 10.3 试点结果（本 PR 已落地，12 节点）

| 指标 | 迁移前 | 迁移后 |
|---|---|---|
| `_build_user_message` 私有副本 | 19 | 11（剩余为第二 / 三批） |
| `_format_history` 副本 | 9 | 0 |
| 输出模型 `Field(description=)` | 0 | 69（option 全部 + close / swap 主要模型） |
| `.md` 内 JSON 骨架 | option 7 份 | 0（改为一句"以工具 schema 为准"） |
| 代码内规则文本 | `place_order.py` 两段 + `close/intent.py` 一段 | 0（迁回 `swap/place_order.md` `[user]` 段 / 删除） |
| 注册 PromptSpec | — | 12（option 8、option_close 2、swap 2） |

LLM 输入文本零变化（user 模板逐字迁回 `.md`；JSON 骨架删除属 ADR 0022 D4 零风险档），全量测试 GREEN（新增 `tests/test_prompt_spec.py` 与 lint 用例）。

### 10.4 剩余迁移与未决

- 第二批：close 5 个 + swap select_counterparty / select_ticker（机械迁移）；第三批：multimodal 3 个（含 v2 灰度位，需多模态 `user_builder`）、ticker 4 个（先转 structured output）、router
- `description` 也计 tokens：`prompt_inventory.py` 需把 function calling schema 算入单请求开销，才能与第九节的"按路径 token 账"合并
- `inputs` 目前只声明不强制；是否用受限 State 代理在测试里强制，第二批后决定

## 附录 A · 发现索引

编号前缀：OPT = option 域、OC = option_close 域、TRJ = ticker/router/judge、SW-INC = swap 增量、GOV = 治理层、C = 代码-提示词契约。完整证据（路径:行号 + 原文）见评估工作流产物；本表只列 P0/P1 与核证结论。**注意**：C-* 评估路的 `.py` 行号系统性失真（核证员逐条修正），本报告正文只引用 `.md` 行号与经核证的代码位置。

| ID | 严重度 | 核证 | 一句话 |
|---|---|---|---|
| OC-01 | P0 | 已修 | holding_query 对手列表占位符未注入 → 99999999 哨兵发后端 |
| OC-02 | P0 | 已修 | close intent 规则写入枚举外值 → close_unknown |
| SW-INC-01 / GOV-02 | P0 | 已修 | swap intent 枚举丢 confirm_order，确认下单链路不可达 |
| SW-INC-06 | P0 | 已修 | 对手简写多命中按列表顺序取首项 |
| TRJ-01 | P0 | 已修 | ticker 当前日期未注入，期货月份推断失锚 |
| GOV-03 | P0 | 已修 | sync.py 硬编码 Dify 账号密码（需轮换） |
| C-02 | P0 | 已修 | router 提示词 代码↔公司名 字典 |
| C-01 / TRJ-03 | P0 | confirmed | infer_code 名称→windCode / 命名指数→ETF 事实清单 |
| C-03 / OC-17 | P0 | confirmed | holding_query 真实对手 / 员工名 / 代码格式字典 / 哨兵魔数 |
| GOV-01 / OPT-16 / SW-INC-08 | P0 | confirmed | 真源三方冲突，阻断所有本地瘦身 |
| OPT-01 / C-09 | P1 | confirmed | 机器人过滤块 ×8，7 个 extract 不注入 bot_name_list |
| OPT-02 / C-07 | P1 | confirmed | extract_place hasFastExecutionIntent 规则是未渲染占位符 |
| OPT-04 / 05 / 07 / 08 / 09 / 11 | P1 | confirmed | 见 4.1 |
| OPT-06 | P1 | partial | 测试账户名成立；「名称↔代码映射」不成立 |
| OPT-13 / 14 | P1 | partial | 可归档成立；处置条件已在 manifest 登记 |
| OC-03 / 04 / 06 / 07 / 08 / 10 / 14 / 18 | P1 | confirmed | 见 4.2 |
| OC-05 / 09 / 15 / 19 | P1 | partial | 代码兜底仅在 LLM 输出非法时触发；三文件重复成立但 compose_prompt 已删；矛盾限无 quote；已登记 manifest 未锁定 |
| TRJ-02 / 04 / 05 / 06 / 09 / 11 / 12 | P1 | confirmed | 见 4.3（TRJ-02 枚举漂移已成事实） |
| SW-INC-02 / 03 / 04 / 08 | P1 | confirmed | 见 4.4 |
| SW-INC-05 / 09 | P1 | partial | 同一 app 两次快照成立、字符数按 YAML 实测修正；示例真实 UAT 对手名属 P1 而非 P0 红线 |
| GOV-03 / 04 / 05 / 07 / 08 / 09 / 11 | P1 | confirmed | 见 6.1 |
| GOV-01 / 06 / 10 | P1 | partial | 真源冲突成立但实害已修（建议降 P1）；注入实现在 HEAD 已有 3 处；D5 漏登记可核实 2 次 |
| C-04 / 05 / 06 / 08 / 11 / 15 | P1 | confirmed | POV25 归属（`place_close.py` 注释自称「不影响后端语义」却改写 POV/25）/ hasFastExecutionIntent 丢弃（Dify 侧 schema 也无此字段，属 Dify 原生死重）/ 多模态链旧 schema（image 缺 9 字段、excel 缺 13）/ 范围段死重 / option 撤单快路径 operate 分歧 / close 单号节点去 LLM 化（仅 cancel_close / confirm_close 有双路径）|
| C-02 | P0 | 已修 | 核证员在 HEAD 判「已修复 / 待 eval 回归」 |
