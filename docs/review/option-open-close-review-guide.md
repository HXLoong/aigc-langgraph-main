# 期权开仓 / 期权平仓重构代码 · 人工审阅导读与检查报告

> 日期：2026-09-24；基线 commit `6475adc`。
> 范围：`app/subgraphs/option/`（开仓，19 个文件约 2100 行）、`app/subgraphs/close/`（平仓，17 个文件约 2200 行）、
> 共享确认协议 `app/execution/confirmation.py`，以及 `app/prompts/option/`、`app/prompts/option_close/`。
> 用途：这部分代码由 AI 生成，本文帮助审阅人快速建立心智模型，并附上已发现的问题。
> 本文只读检查，**没有修改任何业务代码**。

## 0. 怎么用这份文档

1. 先读第 1、2 节：建立"一条消息怎么走到 Java"的整体图。
2. 按第 3、4 节的"建议阅读顺序"读代码，每个文件只需对照表里那一句职责。
3. 第 5 节是问题清单：标"已复现"的都用只读 Python 片段实测过，可以直接转成 RED 测试。
4. 第 6、7 节是可读性清理项和测试缺口，第 8 节是审阅 checklist。

**检查基线**（CI 同款占位环境变量，`tests/subgraphs/option` + `tests/subgraphs/close` + `tests/graph/test_confirmation_paths.py`）：

| 检查 | 结果 |
|---|---|
| pytest | 750 passed / 1 failed。失败用例是 `test_order_type_normalization.py::test_public_diagnostic_does_not_expose_candidate`，原因是容器缺 `_cffi_backend` 原生模块（pyo3 panic），属环境问题，与代码无关 |
| ruff（三个目录） | All checks passed |
| mypy（三个目录） | no issues found in 39 source files |

注意：测试全绿**不代表**没问题。第 5 节的缺陷都没有被现有测试覆盖。

---

## 1. 全局地图

```
POST /v1/workflows/run
  → 主图 ingest → pre_route → intent_route（product_type）
      ├─ option        → build_option_graph()   app/subgraphs/option/graph.py
      └─ option_close  → build_close_graph()    app/subgraphs/close/graph.py
  → persist → render（优先级：reply_text > api_result/api_code > error > default_reply）
```

两个子图的形状一致：

```
START → <x>_intent（LLM + 确定性规则）→ 条件路由（有 error → <x>_unknown）
      → 一个意图对应一个业务节点 → END
```

所有业务节点最终都调用 `POST /admin-api/financial-orders/operate`（`OptionClientHttpx().operate`），
区别只在 DTO 的装法：

| | 开仓 `option/backend.py::call_option_backend` | 平仓 `close/backend.py::call_close_backend` |
|---|---|---|
| 业务参数放在 | `orderList=[...]` | `orderList=[]` + `closeOrderReqVO={...}` |
| `operate` 字段 | 由 `_INTENT_TO_OPERATE` 映射（询价 / 交易 / 取消） | 不传（**待确认**是否与 Java 期望一致） |
| 发送前处理 | `protect_orders`（锁定字段）→ 缺上下文报错 → 期限归一 → `sanitize_order_list` | 缺上下文报错 → `protect_identity_lists` + `protect_orders` → `sanitize_close_order_req_vo` |
| 回执 | `receipt_guard` + `receipt_update`，原样透传 Java 回复 | 同左 |

## 2. 共享机制（两边都依赖，先读懂）

| 机制 | 位置 | 审阅要点 |
|---|---|---|
| 确认协议 | `app/execution/confirmation.py` | 7 条最终确认路径共用。`confirmation_action` 判定口令（出现疑问/否定/条件词就返回 None，要求恰好一个口令）；`parse_confirmation` 从引用消息里取单号、绑定"序号N"、解析用户的范围选择，产出 `Confirmation.order_ids`；`verify_scope` 在字段锁之后再校验一次范围。该文件几乎没有 docstring，正则密集，是**最值得逐行审**的文件之一 |
| 字段溯源与锁 | `app/extraction/locks.py::protect_orders`、`app/extraction/identity.py::prepare_identity_scope` | 业务节点产出 `FieldRecord`（value / source / evidence / origin / locked），发送前 backend 再按锁回滚被篡改的字段 |
| 错误处理 | `@safe_node`：异常写入 `state['error']`；`@io_node` + `add_io_node`：只读节点挂 RetryPolicy | 已核对：**所有写类节点都是 `@safe_node`，没有自动重试**，符合 ADR 0024 D3 |
| cascade | `graph.py` 的 `_route_after_*_intent`、询价子图和平仓子图内部的 `_route_or_end` | 已核对：每条条件边都先检查 error |

---

## 3. 期权开仓（`app/subgraphs/option/`）

### 3.1 意图 → 数据流

| 意图 | 意图判定 | 业务节点 | 是否调 LLM | 关键归一化/校验 | Java type / operate |
|---|---|---|---|---|---|
| `new_inquiry` 询价 | LLM | `build_inquiry_graph`：`inquiry_extract` → `inquiry_normalize` → `inquiry_submit`（extract_inquiry.py） | 是（原文候选 + 证据） | `expand_inquiry_items` 把期限 × 执行价做笛卡尔展开；`OptionOrderItem` 校验 | new_inquiry / 询价 |
| `place_order_from_quote` 请求下单 | LLM | `option_extract_place` → `place_params.parse_place_params_with_lineage` | 否 | `order_scope.selectors` 确定订单范围；逐单绑定参数与来源；`resolve_fast_execution` | place_order_from_quote / 交易 |
| `confirm_order` 确认下单 | **确定性**（intent.py:56-59） | `option_extract_confirm_place` | 否 | `parse_confirmation(allow_parameters=True)` → 复用下单解析 → `verify_scope` | confirm_order / 交易 |
| `cancel_order_request` 取消下单 | LLM，或确定性快速路径（intent.py:60-64） | `option_extract_cancel_place` | 否 | `extract_for_cancel_place`：**只取引用里的全部单号** | cancel_order_request / 取消 |
| `request_cancel_order` 请求撤单 | LLM | `option_extract_cancel` | 否 | 先查否定词，再用 `selectors` 收窄范围 | request_cancel_order / 交易 |
| `confirm_cancel_order` 确认撤单 | 确定性 | `option_extract_confirm_cancel` | 否 | `parse_confirmation(action="cancel")` → `verify_scope` | confirm_cancel_order / 交易 |
| `query_order_status` 查询 | LLM | `option_extract_query`（`@io_node`） | 否 | raw 里的单号优先，其次引用，都没有就是 `[None]` | query_order_status / 交易 |

### 3.2 建议阅读顺序与文件职责

1. `graph.py`：拓扑与路由表，5 分钟看完。
2. `intent.py` + `prompting.py` + `app/prompts/option/intent.md`：意图分类。重点看 LLM 之前的两条确定性快速路径。
3. `backend.py` + `sanitize.py`：出口，看懂 DTO 怎么装。
4. 简单节点：`extract_query.py` → `extract_cancel.py` → `extract_cancel_place.py` → `extract_confirm_cancel.py`，配合 `order_id.py`、`order_scope.py`。
5. 询价：`extract_inquiry.py` + `normalize.py` + `models.py`。
6. **最难的部分**：`extract_place.py` / `extract_confirm_place.py` → `place_params.py`（522 行）→ `provenance.py`。

| 文件 | 一句话职责 |
|---|---|
| `graph.py` | 子图组装：intent → 7 个业务节点 + `option_unknown` 兜底 |
| `intent.py` | 意图分类：确定性确认/撤单快速路径 + LLM + 证据校验 |
| `prompting.py` | PromptSpec 的 user 消息拼装 |
| `models.py` | 意图枚举、`OptionOrderItem` 等 Pydantic 契约 |
| `extract_inquiry.py` | 询价三段子图：LLM 候选 → 代码归一 → 调 Java |
| `normalize.py` | 名义本金、执行价、参与率、期权类型的归一化；询价展开 |
| `place_params.py` | 下单/确认下单的确定性参数解析，逐单绑定并记录来源 |
| `order_scope.py` | 单号正则、"序号N"映射、范围选择器（遇到不明确的范围时拒绝） |
| `order_id.py` | 按意图决定单号来源优先级 |
| `provenance.py` | 把 FieldRecord 绑定到 DTO 路径并加锁 |
| `backend.py` | 构造 Java DTO、加锁、调用、校验回执 |

`place_params.py` 的审阅提示：
- `_bound_order_inputs`（:368-429）用 group / bound / shared 三个可变状态把一条消息切成"每单一段"加"共享尾句"。
- `parse_place_params_with_lineage`（:432-506）内嵌约 60 行的 `append` 闭包，按"B 类字段取引用卡片、A 类字段取用户原文"合并。
- 这个模块没有独立的测试文件，只通过节点测试间接覆盖。

---

## 4. 期权平仓（`app/subgraphs/close/`）

### 4.1 意图 → 数据流

`close_intent`（intent.py:52-101）的顺序是：空 raw 判 unknown → `_deterministic_intent` 规则 → LLM + 证据校验 →
两条**事后改判**规则（:76-85）：模型判成查询但有合约编号和平仓动作词时改成下单；raw 含"撤单"时一律改成撤单申请。

| 意图 | 业务节点 | 是否调 LLM | 关键处理 | 传给 Java 的 `closeOrderReqVO` 字段 |
|---|---|---|---|---|
| `close_order_query` 持仓查询 | `close_holding_query`（`@io_node`） | 是 | `normalize_holding_candidates`：可平筛选、对手唯一子串匹配（匹配不到填 99999999）、枚举映射 | `contractQuery` |
| `close_order_request` 平仓下单 | `build_place_close_graph` 子图，见 4.2 | 是 | 见 4.2 | `closeOrderList` |
| `close_order_confirm` 确认平仓 | `close_confirm_close` | 否 | `parse_confirmation(product="close", action="close")` → `verify_scope` | `confirmOrderNoList` |
| `close_order_cancel_request` 撤单申请 | `close_cancel_close` | 否 | `order_id.extract_for_close_orders`；解析为空时退回会话记忆 `conversation_orders[-1]` | `cancelOrderNoList` |
| `close_order_cancel_confirm` 确认撤单 | `close_confirm_cancel` | 否 | 同确认平仓，`action="cancel"` | `confirmCancelOrderNoList` |
| `close_order_order_query` 平仓单查询 | `close_query_status`（`@io_node`） | 否 | **只看 raw**，不从引用取单号（与 option / swap 不同） | `queryOrderNoList` |

### 4.2 平仓下单子图（place_close.py）

```
parse ──▶ fetch_orders ──▶ extract ──▶ normalize ──▶ validate ──▶ submit ──▶ END
 (纯函数)   (只读IO,重试)   (LLM,重试)   (纯函数)       │              (写,不重试)
   │            │             │           │           └─▶ reject ──▶ END
   └────────────┴─────────────┴───────────┴── 任一步有 error ──▶ END（主图 render 走兜底文案）
```

| 步 | 做什么 | 产出 |
|---|---|---|
| parse | `reference_parser.parse_reference_message`：判断引用是"平仓结果卡"还是"持仓列表"，按"序号"切块，得到成功单、错误单、只能全平单和 holdingMap | `pc_parsed` |
| fetch_orders | `POST /admin-api/financial-orders/query-close-orders`，按单号和合约编号取可平数据；code≠0 时抛 ValueError | `pc_order_data` |
| extract | LLM 输出原文候选（不带 history），再 `verify_candidates` 校验证据 | `pc_candidates` |
| normalize | `execution_fragments` 拆分 "POV25" / "TWAP 13:00-14:00" → `normalize_place_candidates`（约 140 行）：身份绑定、金额/价格/POV/TWAP 归一、全平与否定、执行方式、加速意图、全平扩展、成功单追加 | `pc_close_orders` 或 `pc_reject_reply` |
| validate | 每条都要有 orderId 或 internalTradeId | 进入 reject 或 submit |
| submit | `build_close_order_req_vo` → `call_close_backend` | `api_code` / `api_result` |

### 4.3 建议阅读顺序与文件职责

1. `graph.py` → `intent.py`（重点看 :34-49 的规则和 :76-85 的事后改判）。
2. 三个确定性写节点：`confirm_close.py`、`confirm_cancel.py`、`cancel_close.py` + `order_id.py`。
3. `holding_query.py` + `normalization.py::normalize_holding_candidates`。
4. **最难的部分**：`place_close.py` → `reference_parser.py` → `execution_fragments.py` → `normalization.py::normalize_place_candidates` → `order_type.py`。
5. 出口：`aggregate.py` → `backend.py`。

| 文件 | 一句话职责 |
|---|---|
| `graph.py` | 子图组装：intent → 6 个业务节点 + `close_unknown` 兜底 |
| `intent.py` | 规则优先的意图识别，其余交给 LLM，再做事后改判 |
| `models.py` | 意图、持仓查询、平仓下单的 Pydantic 模型 |
| `place_close.py` | 平仓下单子图（7 个节点） |
| `reference_parser.py` | 引用消息解析（纯函数） |
| `normalization.py` | 候选原文 → 最终参数（身份、金额、比例、时间、方式、全平）；持仓过滤条件 |
| `order_type.py` | 执行方式短语归一化，处理否定、条件和冲突 |
| `execution_fragments.py` | 把复合执行方式候选拆成独立字段 |
| `order_id.py` | CO- 单号正则与撤单范围解析 |
| `aggregate.py` | 组装 `closeOrderReqVO`，清洗字面量 "null" |
| `backend.py` | close 域统一出口 |
| `merge.py` | **生产无引用**，只剩测试在用（见 6.2） |

---

## 5. 问题清单

编号规则：O = 开仓，C = 平仓。"已复现"表示用只读 Python 片段实测过。

### 5.1 高：影响交易参数或操作范围（建议先修）

> 2026-09-24 更新：C1–C3 已按 TDD 修复（`close/order_id.py`），用例见 `tests/subgraphs/close/test_confirm_cancel_close.py::TestCloseCancelCloseNode` 与 `test_confirm_cancel_query_status.py`。
> O1、O2 已修复：`option/place_params._POV_RATIO_RE` 识别「跟量N%」且排除金额；询价期权类型支持「…期权」后缀，看跌 / put 等不支持类型明确回复而非兜底（用例见 `test_extract_place.py`、`test_normalize.py::TestNormalizeOptionType`、`test_extract_inquiry_graph.py`）。
> O3、O4、C6、C7 已修复：范围词需带量词（最后一笔 / 前两笔），「前收盘价」「最后半小时」不再被拒；被否定的下单方式关键词不参与判定；全平只在否定全平本身时取消；「不超过 / 不低于」等价格约束不算执行方式否定。
> O6、O7 已修复：引用撤单回执再回复「撤单」判 request_cancel_order（对齐提示词规则3与 case-029）；带参数的「确认修改」判 place_order_from_quote，裸「确认修改」仍为 unknown；询价中给出但无法解析的执行价格 / 名义本金 / 参与率提示修正、不调 Java。
> C8 部分修复：中文数字解析失败不再编造为 0、叠加前缀（平仓名义本金200万）可解析。0 / 负数 / 超额 / 缺可平金额按 `test_amount_policy_is_delegated_to_java` 的既有约定交给 Java 校验，未改动，如需本地拦截请业务确认。
> O5 已修复（业务裁决：取消下单只取消引用里的订单，raw 指定第N笔 / 序号 / 单号时只取消指定的几笔，指向引用外订单或范围不明时拒绝）。C9 已裁决：取可平数据失败不向客户展示 Java 原文，维持统一兜底文案，由 `test_fetch_failure_never_shows_java_text_to_customer` 锁定。
> O8、C5、C8 已按业务裁决修复：1kw = 1000 万（询价 / 下单 / 平仓一致）；点名了具体订单时「全部平仓」只作用于被点名的订单，写了「B，全部平仓」才带上 B；0 / 负数平仓金额本地拦截并提示，超额金额仍交给 Java 判断。
> C4 已修复（`close/intent.py::_is_cancel_instruction`：否定或查询语义不再强制改判），用例见 `tests/subgraphs/close/test_intent.py::TestCancelKeywordOverride`；`cancel_close.py` 的会话记忆兜底仍待业务确认，未改动。

| # | 问题 | 位置 | 复现 | 建议 |
|---|---|---|---|---|
| O1（**已修复**） | "跟量20%" 被当成执行价，覆盖引用卡片里的执行价并锁定；POV 比例丢失 | `option/place_params.py:274-277`（`_raw_strike` 只剔除带 "pov" 字样的比例） | **已复现**：引用卡片"执行价格：100%" + raw "跟量20% 100万" → `strike_percentage=20.0, order_type=POV, pov_ratio=None` | `_raw_strike` 与 `fast_execution._EXPLICIT_POV_RATIO` 统一口径；补 RED 用例 |
| O2（**已修复**） | 询价的期权类型只识别 "call"、"看涨"；"看涨期权"、"看跌"、"put" 原样透传，被 `OptionOrderItem` 枚举拒绝，用户只看到兜底文案 | `option/normalize.py:138-144`、`models.py:62` | **已复现**：`normalize_option_type("看跌") == "看跌"` | 先与业务确认看跌是否支持：不支持就给出明确回复，支持就补齐映射 |
| C1 （**已修复**） | 平仓撤单按合约编号选错订单：`_quote_mapping` 把合约编号映射到**前面**最近的单号，而 Java 卡片版式是"序号 → 合约编号 → 单号" | `close/order_id.py:126-141` | **已复现**：两笔卡片，"撤单OPT-BBBB2" → `['CO-…AAAAAAAA']`（第一笔） | 复用 `confirmation.py:247-270` 已经正确处理的绑定逻辑 |
| C2 （**已修复**） | 平仓撤单不识别"序号N"，范围扩大到引用中的全部订单 | `close/order_id.py:57-60, 102-110` | **已复现**："撤序号2" / "撤单 序号2" → 两笔都撤 | 同上；违背模块 docstring 里"绝不扩大范围"的约定 |
| C3 （**已修复**） | 平仓撤单的单号正则不区分大小写的说法不成立，小写单号被忽略，范围扩大到全部 | `close/order_id.py:28`（无 `re.I`，docstring :9/:27/:82 却写"大小写不敏感"） | **已复现**："撤 co-20260921-bbbbbbbb" → 两笔都撤 | 加 `re.I` 并统一 `.upper()`；现有测试 `test_extracts_raw_ids_upper_and_deduped` 因同句带大写副本而误通过 |
| C4（**已修复**） | raw 里只要有"撤单"就强制改判为撤单申请，不看否定和查询语义；叠加 C2 和会话记忆兜底，可能误发撤单申请 | `close/intent.py:82-85`、`cancel_close.py:56-64` | 代码确认：例如"不要撤单"、"查询撤单状态" | 改判前先检查否定和查询语义；补测试 |

### 5.2 中：误拒、静默丢值、口径冲突

| # | 问题 | 位置 | 说明 |
|---|---|---|---|
| O3（**已修复**） | 范围检查误伤正常下单：`(?:前\|后\|剩余\|余下)[^，,；;。]*[笔单条个]` 和 "最后" 在任意位置生效 | `option/order_scope.py:103-110` | **已复现**："按前收盘价限价下单 100万" → "无法确定指定订单范围" |
| O4（**已修复**） | 订单类型不识别否定：按关键词优先级做包含判断 | `option/place_params.py:82-94` | **已复现**："不限价，市价下单" → `限价单` |
| O5（**已修复**） | 取消下单完全忽略 raw 里的范围，总是取引用里的全部单号；请求撤单则有收窄和拒绝 | `option/order_id.py:46-48` | 引用两单时"取消第2笔"会两单都取消；**待业务确认** |
| O6（**已修复**） | intent 的确定性快速路径与提示词冲突：raw 和 quote 都含"撤单"就判 `cancel_order_request`（operate="取消"），而 intent.md 规定判 `request_cancel_order`；"确认修改…" 被判 unknown，而提示词说改参数归 `place_order_from_quote` | `option/intent.py:56-64` | 这条快速路径没有测试 |
| O7（**已修复**） | 询价中执行价、名义本金、参与率解析失败时静默变 None，仍然提交；期限失败时却会拒绝，两者口径不一致 | `option/extract_inquiry.py:99-111` | **已复现**：`normalize_notional("1,000,000") is None` |
| C5（**已修复**） | "A，全部平仓" 会把 fullCloseIds 里的 B 也置为全平 | `close/normalization.py:181-183, 286-294` | 已有测试把"A平200万，全部平仓"带上 B 视为设计意图；只指一笔的边界**需业务确认** |
| C6（**已修复**） | 全平的否定判断过宽：evidence 里出现任何"不"字就判否定 | `close/normalization.py:244` | "全部平仓，不用跟量" 会被拒 |
| C7（**已修复**） | 执行方式否定窗口过宽：执行方式词前 8 个字符内出现"不"就判否定 | `close/order_type.py:30-32` | **已复现**："价格不超过10块限价" → `CloseOrderTypeNormalizationError(negated)`，用户只看到兜底文案 |
| C8（**已修复**） | 金额解析：解析失败得 0；保留金额 ≥ 可平金额时静默置 None 后仍提交；负数可以通过；"平仓名义本金200万" 抛 ValueError | `close/normalization.py:47-95` | 见 C 报告实测 |
| C9（**已裁决：不展示**） | 取单接口 code≠0 时抛 ValueError，Java 原文被兜底文案覆盖 | `close/place_close.py:112-113` | 与 CLAUDE.md "如实透传后端响应"的精神有张力，**待确认** |

### 5.3 待业务确认（不一定是 bug）

- **O8（已修复：1kw = 1000 万）** 名义本金 `kw` 按 1 万换算（`option/normalize.py:39`，测试也这样断言）。口语里常指"千万"，属于金额量级风险。
- **C10** TWAP 只校验 H≤23、M≤59，不校验开始早于结束，也不换算上下午："2:00-2:30" 归一为凌晨。POV "25%" 得 25，"0.25" 得 0.25，全部交给 Java 判断。
- **C11** 平仓结果卡作为引用时，未涉及的成功单会整体追加并重新提交（`normalization.py:296-300`）。
- **C12** 平仓 DTO 不传 `operate` 字段，而开仓会传。
- **O9** 请求撤单、取消下单在没有单号时仍发送 `orderList=[{"orderId": None}]`，是否拒绝完全依赖 Java。

### 5.4 低

- 单号正则有多套口径：`confirmation._IDS`（带边界、大写）、`option/order_scope.ORDER_ID_RE`（不做 upper）、`close/order_id.ORDER_ID_RE`（无边界、无 `re.I`）、`reference_parser.ORDER_ID_STRICT_TOKEN`（8 位以上十六进制）、`route_rules` 的 `Q-\d{8}-\d{10}`。
- 各 extract 节点写成 `{"field_records": records, ..., **backend}`：backend 在锁拒绝时带回的 `field_records` 会覆盖节点自己的全部溯源记录（`option/extract_place.py:61-66` 等）。
- `option/order_id.py:38` 的否定正则中 `\S*` 能跨越中文逗号："撤单，不行的话联系我" 被判为否定。
- `option_extract_query` 是 `@io_node`，而 `IO_RETRYABLE` 包含 ValidationError / EvidenceError，确定性失败会被无意义地重试。只读，风险低。
- `reference_parser.py:31` 的结束标记是"若以上订单执行平仓操作"，fixtures 里的实际文案是"若要对以上订单执行平仓操作"。
- `aggregate.py:66-72` 直接读 `os.environ["NULL_LITERALS"]`，没有走 `get_settings()`。

**对照 CLAUDE.md 规则的结论**：没有发现提示词硬编码、手工解析 JSON、直接用 httpx、伪造成功卡片或写节点自动重试。
有两点需要注意：
- 多处依赖 Java 卡片文案（`place_params._LABEL_TAIL`、"本群可选交易对手列表"、"请引用|例如|如只确认"等模板排除正则），Java 改文案后会静默失效。
- `normalization._ENUMS`、`order_type._ALIASES`、哨兵值 99999999 是固定的枚举映射，不是会膨胀的业务字典，不构成 P0 违规，但属于魔法常量。

---

## 6. 可读性清理清单（不改行为，适合单独一个 `refactor` / `docs` PR）

### 6.1 过时或误导的注释

| 位置 | 问题 |
|---|---|
| `option/intent.py:10`，以及多处 `get_qwen_structured` / `get_qwen_thinking` | 函数名是 Qwen，实际是 DeepSeek-V4-pro；`get_qwen_thinking` 实际关闭了 thinking（`app/llm/clients.py:102-105`） |
| `option/models.py:10-16, 68`、`option/backend.py:27-29`、`option/sanitize.py:3` | 引用的 `spec/llm_schemas.txt`、`spec/code_nodes/…` 在仓库中不存在 |
| `option/models.py:73, 102`、`option/sanitize.py:13-14` | 仍描述 LLM 提取 / "避免 LLM 吐 null"，下单链路已不调 LLM |
| `option/order_id.py:11` | 说确认撤单用 `extract_for_confirm_cancel`，实际用 `parse_confirmation` |
| `close/order_id.py:1-21, 182` | 说确认类也用 `extract_for_close_orders`（实际只有撤单申请在用），还写着"大小写不敏感"（不成立） |
| `close/confirm_cancel.py:1` | 模块 docstring 与 `confirm_close.py` 一字不差，是复制粘贴 |
| `close/__init__.py:4`、`close/graph.py:5` | "7 节点 / 7/7 真节点"与实际（8 个节点，另有 7 节点的 place_close 子图）不符 |
| `close/models.py:83` | "与 Dify place_close.md JSON schema 完全对齐"已过时（ADR 0023 以后由 `Field(description=)` 承担） |
| `app/prompts/option/intent.md` | 引用不存在的"规则0"（:86、:118）；"硬性否决自检"缺第 1 条；:78 仍提改单流程；:67 把看跌/put 作为询价标志，与枚举冲突 |
| `app/prompts/option_close/intent.md` | 章节编号有空洞（缺 4、缺规则 2），仍在描述已由代码前置处理的确认类判定 |

### 6.2 死代码与兼容层（已 grep 确认无生产引用）

- 开仓：`intent.py:38 _build_user_message`（仅测试引用）、`backend.py:41 _message_id`、`provenance.py:13 use_memory_orders`、
  `place_params.py:195 _extract_short_name`、`place_params.py:352 history_texts`、`prompting.py:15 extract_user`、
  `order_id.py:51 extract_for_confirm_cancel`（仅 `scripts/export_node_migration.py` 的过时映射引用）、
  `backend.py` 的 `option_rfq` 参数（仅测试传入）。
- 平仓：`merge.py` 整个文件（逻辑已由 `normalization.py:296-300` 取代）、`order_id.py:81 is_order_id`、`backend.py:33 _message_id`、
  `intent.py:45-46`（被 :37 的 `confirmation_attempt` 提前拦截，永远走不到）。

### 6.3 重复实现（建议收敛到 `app/extraction/`）

- 中文数字解析至少 6 份：`confirmation._number` 与 `option/order_scope._number` **逐字相同**；另有 `close/order_id._ordinal_value`、
  `close/normalization._number`、`swap/order_id._number`、`extraction/tenor._cn_number`。
- "序号N → 单号"绑定有 3 套：`confirmation.parse_confirmation`、`option/order_scope.quote_sequence_map`、`close/order_id._quote_mapping`，
  **C1、C2 的根因就在于第三套与前两套不一致**。
- "null" 字面量清洗 3 份：`option/sanitize.py`、`close/aggregate.py`、`swap/prewash.py`。
- 两个 `graph.py` 都把同一组节点名在路由表、条件边映射、END 边列表里重复写了三遍。

### 6.4 复杂度热点

- `close/normalization.py::normalize_place_candidates`（约 140 行，嵌套深），建议拆成：身份绑定 / 参数归一 / 全平处理 / 成功单合并。
- `option/place_params.py::parse_place_params_with_lineage` + `_bound_order_inputs`，建议补独立的单元测试文件。
- 两处 `_route_or_end` 用 `# type: ignore[no-untyped-def]` 压掉了缺失的返回类型。

---

## 7. 测试缺口（每条都可以直接写成 RED 用例）

| 对应问题 | 缺少的用例 |
|---|---|
| O1 | "跟量20%" / "跟量25" 配合带执行价的引用卡片：执行价应保持不变，`pov_ratio` 应被正确提取 |
| O2 | 询价"看涨期权"、"看跌"、"put" |
| O3 | 反向用例："按前收盘价限价下单"、"最后一笔"作为普通措辞时不应被拒 |
| O4 | "不限价，市价下单" |
| O5 | 取消下单时 raw 指定"第2笔" |
| O6 | `deterministic_cancel` 快速路径；`_INTENT_TO_OPERATE` 映射断言 |
| O7 | 询价中执行价或本金解析失败 |
| C1–C3 | 平仓撤单：Java 版式卡片按合约编号撤、"序号N"撤、只有小写单号 |
| C4 | "不要撤单"、"查询撤单状态" 的意图 |
| C6、C7 | "全部平仓，不用跟量"、"价格不超过10块限价" |
| C8 | `_amount` 的异常输入（"."、负数、"平仓名义本金200万"） |
| C9 | fetch 返回 code≠0 或结构错误 |
| 其它 | `extract_confirm_place.py:59-60` 的范围不一致分支；`extract_confirm_cancel` 只有 3 条用例；`execution_fragments` 没有直接单测；`test_merge.py` 测的是死代码 |

---

## 8. 人工审阅 checklist

审阅这两个子图的新改动时，逐条过：

- [ ] 写类节点是否仍是 `@safe_node`（不是 `@io_node`），没有自动重试
- [ ] 新增的条件边是否先检查 `has_error(state)`
- [ ] 用户可见的回复是否来自 Java 回执；本地只允许"拒绝 / 澄清"类文案，不允许伪造成功卡片
- [ ] 订单范围是否只会**收窄**、不会**扩大**：解析失败时应拒绝，而不是回退到"引用中的全部订单"
- [ ] 新正则：是否处理大小写、词边界、否定窗口（不要跨越标点）、中文数字
- [ ] 是否又新写了一份中文数字、单号或序号解析？应优先复用 `app/execution/confirmation.py` 或 `app/extraction/`
- [ ] 归一化失败时是明确拒绝，还是静默变成 None 或 0 后继续提交？
- [ ] 新字段是否写了 `FieldRecord`（evidence / origin / locked），并且没有被 `**backend` 覆盖
- [ ] docstring 是否与实际行为一致（是否调 LLM、节点数量、引用的文件是否存在）
- [ ] 提示词改动是否与代码里的确定性规则冲突（例如 intent 的快速路径和事后改判）
