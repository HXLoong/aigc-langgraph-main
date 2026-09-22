# tests/ 测试脚本评估 · 按 LangGraph 原生架构口径

- 日期：2026-09-22
- 基线：`main` @ `f1e205f`（PR #214 合入后；本地分支与 origin/main 同 sha）
- 口径：[ADR 0024](../adr/0024-langgraph-native-rearchitecture.md) D2–D7 + `.claude/rules/{langgraph-patterns,testing}.md` + `tests/CLAUDE.md` + 根 `CLAUDE.md` 核心原则 7（标的原文交后端）
- 方法：主评审实跑 pytest / ruff / collect 取事实；三路并行只读审查（图-State-节点层 / 三个业务子图层 / API-工具-可观测-脚本层），每条结论附 `file:line`，关键结论由主评审复核
- 范围：236 个 `test_*.py`（2461 个用例）+ `tests/fixtures/`

## 一、执行摘要

**总评：测试体系的"内核"已经是 LangGraph 原生的，但"外壳"与"守护"失效。** reducer / per-turn 重置 / 幂等 / RetryPolicy 读写分界 / evidence 契约 / Mock 纪律这些 ADR 0024 要求的能力都有真实测试钉住，且写法（mock 到 `with_structured_output`、`MockTransport` 注入真实 Client、真子图 cascade）符合原生范式。但当前 HEAD 上**主入口 `app.main` 无法 import**，CI 自 2026-05-12 起不自动触发，所以一次没有同步清理测试的重构（2026-09-20 ticker 迁 Java）让 31 个用例失败、13 个文件无法收集，而没人发现。

### 实跑结果（干净环境，`.env.example` 作配置）

| 项 | 结果 |
|---|---|
| 收集 | 2461 用例，13 个文件收集失败 |
| 执行 | 2649 passed / **31 failed** / 2 skipped / **13 errors**，45.6s |
| 无 `.env` 时 | **37 个文件收集失败**（Settings 5 个必填字段缺失） |
| ruff `tests/` | 2 个 I001 |
| `python -c "import app.main"` | **ModuleNotFoundError: app.subgraphs.ticker** |

### 评分卡（5 分制）

| 维度 | 分 | 一句话 |
|---|---|---|
| 图级 vs 函数级 | **3** | 入口 / 拓扑 / cascade 有真图守护（≈40 条主图 + 各子图 10–12 条）；`tests/nodes` 144 条全函数级；主图与 option/close 路由函数无纯函数单测 |
| State 契约（D2） | **4** | 四个 reducer + per-turn 重置 + `expected_action` 顶层化全覆盖；缺"子图越权写父图路由键"的运行级用例 |
| 持久化（D4） | **3** | InMemorySaver 真多轮、幂等回放、`durability="exit"` 到位；真 MySQL 三条 opt-in 两套开关 + CI 无 service = 死测试 |
| RetryPolicy / io_node（D3） | **3.5** | 读写清单 + 真子图 `await_count==2` 行为证明；清单漏 `plan_instructions`，无"每节点必须归类"完整性断言 |
| 可观测（D5） | **4** | session / user / trace_id / elapsed_ms / decision / LLM 指标 / 软硬 ready 全有行为断言；`TraceEntry` 字段级脱敏无实现无测试 |
| 评估台（D6） | **3.5** | B 方言 / REJECTED 桶 / 早停记失败 / dry-run 四象限全钉住；写类 case `expected.place_params` 全库 0 条 |
| 协议（D7） | **2** | `/v1/runs` 未实现，测试只测 Dify wire 形态，无 adapter 标记 |
| Mock 纪律 | **4.5** | 使用点 patch、structured_output mock、零 conftest autouse、零真网络；10 处 LLM 守卫空转、2 处死守卫 |
| 过期与残留 | **1.5** | 引用已删 ticker 模块、render 旧分支断言、CI 关闭、Dify 口径 ≥ 14 处、932K 零消费 fixture |
| 组织 | **2** | 根目录 79 文件平铺（41 app / 11 harness / 23 scripts）、render 测试 9 文件 2 目录且期望不一致、close 路由四文件三重重复、文档目录不符 |

## 二、P0（阻断）

**P0-1 · 主入口不可 import，13 个测试文件收集失败**
`app/node_execution/registry.py:51` `from app.subgraphs.ticker import resolver as ticker`；该包已于 `2f9ce65`（2026-09-20，标的识别委托后端）删除，而 PR #211（`fa2c55d`）合入的 `registry.py` 未随之调整。`app/main.py:27-28` import 它，因此 `app.main`、`tests/test_api.py`、`test_api_idempotency.py`、`test_checkpointer_wiring.py`、`test_dify_wire_contract.py`、`test_inquiry_continuation.py`、`test_intent_persistence.py`、`test_nodes_{execution,prepare,run_api}.py`、`test_request_deadline.py`、`observability/test_{health_probes,http_metrics_middleware}.py`、`integration/test_nodes_persist_mysql.py` 全部收集失败；另 5 条用例运行期同因失败（`test_logs.py`、`test_database_config.py`、`test_http_tape.py`×2、`tools/test_http_pool.py`）。`tests/test_nodes_execution.py:24`、`tests/test_nodes_prepare.py:18` 也直接 import 该模块；`docs/nodes-run.md:5` 仍宣称"ticker 7"。
改法：从 `registry.py` 摘除 ticker 7 项与 `OrgItemState`，同步删两处测试 import 与文档计数；补一条"registry 所有 callable 可 import 且节点名集合稳定"的冒烟测试（harness 侧 `callable_path` 惰性字符串同样需要）。

**P0-2 · CI 无自动触发，所有守护无强制力**
`.github/workflows/ci.yml:3-6` 仅 `workflow_dispatch`（注释"2026-05-12 暂停"），`:53-60` 只有 `pytest tests/ -v`，无 fast/slow 分层、无 harness、无 MySQL service。ADR 0024 D8 阶段 0 门槛"CI 在 PR 上跑"未达成，是 P0-1 与下面 P1-1 能合进 main 的直接原因。
改法：恢复 `push` + `pull_request`；fast job = ruff + `check_fixture_consistency` + `check_adr_refs` + `pytest -k "not e2e"`（< 2 min）；slow job = 全量 + `services: mysql` + `python -m harness run --backend dry-run`。

**P0-3 · `tests/api/` 明文内网地址与 GOATS 凭据，且会真实下单**
`tests/api/_utils.py:10-20`、`tests/api/test_gotats_endpoints.py:17-26`：内网 `BASE_URL`、已删 Dify 网关地址、`CLIENT_SECRET` / `SALT` / 真实 agent id 明文。24 个文件是 import 即发 HTTP 的手工脚本（无 `def test_`、无 assert，`run_all.py:23-38` 自建 runner），`test_12_trs_order.py:8-13` 会真实下单。只靠 `pyproject.toml:65` `--ignore=tests/api` 掩盖，任何人显式运行即真实写入。违反根 `CLAUDE.md`"绝对禁止硬编码 API Key / Secret"。
改法：revoke 凭据；整目录迁 `scripts/probe_goats/`，凭据走 `get_settings()`，写类探针加 `--confirm-write`；删除 `--ignore`，让"tests/ 下一律可被 pytest 跑"成为不变量。

## 三、P1（本周期应修）

1. **render 旧分支断言未随重构清理（20 条 FAIL）**。`2f9ce65` 删除了 render 的 `hitl_card` / `zero_match` 本地标的卡片分支（现役 decision 集合：`api_result` / `backend_no_result` / `error:*` / `no_reply` / `passthrough` / `trace` / `unknown_intent`），但 `tests/test_render.py` 与 `tests/nodes/test_render_{decision,close_card,option_confirm,swap_complete_fields,unknown_intent}.py` 仍断言旧 decision 与旧文案（`换种说法` / `互换服务未返回有效结果`）。同一分支期望在 `tests/test_render.py:138` 与 `tests/nodes/test_render.py:233` 不一致。改法：以 `test_render_decision.py` 为权威、按现役 decision 重写并归并 9 个文件到 `tests/nodes/`。
2. **真实缺陷被测试抓住但未修**：`tests/graph/test_state_schema.py` 报 `AgentState` 重复声明 `conversation_orders`（`app/graph/state.py:258` 与 `:261`）；`tests/graph/test_failure_recovery.py` swap 并行分支失败汇合断言与 `_route_after_place_order` 现状不符；`tests/observability/test_node_labels.py` 节点目录未覆盖 `add_io_node` 生成的 `__error_handler__*` 节点，且 `from scripts import langfuse_eval` 路径过期（已迁 `scripts/langfuse/`）；`tests/test_check_adr_refs.py` 报 ADR 0008 引用已删路径。
3. **37 个文件在无 `.env` 时不可 import**。根因 `app/nodes/render.py:21` `_ERROR_REPLY = get_settings().default_reply` 模块级求值，测试模块级 import `app.main` / `render` 即触发 Settings 校验。违反 `.claude/rules/testing.md`"所有测试必须 import 时能成功"。改法：render 改为调用期取配置；或 `tests/conftest.py` 用 `monkeypatch.setenv` 的**显式** fixture 提供最小 Settings（不是 autouse 绕业务路径）。
4. **10 处"禁止调 LLM"守卫空转**。`monkeypatch.setattr(module, "get_qwen_thinking", _forbid, raising=False)` 打在目标模块不存在的名字上（`app/subgraphs/option/extract_*.py`、`close/{confirm_close,cancel_close,confirm_cancel,query_status}.py` 中 `get_qwen*` 出现 0 次），`raising=False` 吞掉了信号。证据：`option/test_extract_place.py:45-48` 等 6 个 extract 文件、`option/test_graph_routing.py:64-67`、`close/test_confirm_cancel_close.py:35-38`、`test_confirm_cancel_query_status.py:25-28`、`test_graph_routing_extended.py:26-36`。改法：删 `raising=False`，或改为断言模块无 LLM 工厂符号。
5. **两处死守卫**：`TickerClientHttpx` 在 `app/` 业务代码零引用（仅 `app/tools/__init__.py:40,68` 导出），`swap/test_multimodal_evidence.py:31-32`、`tests/test_backend_instrument_boundary.py:24-32` 的 `assert_not_awaited()` 恒真；后者 `:27-31` 用 `hasattr` 守 `resolve_ticker_full` / `resolve_ticker`，两个名字已不存在。改法：改为 `app/subgraphs/**` 导入面断言（禁止再引入本地证券解析）。
6. **RetryPolicy 清单漂移且无完整性断言**：`tests/graph/test_retry_policy.py:143-153` 列 18 个读节点，实际 `add_io_node` 注册 19 个，漏 `plan_instructions`（`app/graph/main.py:113`）；`:189-199` 只校验白名单内节点，新增写类节点被误挂 RetryPolicy（= 超时重发下单）不会被发现。改法：断言 `set(builder.nodes) - 子图节点 == READ | WRITE | PURE`。
7. **真 MySQL 用例永不执行**：`tests/integration/test_shared_mysql.py:15`、`test_request_replay_mysql.py:12`、`test_nodes_persist_mysql.py:19` 三条 opt-in 且用两个不同开关（`RUN_LOCAL_MYSQL_TESTS` / `RUN_NODE_MYSQL_TEST`），CI 无 service。ADR 0024 D4"至少一条 `AIOMySQLSaver` 真实多轮用例"未落地。
8. **D6 写类 case `expected.place_params` 全库 0 条**：`tests/fixtures/categories/*.jsonl` 与 `unified_golden.jsonl` 零命中；`scripts/check_fixture_consistency.py` 与 `harness/differ.py` 零 lint / 零比对。评估门对写类链路只靠 `response_contains` 文本。范本：`swap/test_fresh_counterparty_graph.py:113-164`（真子图 + 逐字段断言真实 HTTP payload + 断言 fixture 未被改写）。
9. **Dify 口径残留 ≥ 14 处**（违反 ADR 0024 D1"断言以业务正确性为口径"）：断言理由写"与 Dify 一致"的 `swap/test_graph_routing.py:140`、`close/test_backend.py:61`、`swap/test_aggregate.py:171`、`swap/test_prewash.py:95`；测试名含 Dify 的 `close/test_backend_boundary.py:198`、`swap/test_counterparty_completion.py:48`、`nodes/test_fast_query.py:217`、`test_reply_contract_20260920.py:73,125,158`；指向已删源的 `nodes/test_route_rules.py:3`（`dify/yaml/主干工作流.yml`）与 5 个 docstring 指向已删 `spec/code_nodes/*.py`（`close/test_{reference_parser,backend,aggregate,merge}.py:3-4`、`swap/test_aggregate.py:7`）；`test_shadow_compare.py:96-97`"Dify 输出可能 camelCase"。
10. **close 路由测试四文件三重重复 + 误导断言**：`test_graph.py` / `test_graph_routing.py` / `_extended` / `_p0` 中"unknown → close_unknown"重复 3 遍；`_extended:105-109` 名为"未实现意图走 todo"，但两个意图早有真节点且 `close_todo` 已删；6 处 `assert "*_todo" not in trace_nodes` 断言不存在的节点名（`close/test_graph_routing.py:76`、`_extended:72,99`、`_p0:77`、`option/test_graph_routing.py:109`、`swap/test_graph_routing.py:266`）。同时 `close_order_cancel_confirm` / `close_order_order_query` 与 swap `swap_cancel` / `swap_query_order` 从未在真子图上跑过。
11. **假 e2e**：`tests/nodes/test_ingest_reset.py:87-112` 类名与 docstring 称"走完整图"，实际 `build_main_graph(cp)` 结果被丢弃，只调一次 `ingest`。
12. **两套节点注册表并存无 ADR**：`harness/node_registry.py`（PR #214）与 `app/node_execution/registry.py`（PR #211）各自维护节点清单、各有一组测试（`test_node_*` 测 harness、`test_nodes_*` 测 app），与 D6"harness 唯一 gate"并列；ticker 漂移已证明两表必然失步。
13. **D7 零覆盖**：`app/api/` 无 `wire/`，`routes.py:1,51,120` 仍以 `DifyWorkflowRunRequest` 为主实现；测试只测 Dify 形态（`test_dify_wire_contract.py`、`test_api.py:66-130`、`test_api_turn_inputs.py:95`），无一条标记"回滚期 adapter"或钉 `/v1/runs` 契约。
14. **主图条件路由无纯函数单测**：`app/graph/main.py:41,48,64` 的 `_route_after_ingest/_intent/_plan` 无单测（对比 swap 六个 router 在 `swap/test_graph_routing.py:37-43,113-231` 全覆盖）；option `_route_after_option_intent`、close `_route_after_close_intent` 同样缺。
15. **`SubgraphOutput` 无运行级越权用例**：`tests/graph/test_subgraph_contract.py:24-28` 只断言通道集合，无"子图节点写 `product_type`，父图值不变"的 ainvoke 用例；三个业务子图目录内零守护。

## 四、P2（择机）

- `tests/graph/test_reducers.py:62` 或断言（`A == X or A == Y`），窗口语义未钉死。
- `tests/tools/test_client_unreachable.py:32-39` 全局 patch `httpx.AsyncClient.__init__`，应改用各 Client 的 `transport=`（`test_http_pool.py:42` 为范本）。
- 6 处 patch 类方法而非使用点名字：`swap/test_confirmation_protocol.py:29`、`close/test_graph_routing*.py`、`close/test_backend.py:24-26`、`close/test_place_close_graph.py:39-51`（目标模块根本不调 `operate`）。
- `from_goats=True` 夹具 8 处（`swap/test_select_chain.py:217,288`、`test_selection_rules.py:31`、`test_selection_evidence.py:21`、`tests/test_render.py:133`、`nodes/test_render_decision.py:64`、`test_render_backend_rejection.py:15`、`test_nodes_run_api.py:130`）与 `CLAUDE.md` 原则 7"不标记 from_goats" 冲突；stale docstring `swap/test_place_order.py:150,191,227`、`option/test_extract_inquiry.py:168,204,212` 仍叙述本地 resolver。
- `swap/test_place_order.py:37-107` 与 `swap/test_models.py:88-244` 模型测试逐条同名重复；`option/test_extract_inquiry.py:185-186` 同一断言写两遍；`tests/graph/test_session_expiry.py` 被 `test_entry_route_guard.py:44-75` 完整覆盖。
- `tests/test_option_close_fixtures.py:17,52-54` 硬编码 case 集合与逐轮文案，新增用例必 RED（冻结数据而非守契约）。
- `tests/graph/test_business_params.py:71-100` 用 `read_text()` 查源码字符串，重命名即假绿。
- 脱敏默认关（`observability/test_privacy.py:34-37`），D5 要求的 `TraceEntry` validator 字段级脱敏无实现无测试。
- `tests/fixtures/old_typing/` 932K / 1412 条零消费；`tests/fixtures/nodes/` 仅 README，`harness/README.md:21` 的 `node-run --data tests/fixtures/nodes` 无数据可跑。
- 6 处 `sys.path.insert`（`test_promote_langfuse_prompt.py:10`、`test_canary_status.py:7`、`test_metrics_snapshot.py:7`、`test_shadow_compare.py:8`、`test_probe_real_backend_e2e.py:27`、`test_alert_threshold_lint.py:22`），`pyproject.toml:63` 已有 `pythonpath=["."]`。
- 日期后缀文件名 4 个（`test_confirmation_protocol_20260920.py` 等）承载的是长期契约，应语义命名并按域归位。
- ADR 0023 ".md 无 JSON 骨架" 只在 `app/prompts/spec.py:7` 注释，无 lint。
- shadow_compare 状态矛盾：ADR 0024 附录 C 级删除 vs `CLAUDE.md:6` / `scripts/CLAUDE.md:32` 就绪能力，测试与技能都在。
- 文档漂移：`tests/CLAUDE.md:14` 列 `subgraphs/ticker`（不存在）、`:17` 列 `test_e2e.py`（不存在）；`.claude/rules/testing.md:33` 仍写 `app/subgraphs/ticker`；`CLAUDE.md:98`"1864 passed + 15 skipped"与实测不符；`docs/testing/README.md` 仍以 `scripts/ai_test_langgraph/` 为联合验收入口（ADR 0024 已标 deprecated）。
- 环境：干净机器 `pip install -e .[dev]` 后系统 `cryptography` 41（debian 包）触发 pyo3 panic，须 `--ignore-installed` 重装，仓库无说明。

## 五、亮点（应作为后续测试的范本）

1. **拓扑当契约测**：`tests/graph/test_entry_route_guard.py:18-27`（出边数量与目标集合）、`tests/graph/test_subgraph_contract.py:17-21`（`isinstance(graph.nodes[name].bound, CompiledStateGraph)` 钉住原生嵌入）、`close/test_place_close_graph.py:60-69`（拓扑 + output_schema + `pc_*` 不外泄）、`option/test_extract_inquiry_graph.py:34-38,84-95`（三条管线各自 trace 序列 + 快速询价不调 LLM）。
2. **写类节点绝不重试有三重守护**：`tests/graph/test_retry_policy.py:196-199`（逐个 `retry_policy is None`）+ `:99-115`（耗尽落 `error:retry_exhausted`）+ `:132-139`（`add_io_node` 拒绝非 `@io_node`）；三份 `test_intent_cascade.py:74-80` 在真子图上用 `await_count == 2` 行为级证明。
3. **Mock 纪律教科书级**：LLM 统一 mock 到 `with_structured_output` 返回对象（`test_cascade_e2e.py:42-46`）；client 在所有使用点 patch（`test_inquiry_continuation.py:99-110`、`close/test_backend_boundary.py:44-48` 同时 patch 两个使用点）；`httpx.MockTransport` 注入真实 Client 断言真实 wire payload（`swap/test_parsing_http_boundary.py:61-85`、`tools/test_http_pool.py:20-60`）；`tests/conftest.py:3-5` 明令禁止 autouse 兜底；`tests/intent_fixtures.py:21-22` 强制 mock 输出的 evidence 必须来自真实输入。
4. **真多轮走 checkpoint 而非手工塞 state**：`test_inquiry_continuation.py:156-201`（两轮 HTTP 后 `graph.get_state` 校验 history 与 `history:<id>` 证据引用，并断言 HTTP 调用序列）；`test_smoke.py:182-195`（两轮 trace 节点序列逐一相等）；`test_api_idempotency.py:47-53,95-106,148-155`（重投回放、uncertain、跨用户 409）。
5. **金融不确定性语义有专门覆盖**：`swap/test_confirmation_protocol.py:17-54`（50 条 fixture 驱动真子图，非法确认永不调交易 API）；`test_confirmation_protocol_20260920.py:48-85`（七条确认路径 × 9 种不安全指令，63 条 `assert_not_awaited`）；`test_reply_contract_20260920.py:49-63`（无 Java 回执绝不出"已提交"）；`close/test_candidate_migration.py:36-53`（后端不可达 / 403 不伪装成空列表继续交易）。
6. **evidence / provenance 契约是全库最强一层**：`swap/test_multimodal_evidence.py:75-80,99-115`、`option/test_inquiry_evidence.py:38-42`、`option/test_code_provenance.py:32-39`，与 `langgraph-patterns.md`"模型只给指针、Code 定终值"完全一致。
7. **D6 判定口径逐条可验**：`tests/test_harness.py:346-352`（REJECTED 不算 PASS）、`:366-377`（早停逐轮记失败）、`:316-334`（dry-run / real 四象限互拦）；`tests/test_prompt_spec.py:128-143` 遍历全部注册 spec 校验 inputs ⊆ AgentState 与 `Field(description=)` 全覆盖。
8. **skip 纪律干净**：全仓仅 4 处 `skipif`，全部环境门控并写明理由，无 xfail、无无理由 skip。

## 六、建议的修复顺序

1. P0-1 + P1-2 + P1-1（让 main 可 import、pytest 全绿；一并清 ticker 死守卫与 render 旧断言）。
2. P0-2（恢复 CI 触发，fast/slow 分层）——没有它，后面所有项都会再次漂移。
3. P0-3（凭据 revoke + `tests/api` 迁 scripts）。
4. P1-3 / P1-4 / P1-6（import 卫生、空转守卫、RetryPolicy 完整性）。
5. P1-8 / P1-7（`expected.place_params` lint、MySQL 用例进 CI）。
6. 组织重构：`tests/{scripts,harness,prompts,api_wire}/` 归位，render 9 文件归并，close 路由四文件合一，Dify 口径改写，文档同步（`tests/CLAUDE.md` / `.claude/rules/testing.md` / `CLAUDE.md` 计数），并跑 `python scripts/sync_agents_md.py`。

## 七、文件归属统计

| 位置 | 文件数 | 测 app/ | 测 harness/ | 测 scripts/ | 手工脚本 / 数据 |
|---|---:|---:|---:|---:|---:|
| tests/api/ | 24 | 0 | 0 | 0 | 24（被 `--ignore`） |
| tests/tools/ | 11 | 11 | 0 | 0 | 0 |
| tests/observability/ | 16 | 14 | 0 | 2 | 0 |
| tests/ 根 test_*.py | 79 | 41 | 11 | 23 | 4 |
| tests/{graph,nodes,subgraphs,integration}/ | 19+23+68+6 | 全部 | 0 | 0 | 0 |
| tests/fixtures/ | — | — | categories 389 条 + unified_golden.jsonl 921 行 | — | old_typing 932K（零消费）、nodes/ 仅 README |
