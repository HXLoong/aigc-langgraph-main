# ADR 实施记录归档（2026-05 ~ 2026-09）

> 2026-09-24 ADR 精简时，把各篇正文里的实施过程、落地流水与历史实现细节原样迁到此处（仅做标题降级与去重），
> ADR 正文只保留决策、理由、后果与一行现状（ADR 0030 D4）。**本文只读、不再维护**，内容反映写作时点，
> 与当前代码可能不一致；现行口径以 `docs/adr/` 为准。更早的完整原文见 git 历史。

## ADR 0001 · 推倒重写 app/

来源：`docs/adr/0001-rewrite-app-with-harness-first.md`（迁出前原文）

#### D5 · 节点合并策略：保守路 A+ 加 option 拆分

逻辑层与 Dify 大部分 1:1，两处定向重构 + 一处瘦身：

| 处置 | 内容 | 登记 |
|------|------|---|
| **合并** | 互换 3 个"确认 X"节点 → 1 个 `swap.confirm(expected_action)`，新写统一 confirm 提示词（`app/subgraphs/swap/confirm.py`） | 本 ADR |
| **拆分** | 期权 intent_extract（2870 行单节点）→ 1 intent + 5 extract（`extract_inquiry` / `extract_place_or_modify` / `extract_cancel` / `extract_confirm` / `extract_query`；close_order_* 归独立 close 子图） | [ADR 0011](../../adr/0011-split-option-intent-and-extraction.md) 二次修订 |
| **询价补参修复** | `option/intent.md`：期限补充归 `new_inquiry`，建仓补参/确认/撤单按动作和业务阶段判断，删除引用卡片关键词强制改写意图的后处理；`extract_inquiry.md` 增加可选原单号 `orderId`；`extract_place.md` 保留可选期限 `tenor`，原单号与新增期限同传，缺省参数由 Java 合并；保留冻结的 `intent_extract.md` | 2026-09-07 用户明确授权；两轮 HTTP + checkpoint + Java HTTP 请求回归，见 [API 契约](../../api-contracts/java-backend.md) |
| **回归当前 Dify 原文** | 将 `option/{intent,extract_inquiry,extract_place}.md` 与 `swap/{intent,place_order,select_counterparty,select_ticker}.md` 的 system/user 提示词完整同步为 `dify/yaml/场外交易-test.yml` 对应 LLM 节点的 `prompt_template`，移除上述文件相对当前 Dify 工作流的本地提示词改写 | 2026-09-11 用户明确要求；`tests/prompts/test_prompt_governance.py` 按 node_id 锁定 7 个提示词与 YAML 一致 |
| **瘦身** | `app/prompts/swap/place_order.md`：Dify 原版 3059 行 / 152,546 字符 → **2249 行 / 126,171 字符**（删冗余示例、压缩重复规则，保留语义；原版存为 `place_order.dify_original.md`）。注：DSL v2（2026-08）Dify 侧已自行重写该提示词，旧瘦身版随迁移被替换 | 2026-05-12 grill 授权，M2/M3 执行，本次补登记 |
| **瘦身 P0 批（2026-08-28）** | 客户反馈提示词冗长/规则写死损害泛化性，全量评估见 `docs/swap-prompt-slimming-assessment.md`。P0 零风险档产出 4 个 v2 共存文件：`swap/{intent,image_extract,excel_extract,image_ocr}_v2.md`——只删死重（JSON 格式禁令，structured output 已强制）、悬空规则（bot_name_list/shortname_list/序号/total 等未注入变量）、重复陈述（同一规则 2~9 遍收敛为 1 处权威表述）、自相矛盾的补丁修订史（"POV 空格"）；**业务规则语义不变**。灰度经 `_versions.yaml`/env 控制，默认 0 流量，eval PASS ≥ v1 基线后方可放量（ADR 0003） | 本 ADR + 评估报告 |
| **去 LLM 化（2026-08-28 瘦身 P1）** | swap 撤单/查单/三确认共 5 个节点的唯一任务是提取 `H-` 订单号，改为确定性提取（`app/subgraphs/swap/order_id.py`，来源优先级 1:1 对照原提示词规约）；省 5 次 LLM 调用（≈4.8K tokens/请求）与幻觉面。5 个提示词转非活跃资产保留。二次校验/后端调用/输出形状不变 | 本 ADR + 评估报告 |
| **治理机制（2026-09-15）** | 客户反馈提示词臃肿 → 全域可维护性评估（`docs/prompt-maintainability-assessment.md`）；资产状态（active / gray / inactive）改由 ~~`app/prompts/_manifest.yaml`~~ + `scripts/prompt_inventory.py --check` 机器守护（2026-09-16 已废弃移除），本表只登记改写决定；删除零调用点的 `compose_prompt` 形态 | [ADR 0022](../../adr/0022-prompt-governance-after-code-migration.md) |
| **零风险瘦身批（2026-09-15，ADR 0022 D1 拍板后直接落 v1）** | 烘焙 Dify 常量节点 17797951842080 的 keywords / output（5 处悬空占位符）；删 structured output 节点的 JSON 格式禁令（swap 4 文件 + holding_query）；删 option 7 个 extract 的机器人过滤块与 query/bot_name_list 声明（代码不注入）；`ticker/infer_code.md` 删从未注入的范围限制段、名称→windCode 事实清单改格式占位（C-01 红线）；删 `swap/intent_v2` / `place_order_v2`。逐文件记录曾见 ~~`_manifest.yaml`~~ 的 `changelog`（已随 ADR 0022 废弃移除，2026-09-16） | [ADR 0022](../../adr/0022-prompt-governance-after-code-migration.md) D4 |
| **回归副作用补齐（2026-09-15）** | 09-11 回归把 Dify 靠 code 节点前置分流的「确认下单」从 `swap/intent.md` 枚举中移除，app 未移植分流 → 确认下单链路不可达；已在 `app/subgraphs/swap/intent.py` 移植同款 `has_confirmation_keyword` 前置（不调 LLM）。同批：`select_counterparty.md` 把简写唯一性交给代码 → `aggregate.shortname_from_pick` 改「精确 → 唯一子串 → None」；ticker / holding_query 补齐 Dify 上游注入的 日期 / 对手列表 占位符渲染 | 评估 SW-INC-01 / SW-INC-06 / TRJ-01 / OC-01 |
| **保持** | 其他 Dify LLM 节点 1:1 复刻，提示词照搬 | — |

**节点数：蓝图 24 → 主干落地 19**（2026-09-22 口径：swap 6 + option 6 + option_close 7；ticker 已移交 Java）：

| 子图 | 蓝图 | 落地 | 差异说明 |
|---|---|---|---|
| swap | 10 | **6**（intent / place_order / confirm / cancel / query_order / unknown 兜底）+ 多模态分支 | `place_order_image` / `place_order_excel` 已落地（`app/subgraphs/swap/multimodal.py`，swap 图 image / excel 分支）；`cancel_extract` 已被确定性提取取代；`hand_to_share.py` 已删除（手转股退役） |
| option | 6 | 6（另有 unknown 兜底节点）| 与蓝图一致 |
| option_close | 7 | 7（另有 unknown 兜底）| 与蓝图一致 |
| ticker | 1（ReAct 子图）| **0** | 2026-09-20 整体移交 Java（[ADR 0025](../../adr/0025-instrument-resolution-delegated-to-backend.md)），本地无 ticker 节点 |

补充事实：`intent_extract.md`（2870 行）已冻结为 diff 快照，为非活跃资产；`place_order.dify_original.md` 已随 DSL v2 迁移（99a4c2f）删除。非活跃资产曾以 ~~`app/prompts/_manifest.yaml`~~ 为准（ADR 0022）；manifest 机制已于 2026-09-16 废弃移除。

互换"下单 vs 改单"共用 `place_order_request`，靠 `orderList[i].orderId` 有无区分（`swap/place_order.py` 落地一致）。

不走激进合并的理由（保留原论证）：用户最痛的三件事（标的不准 / 参数 bug / 评估缺失）分别靠 ticker 算法、Pydantic 契约、harness 解决，不靠节点合并；激进合并会让提示词信息密度过载、diff 颗粒度变粗。

提示词纪律：合并/新写/瘦身须在本表登记并过 ADR 0030 D3 评测门（[ADR 0003](../../adr/0003-prompt-versioning-by-file-coexistence.md) 管版本化）。

### 实现偏离（2026-08-27 核查，裁决同日落地）

| 偏离 | 现状 | 裁决 |
|---|---|---|
| ~~**ticker "1 节点 = ReAct Agent 子图"名存实亡**~~ | ✅ 关闭（2026-09-20）：ticker 域整体移交 Java（[ADR 0025](../../adr/0025-instrument-resolution-delegated-to-backend.md)），本地无 ticker 节点；历史现状见 ADR 0008 存根 | 2026-08-27 裁决 |
| ~~AgentState 业务参数字段无类型契约~~ | ✅ **2026-08-27 落地**：新增 `app/graph/business_params.py` 状态级模型，15 个写入点全部经 `validated_*` 校验（extra=forbid 防字段名拼错，输出与历史 dict 逐字节一致）；运行时保持 dict（读取侧/checkpoint/eval 零改动）——这是 D6 意图的当前实现形态，全运行时对象化留后续评估 |
| ~~`--mock-ticker` 开关~~ | ✅ 2026-08-27 裁决：**承诺撤销**——CI 回归由 pytest + mock LLM 承担，harness 数据集回归按 ADR 0030 D3 触发 |
| ~~harness 依赖面超纪律 3~~ | ✅ 2026-08-27 裁决：**纪律放宽**为"harness 仅依赖三个稳定入口：`app.graph.main` / `app.config` / `app.llm.clients`"——现状即合规，新增依赖需回本表登记 |

关联的 checkpointer 未接线问题已由 [ADR 0021](../../adr/0021-text-confirm-replaces-interrupt.md) 修复；数据库兼容边界见 [ADR 0009](../../adr/0009-mysql-version-and-tdsql-compatibility.md)。

## ADR 0008 · 标的识别（已被 0025 取代）

来源：`docs/adr/0008-ticker-resolution-as-react-agent.md`（迁出前原文）

### 历史迁移落地（2026-08-28）

~~`app/subgraphs/ticker/react_agent.py`~~ / ~~`graph.py`~~ 已删除（无任何生产/测试引用，`build_ticker_graph` 从未被主图接线）。`resolver.py` 重写为对齐 Dify 新 DSL「标的智能化推断和分词工具」（12 节点）+「标的相关性排序工具」的确定性编排管线：

```
tokenize（本地候选提取，暂代 P5 路由域的"候选标的提取"节点）
  -> format_candidate_list（空 -> 短路）
  -> asyncio.gather(infer_code_batch, split_ticker_keywords, judge_ticker_type)  # 3 路批量 LLM，一次调用处理全部候选
  -> merge_and_validate（确定性，交易所后缀正则校验完整标的，移植自 Dify code 节点）
  -> 逐 orgStr：GOATS securities-instrument/select 批量查询 + rank_candidates（LLM 排序过滤）
  -> TickerCandidate(from_goats=True)
```

- `completeness` 工具已删除，被 `merge_and_validate` 的确定性正则校验替代（Dify 新 DSL 同步删除了 completeness LLM 节点）。
- `_pick_winner` / `_pick_within_a_share` / `tools.pick_best` 三套互不一致的私有选优逻辑已删除，统一由 `rank_candidates`（LLM，对齐「大模型排序并过滤」提示词）承担排序 + 过滤职责。
- `infer_code` 从"单 keyword 同步线程调用 + 动态 prompt HTTP 拉取拼接"（ADR 0013）改为"全候选批量 async 调用 + 纯静态 `load_prompt()` 加载"，删除 5 分钟 LRU 缓存与 `_get_dynamic_prompt_cached` 链路。
- `from_goats=True` 硬约束**保持不变**——新管线在 GOATS 之后才产出 `TickerCandidate`，是本项目对 Dify DSL（本身不含 GOATS 校验步骤）的有意增强，详见下方「后果」段。
- 运行时约束 a/c（hard cap 8 步 / HITL 消歧）随死代码一并移除，未来若要接真 HITL 应走 [ADR 0006](../../adr/0006-hitl-interrupt-boundary.md) 的 interrupt 机制，而非复活 ReAct cap。

### 实际演进（历史）

1. **ReAct 从未接线**（2026-08-27 核查）：`react_agent.py` / `graph.py` 只在测试里编译冒烟；生产走确定性 resolver（tokenize → GOATS → 规则选优 → `infer_code` LLM 兜底 + GOATS 二次校验），与原决策相反但约束更强。三条运行时约束均为死逻辑。
2. **2026-08-27 裁决选项 (b)**：收窄为"确定性编排 + LLM 定点兜底（LLM 输出必须过 GOATS 校验）"，ReAct 死代码删除。
3. **DSL v2 迁移落地**（2026-08-28）：resolver 重写为对齐 Dify「标的智能化推断和分词工具」的 12 步管线（tokenize → 3 路批量 LLM → merge_and_validate → 逐 orgStr GOATS 查询 + LLM 排序），`completeness` 工具与三套私有选优逻辑删除。
4. **真子图化**（2026-09-17，ADR 0024 D3 重构 2）：私有 `TickerState`，`Send` 按 orgStr fan-out，`compile(checkpointer=False)`。
5. **整体移交 Java**（2026-09-20，commit `2f9ce65`）：上述全部本地实现删除；LangGraph 只提取原文候选与引用选择，标的工具由 Java 调用。

## ADR 0012 · 标的查询走后端 HTTP

来源：`docs/adr/0012-restore-backend-http-for-securities-instrument.md`（迁出前原文）

### 历史落地记录（2026-08-27）

**Endpoint 与客户端**（原行内 Status update 已吸收）：

- `GET /admin-api/integration/securities-instrument/select` —— **GET + RequestBody**（不规范但合法）；Java 侧 `SecuritiesInstrumentController.java:100` `@GetMapping("/select")` + `:104` `@RequestBody`，`/admin-api` 前缀由 `WebProperties.adminApi` 框架级注入。
- Python 落点分两层：Protocol/HTTP 实现在 `app/tools/ticker_client.py`（GET-with-body：`await client.request("GET", url, json=payload)`）；子图调用点在 ~~`app/subgraphs/ticker/tools.py`~~（completeness / rank 工具）与 `resolver.py`。原文的 `ticker_tools.py` 文件名已不存在。
- ⚠️ 无契约测试断言 method=GET + body 非空（现有测试全靠 AsyncMock），回归时可能被悄悄改回 POST——护栏待补（见后果）。

**后端业务规则清单**（对照 `aigc/api` 现码更新；正是本 ADR"与后端规则升级自动对齐"收益的实证——2026-07-06 后端 commit `4088b4a5` 改了数字，HTTP 方案零改动跟上）：

- 多关键词并行查询（核心 3 / 最大 10 线程，30s 超时）✅ 不变
- `isFull=true` 精确 vs `isFull=false` `INSTR` 模糊分流 ✅ 不变
- 多关键词命中加权（每多命中 1 个 -30 relevanceScore）✅ 不变
- "退市"标的过滤 ✅ 不变
- 配额：~~`max(5, 60/N)`~~ → **`max(5, 100/N)` + 低命中关键词释放额度轮询再分配**（`SEARCH_SCORE_RESULT_LIMIT=100` / `MIN_KEYWORD_QUOTA=5`）
- 结果上限：~~30 条~~ → **100 条**，按 relevanceScore 升序（**分数越小越相关**，0=精确匹配）

**MySQL 直连的处置（超出原计划）**：原决策保留直连给 mock_api 闭环 demo；`mock_api/` 已于 2026-05-13（commit `4ac9f0b`）整体删除，直连代码零残留。现状的测试形态 = AsyncMock 单测 + `scripts/probe_*_e2e.py` 真后端探针。遗留清理项：

- 死配置：`app/config.py` 的 `ticker_mysql_*`（5 项）与 `securities_instrument_url/key`（零引用）+ `.env.example` 对应段
- rot 脚本：~~`scripts/demo_closed_loop.py`~~（已删除）曾 patch 已删符号，早已不可运行
- `.env.example` 的 `OTC_API_BASE_URL` 示例含 `/admin-api` 会与 client 拼接出双前缀（真实 `.env` 与客户模板写法正确）

**Shadow 比对维度**：原 TODO 已完成——`scripts/shadow_compare.py` 归一化 `tickers` + `ticker_hitl_candidates` 做字段级 diff，有测试覆盖。

## ADR 0013 · 动态 prompt 片段（已撤销）

来源：`docs/adr/0013-load-dynamic-inference-prompt-fragment.md`（迁出前原文）

### 历史落地记录（2026-08-27）

**Endpoint**：`GET /admin-api/counterparty/info/instrument-inference-prompt`，返回 `CommonResult<String>`（包裹纯字符串）。Java 侧 `CounterpartyInfoController.java:32`（`@GetMapping`）/ `:36`（方法签名）——原修订注的 `:33` 是行号偏移，`docs/api-contracts/java-backend.md` 同处偏移待一并修正。`/admin-api` 前缀由 `WebProperties.adminApi` 框架级注入。

**实现链路**：

1. 客户端：`app/tools/ticker_client.py` 的 `TickerClient.get_inference_prompt()`（普通 GET → `result.data` 为 `str`；ADR 0001 D2 三 Protocol 拆分后的归属，原文的 `OtcBackendClient` 已不存在）。
2. 缓存：~~`app/subgraphs/ticker/tools.py`~~ 的 `_get_dynamic_prompt_cached()` —— **模块级单 key 缓存 + 300s 绝对过期 + 进程重启清空**（非 `functools.lru_cache`；`infer_code` 工具入口调用）。多副本部署时各副本缓存独立，热改后最长 5 分钟不一致，可接受。
3. 拼接：静态 ~~`app/prompts/ticker/infer_code.md`~~ 作框架（输出格式、调用规范），动态片段以 `## 后端动态片段（实时拼接）` 追加到 system 末尾。
4. 净化：`_sanitize_dynamic_prompt`（**实现于调用侧** `tools.py`，非原文说的 client 侧；行为等价）——strip + 控制字符剔除 + 4096 字符截断。⚠️ 超限当前是**静默截断**，非原文的"落警并降级"。
5. 降级：后端不可达 → warning + 空片段（仅静态文件），metrics 计数 `otc_agent_dynamic_prompt_total{status=cache_hit|cache_miss_ok|fallback}`，不让 ticker 崩。

### 实现偏离（2026-08-27 裁决：追认 metrics 方案 + 轻修）

| 偏离 | 现状 |
|---|---|
| 拼接后完整 prompt 摘要未落 trace | 裁决：**降级为结构化日志**——`_get_dynamic_prompt_cached` 命中/拉取时以 warning/info 记录片段长度（现有 logger 已含），完整还原依赖后端 config 的变更审计；不再作为 trace 硬要求 |
| 降级标记落 metrics 不落 trace | 裁决：**追认 metrics 方案**（`otc_agent_dynamic_prompt_total{status=fallback}` 为正式载体）；会话级定位可用 trace_id 关联 LangFuse warning 日志 |

## ADR 0015 · 一级路由

来源：`docs/adr/0015-intent-route-rules-first-llm-fallback.md`（迁出前原文）

### 历史落地（DSL v2 前的四层路由，已由文末迁移修订取代）

#### 第 1 层 · 订单号正则（命中即返回）

| 正则 | → product_type |
|---|---|
| `H-\d{8}-[A-Z0-9]+` | swap |
| `OPT-\d{8}-[A-Z0-9]+` | option |
| `CO-\d{8}-[A-Z0-9]+` 或 `OPTG-[A-Z0-9]+` | option_close |
| `Q-\d{8}-[A-Z0-9]+` | option_close（落地后新增，与前四条同为业务硬约定，本次补录）|

#### 第 1.5 层 · quote_content 产品标记（落地后新增层，原文未记录）

`_QUOTE_MARKERS`：引用卡片内容含 `-----场外期权询价详情-----` / `-----场外期权持仓详情-----` / `平仓申请已生成` / `-----互换订单参数-----` 等标记时直接定产品。**优先级高于关键词**——修复 swap-001 类多轮 bug（上轮 swap 订单卡 + 本轮"确认下单"被 option 关键词劫持）。

#### 第 2 层 · 关键词优先级表

**以 ~~`app/prompts/router/keywords.yaml`~~（DSL v2 迁移后已删除,规则并入 `app/nodes/route_rules.py`）为准**（原为业务方单文件维护，启动时加载一次，命中即 break）。语义契约：优先级顺序 **option_close > option > swap**；表已从立项时 3 行示例扩张到 option_close 11 词 + 4 正则 / option 22 词 / swap 24 词 + 5 正则，ADR 不再复制具体词表。

#### 第 3 层 · LLM 兜底

仅规则全部未命中时调用：

- ~~`load_prompt("router", "product_type")`~~（DSL v2 迁移后改为 `load_prompt("router", "unknown_intent")`,391 行,原 product_type.md 已删除）
- 入参：`raw_text` **+ `quote_content`**（拼接到 user 段，原文只写 raw_text，本次补录）
- `with_structured_output(ProductTypeOutput)`，Literal 四值
- **历史工厂偏离已裁决（2026-08-27）**：旧决策选 standard，实际用 thinking；追认 thinking 工厂为事实默认，并规定未来按工厂分化模型前先统一调用点。

#### 第 4 层 · unknown 兜底

LLM 判 unknown 或异常 → `product_type="unknown"` → 主图走 fallback render（友好回复 + trace，不进子图）。`ProductType` Literal 与 `app/graph/main.py` 的 `option_close` / `unknown` 分支均已落地。

#### trace 决策来源（错例追溯用，现为 4 种取值）

`rule:order_no→X` / `rule:quote_marker→X` / `rule:keyword[kw:词]→X` 或 `rule:keyword[re:正则]→X`（带命中 token）/ `llm→X`。

### DSL v2 迁移落地（2026-08-28 修订）

Dify 主干工作流 2026-08 版重写了一级路由,本 ADR 的分层结构随之重构(`feature/dify-dsl-migration` 分支):

- **规则层**:原「订单号正则 + quote_marker + keywords.yaml」三层合并为 `app/nodes/route_rules.py`——
  Dify「脚本判断期权、互换、其他查询指令」code 节点的 1:1 移植(订单号正则/口语化平仓/互换系统引用/
  下单特征/平仓查询关键词/关键词计数,含文件分类:全图片→互换-图片,全 Excel→互换-Excel)。
  keywords.yaml 与 quote_marker 层退役(引用卡片内的订单号由规则层合并扫描 quote_content 覆盖)。
- **语义变化**:`Q-` 单号归 **option**(期权开仓/报价单号,修正旧版误归 option_close 的 g029 类问题)。
- **LLM 兜底**:提示词换为 `app/prompts/router/unknown_intent.md`(Dify「unknown意图兜底识别」,391 行),
  输出 Literal[互换-文本/期权-文本/期权平仓-文本/unknown]。
- **前置分流**:路由之前主图先分流 fast_query(快速询价)与 existing_command(存量兼容),
  并由 `pre_route` 解析对手列表/引用候选标的(见 `app/graph/main.py`)。
- trace decision 取值变为 `rule→<DSL 标签>` / `llm→<DSL 标签>` 两种。

### 多轮引用语境修正（2026-08-28 二次修订，客户反馈 bug）

客户反馈意图识别 bug；评估（`docs/archive/reports/intent-recognition-assessment-2026-08.md`）定位为 DSL v2 1:1 移植
丢失了旧 quote_marker 层的多轮工程修复。本次在规则层叠加三处**工程增强**（偏离 DSL 源，特此登记）：

1. **期权语境让位**（`_has_option_context`）：口语化平仓(step2)与互换下单特征(step4)原本不看
   quote——raw/quote 含期权特征（期权/看涨/看跌/雪球/CALL/PUT）时，step2 直接归期权平仓、
   step4 让位后续层。修复「引用期权持仓卡 + '序号1市价全平'→互换」类 42 条实锤错分。
2. **持仓引用让位**（step5.5）：引用含"持仓"且带期权语境时归期权平仓（raw 含明确互换方向词除外）。
   修复「持仓卡 + '序号1平留300万/限价10 200w'→计数层误归 option」类 57 条错分。
   口语化模式补 `平剩`。
3. **多轮粘性**（intent_route 第 3 层）：规则与 LLM 双 unknown 且 checkpoint 携带上一轮
   product_type 时继承之（trace `sticky→<pt>`）。修复「裸发'确认下单'→LLM 判 unknown→
   fallback 打断」（LLM 兜底实测 229/244 判 unknown）。配套：`make_initial_state` 移除
   `product_type="unknown"` 的每轮重置（eval 入口原会覆盖 checkpoint 粘性）。

量化（golden 802 轮 · 真实卡片近似口径）：规则层精准率 **90.2% → 99.7%**（错分 76 → 2 条边角），
详见评估报告附录。`Q-` 单号归 option 于 2026-08-28 裁决确认，数据集 opt_close-064 已同步。
trace decision 新增第三种取值 `sticky→<pt>`。回归：`tests/nodes/test_route_rules_context.py`
（真实卡片 fixture 矩阵，P0-2 口径修正）+ `tests/nodes/test_intent_route_sticky.py`。

## ADR 0022 · 提示词治理（已废弃）

来源：`docs/adr/0022-prompt-governance-after-code-migration.md`（迁出前原文）

### 上下文

代码迁移（DSL v2，2026-08-28）完成后，`app/prompts/` 有 41 个业务 `.md`、system 段合计约 48 万字符（≈ 30 万 tokens），其中生产活跃 28 个 / 灰度 5 个 / 非活跃 8 个。提示词的**内容**问题（错例回填规则、重复陈述、structured output 下失效的 JSON 格式禁令、悬空变量、硬编码业务数据）在 swap 域已由 `docs/swap-prompt-slimming-assessment.md` 定性，本次评估扩到 option / option_close / ticker / router 全域。

比内容更根本的是**管理**问题——同样的内容病灶会在下一次 Dify 同步后重新长回来：

1. **真源之争**：ADR 0014 D3-2 规定生产真源是 git `.md`；2026-09-11 又按用户要求把 7 个文件回归为 `dify/yaml/场外交易-test.yml` 原文并用 `tests/prompts/test_prompt_governance.py` 逐字锁定。任何对这 7 个文件的瘦身都会让测试失败。更重要的是**锁定守的是文本相等而非代码契约**：这次回归把 Dify 靠 code 节点前置分流的 `confirm_order` 从提示词枚举中删掉，代码 Literal / 路由 / 二次校验没有同步，互换确认下单链路一度不可达（评估 SW-INC-01，已补前置分流）。
2. **活跃/非活跃靠手写**：`app/prompts/CLAUDE.md` 手写"禁止直接删"清单，其中 `swap/place_order.dify_original.md`、`swap/v2/` 已不存在；没有机器可读清单，也没有"每个 .md 必须有加载点"的守护。
3. **三套版本化形态并存**：`_versions.yaml` 同目录灰度（在用）、`compose_prompt` + `swap/v2/` 子目录拼装（零调用点、目录不存在）、`promote_langfuse_prompt` 的 `_v{N+1}` 晋升；ADR 0003 ">2 并存版本视为治理债"无执行机制。
4. **v2 灰度位漂移无防护**：2026-08-28 切出的 `swap/intent_v2` / `place_order_v2` 在 09-11 v1 被 Dify 更新后没有同步，若此时放量会丢规则。
5. **`.md` 契约有死区**：所有节点只用 `prompt.system`，`[user]` 段与 `render_user()` 在 `app/` 内零调用点，却仍被同步与逐字断言；`node_id` / `model` 元数据无代码消费。

### 决策

#### D1 · 真源：git `.md` 是唯一生产真源，Dify 降为上游输入（**已采纳，2026-09-15**）

两种模型的对比：

| | A · Dify 为真源，git 只读镜像（现状 09-11 后） | B · git 为真源，Dify 为上游输入（推荐） |
|---|---|---|
| 瘦身落地方式 | 只能走 `*_v2.md` 灰度位；v1 永远等于 Dify 原文 | 直接改 v1（经 eval 门），Dify 更新走 `export_dify_prompts.py --overwrite` 前人工 diff 选择性合入 |
| Dify 侧更新 | 全量覆盖 v1，本地修复丢失（09-11 已发生一次） | 以 diff 形式呈现，人工决定合入哪些 |
| 与 ADR 0014 D3-2 | 冲突（D3-2 说真源是 git） | 一致 |
| `test_prompt_governance.py` | 逐字锁定 7 文件 | 改为 **Dify 快照漂移告警**：登记 7 个 node_id 的 prompt sha，Dify YAML 变化时提示"上游有更新待合入"，不阻断本地修改 |
| 客户诉求"瘦身" | 只能在灰度位实现，且 v2 会持续漂移 | 可以真正落地 |

采用 B。落地方式：

- manifest 每条镜像自 Dify 的条目登记 `dify: {file, node_id, system_sha256}`（上次同步时上游节点 system 的 sha）；~~`scripts/prompt_inventory.py`~~ 的 `check_upstream` 在上游节点变化时输出「上游有更新待人工 diff 合入」告警、上游存在但未映射的 llm 节点告警（如 1786439000001「互换-全新下单交易对手识别」），映射的节点不存在才 fail
- `tests/prompts/test_prompt_governance.py` 的逐字相等断言退役，改为「每个镜像条目都声明了 dify 映射且节点存在」+「本地修改不阻断」
- 零风险瘦身直接落 v1（`manifest.changelog` 登记）；`swap/intent_v2` / `place_order_v2` 因已与 v1 产生业务规则代差且失去用途而删除，多模态三个 v2 保留待 eval
- Dify 侧同步方向仍是单向（sync → export → 人工 diff）；dify/sync.py 对主干 app 的导出文件名改为 场外交易-test.yml（治理读取的那份），主干工作流.yml 冻结为 2026-08 拓扑参照（**2026-09-17：整条链路随 ADR 0024 D1 移除**）
- Dify 退出上游后停止更新，上游告警自然归零（2026-09-17 已发生，ADR 0024 D1）

#### D2 · ~~`app/prompts/_manifest.yaml`~~ 是活跃/灰度/非活跃的机器可读真源（已落地，2026-09-16 移除）

- 每个 `.md` 必须登记 `status: active | gray | inactive`；`scripts/prompt_inventory.py --check` 进 CI 守四条不变量：
  1. 目录 ↔ manifest 双向无孤儿
  2. `active` 的 `loader` 文件存在且引用了字面量 name
  3. `inactive` 在 `app/` 内零 `load_prompt` 引用，且 `reason` 必填（保留理由 + 可删条件）
  4. `gray` 记录 `base_system_sha256`（切 v2 时 v1 的 system 快照），v1 之后被改 → 报"漂移"，必须重做 diff 并写 `drift_acknowledged`
- `python scripts/prompt_inventory.py` 同时产出字符数 / 估算 tokens / JSON 禁令行数 / Dify 占位符数 / `[user]` 段字符数，替代人工 `wc -m`
- `app/prompts/CLAUDE.md` 不再手写非活跃清单，只指向 manifest
- 取代 ADR 0001 D5 "处置表登记制"中的**资产状态**部分；D5 表继续登记**改写决定**（合并 / 拆分 / 瘦身批次）

#### D3 · 版本化形态收敛为一种：同目录并存 + `_versions.yaml`（已落地）

- 删除 `compose_prompt()` 与 `Settings.swap_prompt_version`，~~`tests/test_prompt_inventory.py`~~ 防复活
- `promote_langfuse_prompt.py` 产出的 `_v{N+1}.md` 同样按 D2 登记为 `gray`
- ">2 并存版本视为治理债"由 manifest 的 `gray` 条目数可见化；转正时 v2→v1 并注销条目

#### D4 · 瘦身纪律：三档 + 错例转 golden + 死重一律删（**放量待业务方**）

沿用 swap 评估报告的三档：

| 档 | 内容 | 门槛 |
|---|---|---|
| 零风险 | structured output 下的 JSON 格式禁令；未注入变量的悬空规则；同一规则 2~9 遍收敛为 1 处；自相矛盾的修订史；示例污染防护三大段 | eval PASS ≥ v1 基线 |
| 低风险 | few-shot 去重；自检清单与正文去重；闭集词表改"语义类 + 少量锚例" | eval + 抽样人工比对 |
| 需业务确认 | 硬编码产品名 / 名称词典 / 真实账户与员工名（P0 红线）；低频输入形态整段降级；提示词承诺但代码未实现的后处理 | 业务方逐条确认 |

原则：**错例回填规则转 `tests/fixtures/` golden，提示词只留通用原则**；LLM 干确定性活（订单号提取、量词展开、时间补零、表格模式判定）下沉代码，参照 `app/subgraphs/swap/order_id.py` 先例。

#### D5 · `.md` 契约瘦身（已落地一半）

- `[user]` 段：保留作 Dify 原始输入形态参照，不再是运行时契约；节点 user 消息由代码拼装。**ADR 0023 修订**：user 消息里含规则文本的节点，把规则写回 `[user]` 段用 `{{var}}` 占位并由 `PromptSpec.user_builder` 经 `render_user()` 渲染（先例 `swap/place_order.md`），此时 `[user]` 段重新成为运行时契约
- `{{#node.var#}}` 占位符：只允许出现在**代码确实注入了对应值**的位置（由代码-提示词契约评估逐文件核对）；未注入的占位符视为悬空规则，属零风险删除档
- `node_id` / `model` 元数据：仅供 Dify 对照，无代码消费

#### D6 · 非活跃资产处置（已落地）

8 个 `inactive` 条目的保留理由与可删条件写在 manifest `reason` 字段。全量上线稳定 7 天后按 reason 逐条清理；Dify 原始快照类归档到 `docs/archive/dify-originals/`（已有先例）而非留在 `app/prompts/`。

## ADR 0023 · PromptSpec

来源：`docs/adr/0023-prompt-as-code-langgraph.md`（迁出前原文）

#### D5 · 迁移路径（不一次性全迁）

以下批次为历史记录。2026-09-20 标的识别委托后端后，ticker 提示词及其输出模型已删除；
现役注册以主图加载后的 `all_specs()` 为准（2026-09-22：14 个；多动作编排及其拆分提示词已退役）。
职责见[标的识别边界](../../backend-instrument-boundary.md)，不恢复已退役的本地推断节点。

| 批次 | 节点 | 说明 |
|---|---|---|
| 试点（本 ADR 已落地） | option intent + 7 extract、option_close intent / holding_query、swap intent / place_order | 12 个，覆盖三种形态：纯变量 user、带注入、带灰度与 `[user]` 模板 |
| 第二批 | close 5 个（place_close / cancel_close / confirm_close / confirm_cancel / query_status）、swap select_counterparty / select_ticker | user 拼装同构，机械迁移；同时给 `close/models.py` 剩余模型补 description。**已完成（2026-09-17），含 swap/fresh_counterparty** |
| 第三批 | swap multimodal（image / excel / ocr，含 v2 灰度位）、ticker 4 个（tools.py helper 形态）、router unknown_intent | multimodal 输入含图片 / 文件，`user_builder` 需扩展为多模态消息；ticker 先完成 ADR 0022 未决项"转 structured output"再迁。**已完成（2026-09-17）**：multimodal 3 个（image_ocr 为 system 渲染 + 运行期 user 拼接）、ticker 4 个输出契约见 ~~`app/subgraphs/ticker/models.py`~~、router unknown_intent |

**2026-09-17 D 批（去 LLM 化，非 PromptSpec 迁移）**：close 4 个 CO- 节点（cancel_close / confirm_close / confirm_cancel / query_status → `close/order_id.py`）与 option 4 个 Q- 节点（extract_cancel / extract_cancel_place / extract_confirm_cancel / extract_query → `option/order_id.py`）已转确定性提取，8 个对应提示词文件同批删除；注册表 28 → 20（2026-09-20 ticker 4 个注销后 → 15）。

每批的门：对应子图测试 GREEN + eval PASS ≥ 迁移前（迁移本身不改 LLM 输入文本，eval 应零变化；原 `prompt_inventory --strict` 门槛已随 ADR 0022 废弃移除，2026-09-16）。

## ADR 0024 · LangGraph 原生重构

来源：`docs/adr/0024-langgraph-native-rearchitecture.md`（迁出前原文）

### 上下文

DSL v2 迁移（2026-08）后，代码在 LangGraph 上跑通了全部业务链路，但评估显示它在四个决定性能力上仍是 Dify 形态（详见评估报告第一节评分卡）：

1. **图**：子图靠手写 `ainvoke` + `Overwrite` 包装，无 input / output schema，1.x 的 Command / Send / RetryPolicy / durability 零使用；ticker 12 步管线是"Python 写的图"；`render` / `place_close` / `extract_inquiry` 是 Dify code 节点原样搬来的厚节点。
2. **持久化**：checkpoint 除 `history_messages` 外只写不读；生产 saver 单连接无重连；无请求级幂等（重试即重复下单）；serde 未固化；`history_messages` 无界。
3. **可观测**：生产走裸 `CallbackHandler`，trace_id 契约是死码；LangFuse 无 session / user；LLM 指标零调用导致告警永不触发；敏感字段明文。
4. **评估**：CI 自 2026-05-12 不跑；主力 921 条数据集被主力加载器拒绝；`windCode` 别名 bug 让仅有的节点级期望恒假失败；写类链路零 `place_params` 期望。

同时，两条现行纪律把 Dify 钉成业务真源：`app/nodes/route_rules.py:8`"改业务逻辑必须先改 Dify 源再同步"、`.claude/rules/git-workflow.md`"提示词冲突永远选 Dify 原始版本"。ADR 0022 已把 git 定为提示词真源，但代码与流程层的这两条没有同步撤销。

### 落地记录（按日期保留历史；当前边界见文首）

2026-09-17 条目保留为当时记录；其中 ticker、本地卡片、记忆补单号及独立 error handler 的现役状态以本篇 2026-09-22 修订为准。


- 2026-09-17 首批（TDD）：`harness/differ.py` `windCode` 修正 + 真实 `TickerCandidate` 契约测试；`record_history` 加 `@safe_node`；`AgentState.reply_text` 重复声明清理、`api_result` 类型改为 `str | dict | list | None`；`_build_run_config` 增加 `langfuse_session_id` / `langfuse_user_id` / `langfuse_tags`；`graph.ainvoke(..., durability="exit")`；生产 saver `serde` 白名单固化；`tracing.py` 客户端注册顺序修正；撤销 `route_rules.py` 与 `git-workflow.md` 两条"Dify 为真源"纪律。其余首批项（CI 触发恢复、saver 连接池、请求级幂等、LLM 指标 callback、`/ready` 软硬分离、revoke 明文 key）当时列为待办，后续批次逐项落地。
- 2026-09-17 重构 1（D2 / D3，TDD）：`TraceEntry` / `Message` 增加不参与 dump 与相等比较的 `id`，`trace` / `history_messages` 的 reducer 由 `operator.add` 改为 `merge_by_id`（与 LangGraph `add_messages` 同款按 id 去重）；新增 `SubgraphOutput` TypedDict，三个业务子图 `StateGraph(AgentState, output_schema=SubgraphOutput)`，子图对 `product_type` / `swap_input_mode` / `history_messages` / 入口字段的写入停在子图内；主图改为 `add_node(name, compiled_subgraph)` 原生嵌入，删除 `_as_subgraph_node`。实验（`tests/graph/test_reducers.py` / `test_subgraph_contract.py`）证实：原生子图节点回传完整输出 state，`operator.add` 会把父图已有 trace 再加一遍，按 id 合并后零重复；`_reset_turn_trace` 暂留（一轮边界收敛到 ingest 待下一步）。
- 2026-09-17 重构 2（D3，TDD）：ticker resolver 变真子图 ~~`app/subgraphs/ticker/graph.py`~~——私有 `TickerState`，`extract_candidates` → 三路 LLM 并行分支（`infer_codes` ‖ `split_keywords` ‖ `judge_type`）→ `merge_candidates` → `Send` 按 orgStr fan-out `resolve_org_item`（GOATS + rank，此前串行）→ `assemble` 按输入 index 汇总；`compile(checkpointer=False)` 不继承父 checkpointer；节点函数留在 `resolver.py`（测试 monkeypatch 边界不变），`resolve_ticker_full()` façade 契约不变。~~`tests/subgraphs/ticker/test_graph.py`~~ 断言拓扑与并发峰值 ≥ 2。
- 2026-09-17 重构 3（D3，TDD）：swap 选对手 ‖ 选标的 并行——两个 LLM 节点只产出指针到 `swap_counterparty_picks` / `swap_ticker_picks`（AgentState 新增两通道），确定性查表覆盖收敛到新汇合节点 `swap_apply_picks`（用后清空通道）；`_route_after_place_order` 返回并行分支列表，两条边汇合到 `swap_apply_picks` 再路由提交 / 兜底。热路径少一次串行 LLM 往返；`place_params` 保持单值覆盖语义，不引入 dict 合并 reducer。
- 2026-09-17 重构 4（D3，TDD）：`render` 18 分支决策树每个出口写 `TraceEntry(node="render", decision=…)`（`passthrough` / `api_result` / `hitl_card` / `zero_match` / `error:*` / `unknown_*` / `close_card` / `cancel_ack` / `no_reply` 等），回复文本零变化；eval 失败归因不再看不到 render 走了哪条分支。
- 2026-09-17 重构 5（D3，TDD）：`close_place_close` 215 行 6 阶段厚节点拆成子图 `build_place_close_graph()`：`place_close_parse` → `fetch_orders` → `extract`（LLM）→ `normalize`（合并 + 确定性后处理）→ `validate` → `submit` / `reject`，两处早退（空列表、校验失败）做成图边，每阶段一条 TraceEntry，错误归因到具体阶段（如 `place_close_extract`）；私有 `PlaceCloseState`（AgentState + `pc_*` 中间态）+ `PlaceCloseOutput` output_schema，中间态不外泄；close 图 `add_node("close_place_close", build_place_close_graph())` 原生嵌入；`close_place_close(state)` façade 契约不变，汇总条目沿用 `close_place_close` 名兼容既有归因。
- 2026-09-17 重构 6（D2，TDD）：业务对象 per-turn 语义落地——评估核实没有任何业务节点把上一轮的 `tickers` / `place_params` / `cancel_params` / `confirm` / `query_filter` / `close_params` 当结果读（唯一读者是 render，残留会被渲染成"已收到撤单请求"），`ingest` 统一清空这些字段与 `ticker_hitl_candidates` / swap 指针通道；一轮的边界收敛到 `ingest`（`trace` 用 `Overwrite([])` 重置，`@safe_node` 学会把自身条目写进 Overwrite），删除主图 `_reset_turn_trace` 节点；跨轮记忆只保留 `history_messages`。API 层对当轮输入字段的显式置空保留（输入必须由请求决定，不属于图内边界）。
- 2026-09-17 重构 7（D4，TDD）：`history_messages` 窗口——reducer 改为 `merge_history`（按 id 合并后只保留最近 N 条），N 走 `Settings.history_window_messages`（默认 40 条 ≈ 20 轮，`.env.customer.template` 已登记），只影响超过 20 轮的长会话；N 的最终取值由现场 eval 校准。
- 2026-09-17 （D4 / D5，TDD）：checkpointer 改为 `aiomysql.create_pool`（`checkpoint_pool_minsize` / `maxsize` / `pool_recycle_seconds` 默认 1 / 10 / 1800，小于 MySQL `wait_timeout`）+ `AIOMySQLSaver(conn=pool, serde=白名单)`，`from_conn_string` 单连接形态退出生产；新增 `probe_checkpointer()`，`/ready` 的 mysql 探针在 saver 已接线时打 saver 自己的池；`/ready` 区分硬依赖（mysql / java_backend → 503）与软依赖（langfuse / llm → 200 + degraded）。真实 MySQL / TDSQL 上的连接池行为仍需现场验证。
- 2026-09-17 （D4 / D5，TDD）：**请求级幂等** `app/api/idempotency.py`——以企微 `message_id` 对齐 `message_log.uk_message_id`：首次占位 → 跑图 → 回填 `reply_text`；重投已完成 → 回放上次回复（`outputs.replayed=true`）不重跑图；处理中 → 固定文案；无 message_id 不做幂等；存储故障只 warning（退化为无幂等）。`REQUEST_IDEMPOTENCY`（默认关，客户模板开）+ `message_log` 新增 `reply_text` 列（`sql/init.sql` 附 ALTER）。**LLM 指标 callback** `app/observability/llm_metrics.py`——`on_llm_end` / `on_llm_error` 自动 `emit_llm_call` / `emit_llm_tokens`（节点名取 `metadata["langgraph_node"]`），常驻于每次 graph 调用的 `config["callbacks"]`，`llm_failure_high` 告警与成本日报从此有数据。
- 2026-09-17 （D5，TDD）：**LangFuse 注入路径统一**——删除 `app/graph/main.py` 图级 `_attach_langfuse_callbacks` 与 `app/main.py` 的 environment 分叉，`tracing._enabled()` 不再绑死 development，所有环境走 `routes.attach_request_trace` 请求级 handler（生产从此有 trace_id / session / user 契约与 trace_url）；入站 traceparent 信任改为独立开关 `TRUST_INBOUND_TRACEPARENT`（默认关）；`Langfuse(environment=)` 按环境切分；`scripts/langfuse/langfuse_eval.py` 自带 handler 并携带 `langfuse_session_id` / `trace_id` 与生产同契约。
- 2026-09-17 入口收敛（D2 / D5，TDD）：`make_initial_state` 退役——一轮输入 → AgentState 的唯一入口收敛为 `app/api/turn_state.py::inputs_to_state`（从 routes 抽出），生产与 eval 同一路径；删除 M1 兼容层（它硬清空业务对象、写 6 个不存在的键）。lifespan 关闭段 `tracing.flush()`。
- 2026-09-17 `expected_action` 提升顶层（D2，TDD）：新增 `ExpectedAction = Literal["place", "modify", "cancel", "inquiry", "close"]` 与 `AgentState.expected_action`（per-turn，ingest 重置，`SubgraphOutput` 放行）；`PlaceParams` / `CancelParams` 信封不再接受该键（`extra=forbid` fail-fast）；swap / option / close 全部写类节点改写顶层（option 两种撤单原来的 `request_cancel` / `cancel_request` 收敛为 `cancel`，意图仍由 `intent` 区分；提交 / 汇合节点不再逐节点转抄该键）；render 的期权询价无结果分支读顶层。**Java 契约结论**：`docs/api-contracts/java-backend.md` 明确后端只读 `answer` / `data.outputs.reply_text`，该键不在 Java 读取面；`_state_to_outputs` 新增顶层 `outputs.expected_action`，同时把它投影回 `outputs.place_params` / `outputs.cancel_params`（wire 兼容既有探针 / 日志读者，state 本身不改写），可在确认无外部读者后移除投影。
- 2026-09-17 harness B 方言收敛（D6，TDD）：`harness/golden.py` 成为三方言唯一加载器——A（`categories/`）、B（`unified_golden.jsonl`：`conversation[{raw_content, quote_desc}]` + case 级 `expected`）、raw（`id + raw_content`），默认发现并入 B 文件，可执行样本 389 → 1310（多轮 9 → 260），混合方言 fail-fast。B 多轮的 case 级 expected 描述的是焦点轮（`swap/confirm` 是末轮、`option/place_from_quote` 是中间轮），故引入 `expected_scope="any_turn"` + `differ.check_case_assertions`（任一已执行轮同时命中即通过）；`quote_desc` 非空 → `quote_previous=True`，首轮标注引用只记录不回放。数据缺陷不掩盖：48 条某轮 `raw_content` 为空的 case 标 `skip_reason`，`select_runnable` 在 CLI / eval 显式报数后跳过；`check_fixture_consistency.py` 同时 lint 两份文件（一个文件一种方言、id 跨文件唯一），空轮与 9 条 `product_type=query` 以 WARNING 列出归 Issue #113。`scripts/ai_test_langgraph/` 标 deprecated。D6 其余项（业务拒绝单独桶、早停未执行轮记失败、`--backend dry-run` 真生效、`expected.place_params` 必填）待后续批次。
- 2026-09-17 harness 判定口径收口（D6，TDD）：`_report_case` 出 `status ∈ {PASS, FAIL, REJECTED}`，后端业务拒绝且无其它 diff 的 case 进 REJECTED 桶，不再算 PASS，summary / markdown 分桶计数、`pass_rate` 只数 PASS；早停后未执行的轮次逐轮记 `runtime` 失败（多轮 case 不再因首轮拒绝静默通过）；`/health` 新增 `backend_mode`（`dry-run` / `real`），`_doctor` 据此对 `--backend` 把关——想 dry-run 却打在真后端、或想真回归却打在 dry-run 都拒绝启动，旧服务端不报模式时 dry-run 亦拒绝；`check_text_assertions(allow_dry_run=)` 让 dry-run 模式下 `DRY-RUN-` 标记不算失败。D6 仅剩写类 case `expected.place_params` 必填（需业务方抽检）。
- 2026-09-17 RetryPolicy + 客户端单例 + 协议层解耦（D3，TDD）：`app/graph/retry.py`——`@io_node`（`@safe_node(retryable=IO_RETRYABLE)`：后端不可达 / LLM 限流超时 5xx 穿透，其余异常仍就地落 error）+ `add_io_node`（挂 `RetryPolicy(max_attempts=NODE_RETRY_MAX_ATTEMPTS)` + 节点级 `error_handler`，耗尽后 `retry_exhausted_handler` 写 ErrorInfo 与 `error:retry_exhausted` trace，cascade 照常）；每次穿透打 `otc_agent_node_total{status="retry"}`。**读写分界**：16 个只读 IO 节点（意图识别 / 抽取 / 选择 / 查询 / ticker 三路 LLM 与 GOATS）挂重试，下单 / 撤单 / 确认 / 平仓 / 询价 14 个写类节点保持 `@safe_node` 不重试——超时后重试可能重复下单，`tests/graph/test_retry_policy.py` 以清单守护；`add_io_node` 拒绝非 `@io_node` 函数（否则 safe_node 吞异常、RetryPolicy 静默失效）。`app/tools/http_pool.py`：lifespan 打开一个 `httpx.AsyncClient` 连接池（`trust_env=False`，limits 100/20），option / swap / ticker / GOATS agent 四个 Client 经 `acquire_http_client` 复用，超时逐请求按各自设置传入；测试 `transport=` 注入与未开池的脚本 / 探针走独占临时 client，既有 30 个 monkeypatch 边界不变。`app/tools/bot_context.py`：`BotContext.from_state` / `missing_required` / `to_wire` 取代三份重复的 `_context` / `_message_id`，协议层只吃上下文模型；`call_*_backend(state, ...)` 签名不变，边界处转换。未做：`@safe_node` 的 `(state, config)` / `Runtime` 注入（当前无节点需要）。
- 2026-09-17 `extract_inquiry` 拆子图 + `last_confirmed_params`（D3 / D4，TDD）：期权询价三条管线（快速询价 GOATS 直传 / 代码型标的预检 / LLM 抽取）做成图边——`inquiry_fast_parse` → `inquiry_fast_submit`、`inquiry_precheck` → `inquiry_reject`、`inquiry_extract` → `inquiry_resolve` → `inquiry_submit`，四个只读阶段 `@io_node` 挂 RetryPolicy，两个提交阶段不重试；私有 `InquiryState`（`iq_*`）+ `InquiryOutput`；LLM 失败归因到 `inquiry_extract`（此前整节点一个名）；汇总条目沿用 `option_extract_inquiry` 名与 decision 口径，测试 monkeypatch 边界不变，option 图原生嵌入。ConversationMemory：`AgentState.last_confirmed_params`（跨轮持久化，ingest 不重置，不在 SubgraphOutput）由主图新节点 `remember_confirmed_params`（render 之后、record_history 之前）写入——本轮无 error、`api_code == 0`、`expected_action ∈ {place, modify, inquiry, close}` 且从业务对象 / 后端回复（按产品线 `H-` / `Q-` / `CO-` 正则）拿到订单号时覆盖，撤单 / 确认回合不改写；读取点 `app/graph/memory.py::memory_order_ids(state, product_type)`：swap 三确认、option 确认下单 / 确认撤单、close 确认平仓 / 确认撤销在**文本抽不到单号**时回退到记忆。**优先级决定**：显式单号 > 引用消息 > 记忆——记忆只补裸确认，不扩大操作范围（close 点名序号 / 合约但对不上仍回请求补充）。
- 2026-09-17 节点延迟直方图 + 结构化日志（D5，TDD）：`otc_agent_node_latency_ms{node}` 独立直方图，`emit_node_completed` 不再往 intent 直方图写 `product_type=unknown` + `node` label 的寄生样本，`alerts.py` P95 解析器删除 `node=` 字符串过滤 hack；`@safe_node` 单一计时——节点自写的本节点 TraceEntry 缺 `elapsed_ms` 时补上（`node_trace.duration_ms` 不再恒 NULL），已有值与其它节点条目不动。`app/observability/logs.py`：structlog 接管 stdlib logging（业务代码不改写），`LOG_FORMAT=auto|json|console`（auto = development 控制台、其余 JSON），`LOG_LEVEL` 终于被消费；`bound_request_context` 在 routes 里包住整次图调用，`trace_id` / `conversation_id` / `message_id` 经 contextvars 进每条日志，退出时只解绑自己绑的键；lifespan 起点 `configure_logging_from_settings`（幂等，不动 uvicorn 自己的 handler）。
- 2026-09-17 Dify 残留 B / C 级清理（D1）：**C 级删除**——打 tag `dify-assets-frozen-20260917（指向 commit fddd94e；tag 仅存本地，远端拒绝 tag 推送，维护者可从该 sha 重建）` 后移除 dify/（sync.py + README + 1.7MB YAML）、scripts/export_dify_prompts.py、sync-dify-prompts / migrate-prompt 技能、dify-reviewer / prompt-migrator agent 及 `.agents` 镜像、mock_api rerank 桩、tests/api/test_20_dify_rerank.py（连同 ~~`tests/api/_utils.py`~~ 里的明文 Dify key）、3 个零流量 *_v2.md、docs/archive/dify-originals/（1.1MB）；日期型对比报告移入 `docs/archive/reports/`。**B 级**——19 份业务 `.md` 删除零消费的 node_id / model 元数据行；12 份只作 Dify 输入形态参照的死 `[user]` 段删除（现役 `[user]` 只剩 `swap/place_order.md`、`swap/fresh_counterparty.md`）；system 占位符改原生名 `{{counterparty_list}}` / `{{current_date}}`，`fresh_counterparty` 不再用 Dify 原文当 `render_user` 键；`app/main.py` description 与加载器 / 规则 / 根文档口径同步。**未做**：`scripts/shadow_compare.py` 是 M4 灰度工具链的一部分（CLAUDE.md 列为就绪能力），是否退役待 F4.1 决策；ADR 0022 保留原位（已标废弃，移动会打断 ADR 互引）；一级路由中文标签改原生 Literal 会改 LLM 输出词汇表，需 eval 门；~110 处"与 Dify 对齐"注释与 ~30 处测试口径未逐条改写。

### 附录 · Dify 残留分级清单（摘要）

以下工作量与分类为原方案快照；原生 endpoint / adapter 迁移按 D7 暂缓，shadow 工具保留。

- **A 保留**：`app/api/routes.py` wire schema + 502 语义 + `_INPUT_FIELD_ALIASES`；`app/tools/{swap,option}_client.py` 意图枚举；~~`app/tools/goats_rfq.py` 签名~~（2026-09-22 普通询价快捷分支退役，主图快速询价使用 `app/tools/goats_agent_client.py`）；`docs/on-call-runbook.md` 回切预案（G5.2b 后失效）。
- **B 替换**（19-26 人日）：原生 endpoint + adapter；`DifyWorkflowRun*` 重命名；提示词 `node_id` / `model` 行；31 处死 `[user]` 段与占位符；`fresh_counterparty.py:24-28` hack；4 处 system 占位符命名；`intent_route.py:36-51` 中文标签；两条纪律；~110 处注释；~30 处测试；`option_close`/`close`；`app/main.py:68` description；活跃文档。
- **C 删除**（4-6 人日）：dify/、scripts/export_dify_prompts.py、sync-dify-prompts / migrate-prompt 技能与 dify-reviewer / prompt-migrator agent（含 `.agents` 镜像）、`mock_api` rerank 桩、tests/api/test_20_dify_rerank.py、3 个 0 流量 *_v2.md、docs/archive/dify-originals/、日期型对比报告、ADR 0022 移 archive。（2026-09-17 除 shadow_compare 与 ADR 0022 外已全部执行，见落地记录）
- **安全（历史提案）**：曾提出对 ~~`tests/api/_utils.py:12`~~ 中的历史凭据执行 revoke；本轮历史 GOATS 测试凭据按 #218 用户裁决不处理。

### 2026-09-22 巡检裁决与本地实现

- 用户确认按当前 Dify 的入口边界收敛询价：普通 `new_inquiry` 仅保留 `inquiry_extract → inquiry_normalize → inquiry_submit`，产品关键词不再触发 GOATS 解析。`inquiry_fast_parse / inquiry_fast_submit` 及旧直连客户端退役；GOATS 快速询价保留在主图 `fast_query=1` 的 `quick_inquiry`。上文 2026-09-17 三管线记录作为历史保留。本次仅对齐入口与链路，询价字段契约差异另行处理。
- #218：用户决定不处理历史 GOATS 测试凭据，不纳入本轮验收。
- #219：Python 依赖已限制 PyMySQL < 1.2；已部署环境与离线包核查仍待执行，不宣称现场已修复。
- #223：7dfed2a 在原 IO 节点最后一次失败时返回错误，恢复正常图边与并行收尾；专项 RED 8 条失败，GREEN 85 条通过。
- #224：6938513 建立共享节点契约目录并保留应用/评测各自范围，修复 render.api_code 输入遗漏；专项验证结果见本轮交付记录。上述提交仅在本地，待合入。
- shadow_compare、测试与 shadow-test 技能继续保留，从当前删除范围中移出；去留待 F4.1 灰度与回滚安排确定。
- 全量 pytest、真实业务回归、性能测试留待统一验收；Java 保持零修改。

## ADR 0028 · 多指令编排（已退役）

来源：`docs/adr/0028-session-entry-and-multi-instruction-send-orchestration.md`（迁出前原文）

### 历史方案（已退役，仅保留实施记录）

以下 D2–D4、备选方案和后果记录 2026-09-18 的实现，不代表当前能力或待办。

#### 历史 D2 · 多指令计划：确定性预筛 → LLM 拆分 → Code 定位与拒绝规则（~~`app/graph/instructions.py`~~）

- 预筛：无分隔符 / 连接词且动作词计数 ≤ 1 → `single_instruction`，不调 LLM；引用卡片的批量补参 → `quoted_batch_supplement`，不拆。
- LLM（PromptSpec `router/split_instructions`）只输出 `InstructionCandidate`：`text`（连续原文，不改写）、`evidence`（= text）、`confidence`、`depends_on`（只能引用前序）、`requires_result`（是否必须使用前序生成的订单身份）；最多 8 条。
- Code 定位每条的 `start` / `end`：相邻指令之间只允许分隔词与连接词，**不得遗漏原文**；定位失败 → `EvidenceError`（E2）。
- 拒绝拆分：含业务成功条件（"成交后再…"，HTTP `code=0` 不证明成交）→ 要求用户稍后显式确认；多指令携带附件（归属不明）→ 拒绝。

#### 历史 D3 · `instructions` 子图：依赖分波、`Send` 并行准备、批量一次提交

```
initialize → schedule ─(Send 按就绪指令 fan-out)→ prepare_instruction ×N → submit_instruction_batches → schedule … → finish
```

- `schedule`：依赖未完成的指令等待；依赖失败 → `blocked(dependency_unavailable)`；`requires_result` 要求恰好一个依赖且能取到权威订单号，否则 `blocked(dependency_binding_ambiguous)`。
- `prepare_instruction`：以主图的 worker 形态（`build_main_graph(_instruction_worker=True)`，无 persist / 不递归编排）跑单条指令；`capture_operations` 在协议边界**捕获**已校验的 DTO 而不真提交；依赖结果以后端真实回复（非伪造卡片）追加进 `history_messages`；一条指令产出 0 / >1 个操作分别记 `needs_input` / `blocked`。
- `submit_instruction_batches`：`batch_operations` 把同一产品、可合并的列表型操作合成一批，`execute_batches` 每批提交一次；`dedup_window_seconds`（默认 10s）与 `blocked_keys` 防止同键重复提交。
- `finish`：逐条 / 逐批输出"第 N 条指令：<后端真实回复或状态文案>"；任一 `uncertain` → `ErrorInfo(BackendUnreachableError)` 触发对账语义（[ADR 0026](../../adr/0026-request-idempotency-uncertain-receipts-reconciliation.md)）；混合指令的 `product_type=unknown` / `intent=multi_instruction`，每条真实结果保留在 `instruction_results`，不写成单一 Java `productType`。

#### 历史 D4 · 边界

- 子图 `compile(checkpointer=False)`，中间态 `_*` 不外泄（`InstructionsOutput`）。
- 写类操作仍不重试（ADR 0024 D3）；批内失败隔离，不回滚其它指令。

### 历史备选方案

- **串行逐条重跑主图**：第 N 条的依赖需要前序结果，串行实现简单但整体延迟随条数线性增长，且无法隔离 persist 副作用。否决。
- **LLM 一次输出多个 DTO**：违反 [ADR 0027](../../adr/0027-field-evidence-contract.md)（最终值由 Code 产生），且无法表达依赖与批量。否决。
- **预筛 + LLM 拆分 + Send 并行准备 + 批量提交（当时选择，现已退役）**。

### 历史方案后果

- 正面：单条指令路径零额外 LLM 调用（预筛短路）；多指令并行准备、按依赖分波提交；每条指令失败隔离并有独立结果；`Send` 在主链路有了真实用途。
- 负面：worker 形态的主图与正式主图必须保持拓扑同步（同一 `build_main_graph`，用 `_instruction_worker` 分叉）；`dedup_window` 与后端自身去重的关系需现场校准；多指令回复较长。
- 未决：跨产品依赖（期权成交后互换）的身份绑定；条件指令（"成交后"）的权威事件契约；set-intent 对 `multi_instruction` 的 Java 侧语义。
