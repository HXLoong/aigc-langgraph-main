<!-- 自动生成：python scripts/sync_agents_md.py —— 禁止手改。
     真源是 CLAUDE.md + .claude/rules/*.md；改那里再重新生成，CI（governance job）会校验同步。 -->


# otc-agent · 图灵科技 Project Memory

场外衍生品 AI 指令助手。**FastAPI + LangGraph + MySQL + LangFuse self-hosted**，从 Dify 工作流迁移而来。
企微群客户消息 → 意图解析 → 后端业务/交易系统。

> 当前阶段：**M1 / M2 / M3.1 / M3.2 已完成**（M2 PR #41 已合 main，主干 24 节点蓝图实际落地 20 节点：swap 6 + option 6 + option_close 7 + ticker 1；mock_api baseline PASS ≥ 92.5%，真 LLM baseline 84.6%）→ **M3.3 真后端 golden 回归 + 错例修 P0/P1 + 业务方现场 sign-off 进行中**（open issues #82–#87，参见 [ADR 0016](./docs/adr/0016-m3-scope-engineering-loop-not-shadow.md) 与 [docs/m3-m4-roadmap.md](./docs/m3-m4-roadmap.md)）；**M4 灰度工具链已就绪**（rollback_canary / drill_smoke / shadow_compare / deploy-customer / Grafana 模板 / Prompt 晋升 + on-call runbook，详见 README "M4 准备就绪的工具链"）

## 关键命令

```bash
# 安装
pip install -e ".[dev]"

# 启动业务依赖
docker compose up -d mysql                                                          # MySQL（业务库 + checkpoint）
docker compose -f infra/langfuse/docker-compose.yml --env-file infra/langfuse/.env up -d  # LangFuse self-hosted

# 启动应用
uvicorn app.main:app --reload                # FastAPI（POST /v1/workflows/run，兼容 Dify）

# 测试（841 passed + 14 skipped，约 2 分钟，行覆盖率 82%）
pytest tests/ -v                             # 全套
pytest tests/test_smoke.py -v                # 仅 smoke
pytest -k "not e2e"                          # 跳过 e2e

# 评估（M3 主用入口：DeepSeek Judge + per-turn 富集 JSON 写到 Langfuse Cloud）
python scripts/langfuse_eval.py --local tests/fixtures/unified_golden.jsonl --concurrency 4   # 全量 350+
python scripts/langfuse_eval.py --local tests/fixtures/unified_golden.jsonl --ids opt-001,opt-018 --concurrency 2

# Harness CLI（备用 / 本地快速 smoke，无 Judge）
python -m harness run                        # 跑 golden 全集
python -m harness diff <run-a> <run-b>       # 比对两次 run
python -m harness sync-golden                # tests/fixtures/*.jsonl ↔ LangFuse dataset

# 真后端探针（M3 联调）
python scripts/probe_real_backend_e2e.py
python scripts/probe_swap_write_e2e.py
python scripts/probe_option_write_e2e.py
python scripts/probe_close_write_e2e.py
python scripts/probe_ticker_e2e.py

# Dify 同步（保留资产）
export DIFY_EMAIL="..." DIFY_PASSWORD="..."
python dify/sync.py                          # 拉最新 YAML → dify/yaml/
```

## 项目结构（M2 完成、M3 进行中）

```
app/
├── main.py                  # FastAPI 入口 + lifespan + HTTPMetricsMiddleware + /metrics
├── config.py                # pydantic-settings 配置加载
├── api/                     # routes.py（POST /v1/workflows/run）+ health.py（/health, /ready）
├── graph/
│   ├── state.py             # AgentState（按业务对象聚合）
│   ├── safe_node.py         # @safe_node 装饰器
│   ├── cascade.py           # cascade fallback（error → 友好降级）
│   └── main.py              # 主图组装入口（build_main_graph;旧 graphs/ shim 已删）
├── nodes/                   # ingest / pre_route（对手+候选提取）/ route_rules + intent_route（DSL v2 两层路由）
│                            # / fast_query（快速询价+存量兼容前置分支）/ persist / render / fallback
├── subgraphs/               # —— 2026-08 Dify DSL v2 迁移后结构 ——
│   ├── swap/                # intent / place_order(+submit) / select_counterparty / select_ticker
│   │                        # / confirm(三提示词+二次校验) / cancel / query_order / multimodal(图片+Excel)
│   │                        # （+ quote_hints / aggregate / prewash / backend / graph / models;手转股已删）
│   ├── option/              # intent + 7 extract（inquiry / place / confirm_place / cancel_place /
│   │                        # confirm_cancel / cancel / query）+ sanitize + backend
│   ├── close/               # intent / place_close(5 步引用解析链) / cancel_close / confirm_close /
│   │                        # confirm_cancel / holding_query / query_status + reference_parser/merge/aggregate/backend
│   └── ticker/              # resolver 确定性管线（候选格式化 → 3 路 LLM → merge_and_validate → GOATS+rank;ReAct 已退役）
├── tools/
│   ├── models.py            # Java DTO 对应 Pydantic
│   ├── option_client.py     # OptionClient Protocol（POST /financial-orders/operate）
│   ├── swap_client.py       # SwapClient Protocol（POST /swap-order/operate）
│   ├── ticker_client.py     # TickerClient Protocol（GET /securities-instrument/select）
│   ├── goats_agent_client.py # GOATS /internal/agent/*（快速询价 rfq parser + 存量兼容,md5-16 签名）
│   ├── auth.py / exceptions.py
├── llm/clients.py           # LLM 统一工厂：全量 DeepSeek-V4-pro（ADR 0020，thinking 关闭 + structured output 走 function_calling 适配）
├── checkpointer/factory.py  # AIOMySQLSaver
├── observability/           # tracing.py + metrics.py（Prometheus 兼容 /metrics）
└── prompts/                 # Dify 提示词资产（router / swap / option / option_close / ticker）

harness/                     # 评测台（与 app/ 解耦，仅 import build_main_graph）
├── golden.py                # golden.jsonl 加载
├── runner.py                # 跑 case + dump trace 到 LangFuse
├── differ.py                # 字段级 diff（按业务对象路径）
├── reporter.py              # JSON + markdown 报告（按 source 桶分别统计）
├── langfuse_client.py       # LangFuse SDK 封装（v4 OTel-based）
├── token_tracker.py         # LLM token / 成本估算
├── case_generator/          # LLM 对抗式 paraphrase 生成 C 桶
└── cli.py                   # python -m harness <run|diff|sync-golden|...>

scripts/                     # langfuse_eval.py（Judge 评估，M3 主用） / eval_golden.py / probe_*_e2e.py
                             # upload_golden_to_langfuse.py / promote_langfuse_prompt.py / canary_status.py
                             # rollback_canary.sh / run_alerts.py / llm_cost_report.py / shadow_compare.py 等

infra/langfuse/              # LangFuse self-hosted Docker Compose（PG + ClickHouse + Redis + MinIO + Web + Worker）
docs/adr/                    # 架构决定 ADR 0000-0021（共 22 篇）+ README 索引
docs/api-contracts/          # Java 后端真实业务 API 契约
docs/m3-m4-roadmap.md        # M3/M4 端到端任务图（6 个交付面，2026-05-11 修订）
docs/on-call-runbook.md      # 上线 on-call SOP
tests/                       # 841 passed + 14 skipped；行覆盖率 82%
tests/fixtures/              # golden.jsonl（350+ 条）+ golden_ticker_2026-05.jsonl（34 条）
```

## 团队工具链：Claude Code 与 Codex 共用一份纪律

团队主用 Codex。Codex 只读根目录与各级子目录的 `AGENTS.md` 和 `.agents/skills/<name>/SKILL.md`，不读本文件、
`.claude/rules/`、`.claude/skills/`、`.claude/agents/`。因此这些 **Codex 产物全部由 `python scripts/sync_agents_md.py` 生成，禁止手改**：

- 根 `AGENTS.md` = 本文件 + 并入 `.claude/rules/{prompt-management,testing}.md`，其余 rules 只列路径（控制上下文体积）
- `app/prompts` / `tests` / `scripts` 下的 `AGENTS.md` = 各自的 `CLAUDE.md`
- `.agents/skills/<name>/` = `.claude/skills/<name>/`（frontmatter 收敛为 Agent Skills 标准的 `name` / `description` / `metadata`）
  + `.claude/agents/*.md`（Codex 无 subagent，转为同名技能，调用时以该角色执行）；Codex 里用 `$name` 显式调用

改纪律或流程只改 `CLAUDE.md` / `.claude/**`，再跑生成脚本一起提交；governance CI `--check` 守同步。

## 子目录陷阱页（按需加载）

只在三个目录下有 `CLAUDE.md`，承载**根文件不便展开的局部陷阱**，不是必读层级：

- `app/prompts/CLAUDE.md` — 提示词加载器 + ADR 0001 D5 改写纪律
- `tests/CLAUDE.md` — Mock "patch where it's looked up" 陷阱 + TDD 红线
- `scripts/CLAUDE.md` — 25+ 脚本分类目录页

## 核心原则（永远有效）

1. **提示词不硬编码在代码里** —— 从 `app/prompts/**/*.md` 加载；LLM 节点用 `PromptSpec`（`app/prompts/spec.py`，ADR 0023）声明 `inputs`（AgentState 字段）/ `output_model` / `injects` / `user_builder`，`SPEC.build_messages(state)` 拼消息；user 里的规则文本住 `.md` `[user]` 段，代码只供变量；共享拼装用 `app/prompts/blocks.py`，不在子图里复制 `_format_history`
2. **LLM 输出用 `with_structured_output(PydanticModel)`** —— 绝不手工解析 JSON；输出模型每个字段写 `Field(description=)`，这是输出语义的唯一真源（经 function calling schema 下发），提示词正文不再维护 JSON 骨架 / 字段表
3. **每个节点用 `@safe_node` 装饰** —— 异常降级到 `state['error']`，不让图崩
4. **State 字段只通过 TypedDict 约定** —— 新增字段必须先在 `app/graph/state.py` 中声明
5. **TDD 强制**（`.claude/skills/test-driven-development/SKILL.md` 流程）—— 任何 bug fix / 新功能必须先写失败测试：
   - 写测试 → 跑到 RED（测试失败） → 写最小修复代码 → 跑到 GREEN → 全量回归
   - 禁止先改代码再补测试，也禁止跳过 RED 验证
   - `.claude/skills/test-driven-development/SKILL.md` 流程 包含完整 workflow，修改代码前调用
6. **git 里的提示词是唯一真源，Dify 只是上游输入**（ADR 0022 D1，2026-09-15）—— 改活跃提示词走 ADR 0022 D4 分档：零风险档直接改 v1，低风险 / 需业务确认档走 `*_v2.md` 灰度 + eval 门；每次改动在 `app/prompts/_manifest.yaml` 该条目 `changelog` 登记，`prompt(<scope>)` commit。Dify 侧更新由 `scripts/prompt_inventory.py --check` 告警后人工 diff 合入，不再一键覆盖
7. **标的代码必须 from_goats=True** —— Ticker Agent 的绝对约束（ADR 0008）
8. **节点失败必须 cascade 防御** —— 任一节点写入 `state['error']` 后，下游 conditional 路由必须检查并跳到 fallback render，禁止 cascade 失败。具体：主图 `_route_by_product` 与每子图首节点后的 conditional 都加 `if state.get('error'): return 'fallback'`。fallback 节点输出友好回复（"我没完全理解你的意思，能换种说法重新告诉我吗"）+ trace 记录原 fail 节点名。LLM 解析失败由 `with_structured_output` 自带 1 次重试 + `@safe_node` 兜底捕获 ValidationError 写入 error；不走 HITL（HITL 仅用于 ADR 0006 的业务参数二次确认场景）

## 排查与修复流程（Bug Debug Workflow）

### 1. 从 Langfuse 富 output 定位根因（首选）

`scripts/langfuse_eval.py` 每跑完一条 case 会把**结构化富集 JSON** 写到 Langfuse Cloud
（https://us.cloud.langfuse.com），outer span output 包含：

```jsonc
{
  "expected": "Judge 期望输出",
  "score": 0.0,
  "judge_comment": "Judge 一句话评语",
  "turns": [
    {"turn": 1, "raw": "用户原始输入", "reply": "机器人回复",
     "product_type": "option", "intent": "new_inquiry",
     "tickers": [{"wind": "...", "desc": "...", "goats": true}],
     "place_params": {"action": "...", "orderList": [...]},
     "api_result": null, "api_code": null,
     "error": null,
     "trace": "ingest → intent_route → ...",
     "quote_passed": ""}
  ]
}
```

**AI 查错 SOP**：
1. eval stdout 找 `LangFuse 写入成功  run=local-YYYYMMDD-HHMMSS` 这行
2. Langfuse UI 按 run name 过滤 → 点开失败 case
3. 顶层 `score` + `judge_comment` 锁定差异
4. `turns[i]` 数组按字段定位错误层：
   - `product_type` 错 → [app/nodes/intent_route.py](app/nodes/intent_route.py)
   - `intent` 错 → 子图 `intent.py` 提示词
   - `tickers` 缺失或错 → [app/subgraphs/ticker/](app/subgraphs/ticker/)
   - `place_params` 字段漏 → 子图 `extract_*.py` 提示词
   - `api_result` 含"正在处理"/"请勿重复" → 后端 dedup
   - `error` 非空 → 看 `error.node` + `error.message`
5. 左侧子 span 树（CallbackHandler 自动嵌套）看每个 LLM 调用的 prompt / completion / token

### 1b. 备用：stdout per-turn 文本（无 Langfuse 时）

```
第N轮 [product_type/intent] | quote=Xc 'preview' | ERROR: ...
  trace : ingest → intent_route[rule:...→option] → option_intent[...] → render
  reply : 实际回复内容
```

**读法**：
- `[product_type/intent]`：路由是否正确
- `quote=Xc`：quote_content 是否传入（0c = 未传）
- `trace`：节点决策链，找第一个"错"的节点
- `trace` 是累积的（LangGraph add reducer）；多轮 case 的本轮节点在 **末尾**

**常见根因模式**：

| 现象 | 根因 | 文件 |
|---|---|---|
| 第2轮路由走了 LLM 而非 quote_marker | `_QUOTE_MARKERS` 未覆盖实际标记 | `app/nodes/intent_route.py` |
| reply 含"无法识别"但未问标的 | `make_initial_state` 设了 `tickers=[]` 覆盖 checkpoint | `app/state.py` |
| option place_order 显示"互换订单参数" | render 第3分支缺 `product_type=="swap"` 条件 | `app/nodes/render.py` |
| 多轮 tickers/params 丢失 | `make_initial_state` 不应对业务字段设默认值 | `app/state.py` |
| 后端返回"订单不存在" | 参数中 orderId/Q- 单号提取错误 | 子图 extract 节点 + 提示词 |

### 2. TDD 修复（强制）

找到根因后，**必须先写失败测试再改代码**（`.claude/skills/test-driven-development/SKILL.md` 流程）：

```bash
# 1. 写 tests/xxx/test_yyy.py，体现 bug 的最小复现
# 2. 确认 RED
.venv/bin/python -m pytest tests/xxx/test_yyy.py -v
# 3. 写最小修复
# 4. 确认 GREEN + 全量回归
.venv/bin/python -m pytest tests/ -q --tb=line 2>&1 | tail -5
```

### 3. eval 回归

修完跑对应 case 确认：

```bash
.venv/bin/python scripts/langfuse_eval.py --local tests/fixtures/unified_golden.jsonl --ids opt-001,opt-018 --concurrency 2
```

## 绝对禁止

- **硬编码 API Key / Secret** —— 必须通过 `app.config.get_settings()`，读环境变量
- **在节点函数内抛未捕获异常** —— 用 `@safe_node` 包住
- **MySQL 版本不符合 8.0.19 ≤ v < 9.6.0 的假设** —— AIOMySQLSaver 兼容性硬约束
- **直接 `httpx.AsyncClient` 调后端** —— 走 `OptionClient` / `SwapClient` / `TickerClient` 三个 Protocol（ADR 0001 D2 修订版）
- **在 main 分支直接改业务子图** —— 走 feature branch + PR
- **面向测试编程** —— 禁止为提高通过率硬编码白名单标的，禁止在 `app/` 业务代码里内置"备用实现"开关（如 `DEFAULT_MODE` 环境变量切换查询路径），禁止在 `conftest.py` 用 `autouse` fixture 全局绕过真实业务路径。测试慢应 mock HTTP 层（`_make_client`），不改业务代码路径
- **P0 · 业务代码不能掩盖后端真实响应** —— 严禁在 `app/nodes/render.py` 或子图里加"如果后端返回 X 就改成 Y"的回退逻辑（典型反例：后端返回"正在处理，请勿重复提交"时改用本地 LLM 抽取结果伪造订单卡）。即使 eval 通过率因此下跌，也必须如实透传后端响应。Why: 生产环境下用户会被错误引导，看到伪造的订单卡以为已下单，实际请求被后端 dedup 丢弃；调试时也会误以为业务流程通了。如果是 eval 节奏导致的偶发问题（如多轮间隔太短撞 dedup），workaround 必须放在 `scripts/langfuse_eval.py`（如 turn 间 sleep），**绝不进业务代码**
- **P0 · 迭代过程中禁止 `git push` / `gh pr create`** —— `/goal` `/iterate-option` 这类自驱动循环里**严禁**调用 `git push` 或 `gh pr create`（即使 commit 已落地）。Why: 这两个命令默认会触发 permission 弹窗 → 循环阻塞等用户点 Yes，被强制 pause。`/goal` 的语义是"持续推进不打断"，远程操作必须等用户**显式**说"push" / "pr" 才能做。本地 `git commit` 可以正常做（不触发权限弹窗），但远程推送和 PR 创建必须留到用户主动指示
- **P0 · 硬编码业务数据字典** —— 严禁在代码或本仓 YAML/JSON 配置里维护**业务数据映射清单**（如"命名指数 → ETF 代码"、"中文名 → windCode"、"产品名 → 行业代码"等）。理由：业务数据规模会快速膨胀到 100+ 条且持续变化（新 ETF/新指数/新产品每月发行），代码侧维护必然过期、漂移、出错。正确做法是 **LLM 通用知识推断 + 后端权威源校验**：用 `infer_code` / 类似 LLM 工具把模糊关键词翻译成候选 windCode，再用 GOATS / 后端接口反向校验存在性。把"业务清单"留给后端或业务方维护的数据库，代码侧只负责调用与校验

## 代码风格

- Python 3.11+，严格类型提示
- ruff lint，行宽 100
- 异步优先：能 async 就 async
- 中文注释 OK，docstring 简洁清晰
- 不加 emoji（生产代码）

## 下一步：M3.3 真后端 golden 回归 + 业务方 sign-off（进行中）

ADR 0016 把"M3 = shadow 双跑"重新定义为"M3 = 工程联调闭环 + 评估迭代"，分 M3.1 / M3.2 / M3.3 三段：

**已完成（六大交付面）**：

1. **代码完整性** ✅：24 节点蓝图 → 主干 20 节点已落地；P2 辅助节点（place_order_image / place_order_excel / image_recognize）按线上流量增量补
2. **数据集完整性** ✅：golden.jsonl 已扩到 350+；fixture 职责矩阵 + 一致性 lint 已就位（PR #109）；按 B / C / D 桶分别维护
3. **客户现场部署能力** ✅：infra/langfuse self-hosted、`scripts/deploy-customer.sh`（C1.13 / Issue #58）、`.env.customer.template`（C1.12 / Issue #52）、私有化部署文档（C1.11 / Issue #51）
4. **联调与回归** ✅：真后端 e2e 探针（`scripts/probe_*_e2e.py`，D2.1–D2.6 + Dx.1–Dx.2 已 closed）+ DeepSeek Judge 评估（`scripts/langfuse_eval.py`）+ business 子图 → 真 client → mock_api 全链路（PR #110，27 测试）
5. **可观测 + 运维** ✅：`/metrics` Prometheus 端点（C1.5 / Issue #50） + 5xx 计数闭环（PR #104） + P95 延迟告警（PR #103） + LLM 成本监控（C1.7 / Issue #56） + 阈值一致性 CI lint（PR #106） + on-call 应急回切剧本（PR #99） + `scripts/rollback_canary.sh`（PR #98）
6. **上线策略** ✅工具链就绪：Shadow 双跑（M4 第二意见，含 `DRY_RUN_BACKEND` 模式 PR #112）+ 按群组金丝雀（`scripts/canary_status.py` PR #92 / `scripts/metrics_snapshot.py` PR #94）+ Grafana 灰度面板 JSON 模板（PR #97）+ LangFuse Prompt 晋升工具（F4.6 / PR #95）

**进行中（M3.3）**：

| Issue | 任务 | 退出门 |
|---|---|---|
| #82 E3.1 | 真后端跑 B 桶全集 → PASS rate | 总 PASS ≥ 92.5%（与 M2 mock baseline 同口径）|
| #83 E3.2 | business_seed 全集按桶分别评估 | B 桶 ≥ 90% / C 桶 ≥ 80% |
| #84 E3.3 | 真后端跑 D 桶（客户真实输入）| 依赖 B1.5 PM 收集 30+ 条 |
| #85 E3.4 | 错例聚类 + 根因分析，**只修 P0/P1** | cascade fail / 5xx / 严重参数错 / 标的错全部修复 |
| #86 E3.5 | 现场 smoke checklist + 客户 Java 后端真实联调 | ≥ 5 条真实业务流走通 |
| #87 E3.6 | 业务方培训 + 现场 sign-off | 业务方盲测 ≥ 5 条 case PASS sign-off |
| #59 C1.14 | 离线依赖包（pip wheel + docker save）| 离线环境完整跑通客户部署 |
| #113 | fixture 数据集质量修复（执行价格缺失 / 反案例标错）| 业务方 review pass |

**二期持续优化（全量上线后启动，不阻塞 M3/M4）**：

- Issue #35 · 评估→优化→更新→再评估自动闭环
- Issue #36 · 智能体异常干预 + 沉淀记忆机制（agentic memory）
- Issue #37 · 回流集自动化打通（D 桶 · 生产真实流量 → golden）

参见 [docs/m3-m4-roadmap.md](./docs/m3-m4-roadmap.md) 获取分阶段任务图与 owner 表。

### 节点工作模板（不变）

每个节点：`@safe_node` + `with_structured_output(<NodePydanticOutput>)` + `load_prompt()` + golden case。

### golden case 来源策略

**B + C + D 三桶**：

| 来源 | 角色 | 退出门 PASS 率 |
|---|---|---|
| **B · 业务方手写种子** | 主基线，意图均衡覆盖 | ≥ 90% |
| **C · LLM 对抗式 paraphrase**（`harness/case_generator/`） | 边界 case / 同义改写 | ≥ 80%（容忍 LLM 同质化抖动）|
| **D · 客户历史真实输入** | 反映真实分布；必须业务方人工标注 expected 后才能合入 | 无硬性阈值（M3 持续累积，作补充参考）|
| ~~A · 历史企微日志抽样~~ | 暂搁，被 D 桶替代 | — |

harness reporter 输出按桶分别统计；CI 维护一致性 lint（详见 `scripts/check_fixture_consistency.py`）。

详见：

- 领域语言：`@CONTEXT.md`
- 架构决定：`@docs/adr/`（ADR 0000-0023 共 24 篇，索引见 `docs/adr/README.md`）
- Java 契约：`@docs/api-contracts/java-backend.md`
- M3/M4 路线图：`@docs/m3-m4-roadmap.md`
- on-call SOP：`@docs/on-call-runbook.md` + `@docs/troubleshooting-sop.md`

## Agent skills

### Issue tracker

Issues 存在 GitHub Issues（`github.com/GZTL-AI/aigc-langgraph`），通过 `gh` CLI 操作。详见 `docs/agents/issue-tracker.md`。

### Triage labels

使用默认标签词汇：`needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix`。详见 `docs/agents/triage-labels.md`。

### Domain docs

Single-context 布局：根目录 `CONTEXT.md` + `docs/adr/`。详见 `docs/agents/domain.md`。


---

# 附一：并入正文的仓库规则（.claude/rules 原文）


<!-- 来源：.claude/rules/prompt-management.md -->

# 提示词管理规则

> 真源与状态机：[ADR 0022](../../docs/adr/0022-prompt-governance-after-code-migration.md)；
> 清单：`app/prompts/_manifest.yaml`（`python scripts/prompt_inventory.py` 打印，`--check` 进 CI）；
> 局部陷阱：`app/prompts/CLAUDE.md`。本文件只写"怎么做"，不复制清单与节点数（以 manifest 为准）。

## 三态与守护

| status | 含义 | lint 不变量 |
|---|---|---|
| `active` | 生产加载 | `loader` 文件里必须有 `load_prompt("<cat>", "<name>")` / `resolve_prompt_version(...)` 或 `loader_call` helper 调用 |
| `gray` | ADR 0003 灰度位（`*_v2.md`），由 `_versions.yaml` / `OTC_PROMPT_<CAT>_<NAME>_VERSION` 切流 | 记录 `base_system_sha256`；v1 之后被改 → 必须重做 diff 并写 `drift_acknowledged: {at_base_sha, note}`；`expires` 到期未转正 → 警告 |
| `inactive` | 无加载点的资产 | `reason` 必填（保留理由 + 可删条件）；`app/` 内零 `load_prompt` 引用 |

`--strict` 加严项（ADR 0022 D5 目标态，逐步收敛）：system 段里未在 `injects` 登记的 `{{#…#}}` 占位符视为**悬空**；走 `with_structured_output`（有 `output_model`）的文件里的 JSON 格式禁令视为死重。

## 占位符纪律（2026-09-15 反转）

Dify 的 `{{#node_id.var#}}` 在 Dify 由工作流引擎渲染；LangGraph 里**没有渲染层**。所以：

- 代码确实注入的占位符 → 在节点里 `system.replace(...)` 渲染（先例：`close/holding_query.py` 对手列表、`ticker/tools.py` 当前日期），并在 manifest `injects` 登记
- 代码不注入的占位符 → 是悬空规则，LLM 看到的是变量名；属零风险删除档，围绕它的整段规则一起删

## 加载方式（ADR 0023：一个 LLM 节点 = 一个 PromptSpec）

```python
from app.prompts import blocks
from app.prompts.spec import PromptSpec, register

def _build_user_message(state: AgentState) -> str:      # 只拼变量，规则文本不进 Python
    return f"raw_content: {state.get('raw_text', '') or ''}\n\nhistory:\n{blocks.format_history(state.get('history_messages'))}"

SPEC = register(PromptSpec(
    category="swap", name="intent",
    output_model=SwapIntentOutput,                    # 输出契约唯一真源：每个字段写 Field(description=)
    inputs=("raw_text", "history_messages", "conversation_id"),   # 必须是 AgentState 字段，构造期校验
    user_builder=_build_user_message,
    injects={"{{#node.var#}}": lambda s: blocks.json_list(s.get("option_counterparties"))},  # system 占位符渲染
    gray=True,                                        # 走 _versions.yaml 灰度（resolve_prompt_version）
))

messages, prompt_name = SPEC.build_messages(state)    # [("system", ...), ("user", ...)]
result = await model.with_structured_output(SwapIntentOutput).ainvoke(messages)
```

- 节点默认只用 system 段 + 代码拼变量的 user；user 里若有**规则文本**，写进 `.md` 的 `[user]` 段用 `{{var}}` 占位，`user_builder` 里用 `load_prompt(...).render_user(**vars)` 渲染（先例 `swap/place_order.md`）
- **禁止**把提示词正文硬编码进 Python（含"后置追加一段格式指令"这种写法）；**禁止**在 `.md` 里维护 JSON 骨架 / 字段表——字段语义只写在 Pydantic `Field(description=)`
- 共享拼装（历史、对手列表、JSON 列表）只在 `app/prompts/blocks.py` 定义一次，不在子图里复制
- `injects` 必须与 manifest 该条目的 `injects` 一致（`tests/test_prompt_spec.py` 交叉核对）；`prompt_inventory.py --check` 把 `PromptSpec(category=, name=)` 视为加载点
- 灰度节点必须把 `build_messages` 返回的 `prompt_name` 写进 `TraceEntry.llm_output["prompt_name"]`（ADR 0003 硬前置，harness reporter 按此分桶）
- 尚未迁到 PromptSpec 的节点（close 5 个、swap select_* / multimodal、ticker、router）仍是 `load_prompt` / `resolve_prompt_version` 直调，按 ADR 0023 D5 分批迁移

## 来源优先级（ADR 0014 D3-2）

生产真源永远是 git 里的 `app/prompts/**/*.md`；`USE_LANGFUSE_PROMPTS=true` 只允许开发/staging 演练，生产开启即 fail-fast。LangFuse 演练稿用 `scripts/promote_langfuse_prompt.py` 晋升为 `_v{N+1}.md`（自动登记 manifest `gray`），再走 PR。

## 改提示词的三条路

| 场景 | 做法 | 门槛 |
|---|---|---|
| 瘦身 / 修规则（ADR 0022 D4 三档） | 零风险档直接改 v1；低风险档与需业务确认档走 `*_v2.md` 灰度位；都在 manifest `changelog` 加一行 | eval PASS ≥ v1 基线；`prompt(<scope>)` commit |
| Dify 侧有更新 | `python dify/sync.py`（凭据只从 `DIFY_EMAIL` / `DIFY_PASSWORD` 环境变量读）→ `scripts/export_dify_prompts.py`（默认不覆盖已存在文件）→ 人工 diff 选择性合入 | 不要一键覆盖；`prompt_inventory.py --check` 会按 manifest `dify.system_sha256` 告警哪些节点有上游更新，合入后更新该 sha |
| 新 LLM 节点 | `.md` 放对目录 + Pydantic Output 模型（每字段 `Field(description=)`）+ `PromptSpec` 声明 + `@safe_node` 节点 + manifest 登记（`output_model` / `injects`）+ golden case | `prompt_inventory.py --check` 通过 |

## 字符数 / 延迟

用 `python scripts/prompt_inventory.py` 看 system 字符与估算 tokens（÷1.6）；单请求开销按调用链累加（`docs/prompt-maintainability-assessment.md` 第二节）。当前最重路径：互换图片下单 ≈54K tokens、平仓下单 ≈37K、互换文本下单 ≈36K。

## Loader 缓存

`load_prompt()` 有 `@lru_cache`；测试里要重载用 `from app.prompts import clear_cache; clear_cache()`。

## 相关 ADR

- ADR 0001 D5：改写决定登记表（资产状态部分已由 manifest 接管）
- ADR 0003：同目录并存 + `_versions.yaml` 灰度（唯一版本化形态）
- ADR 0014：LangFuse 作为演练区，git 为真源
- ADR 0022：代码迁移完成后的提示词治理模型
- ADR 0023：提示词即代码（PromptSpec / AgentState inputs / Pydantic description 输出契约）


<!-- 来源：.claude/rules/testing.md -->

# 测试规范

## 三层测试金字塔

```
   E2E 集成测试 (tests/test_e2e.py)     ← 慢，少，Mock LLM + Mock 后端
   ─────────────────────────────
   子图 / 节点测试 (tests/test_*.py)   ← 中等，覆盖关键路径
   ─────────────────────────────
   模型与路由测试 (tests/test_models.py) ← 快，多，纯函数单测
```

## pytest 约定

- 所有测试必须 import 时能成功（不联网、不依赖真实 MySQL）
- 异步测试用 `@pytest.mark.asyncio`（`asyncio_mode = "auto"` 已在 pyproject.toml 配置）
- Mock 必须 patch "where it's looked up"，不是定义处

## Mock 陷阱提醒

```python
# ❌ 错误：patch 原定义位置
monkeypatch.setattr("app.tools.otc_backend.OtcBackendClient", factory)
# 因为 swap.py 已经 `from app.tools.otc_backend import OtcBackendClient`
# 名字绑到 swap 模块了，改原模块不生效

# ✅ 正确：patch 所有使用点
for target in (
    "app.tools.otc_backend.OtcBackendClient",
    "app.subgraphs.swap.OtcBackendClient",
    "app.subgraphs.option.OtcBackendClient",
    "app.subgraphs.close.OtcBackendClient",
):
    monkeypatch.setattr(target, factory)
```

## E2E 测试

- **用 `InMemorySaver` 代替 MySQL Checkpointer**：避免依赖数据库
- **Mock LLM 要 Mock 到 `with_structured_output` 返回的对象**：
  ```python
  mock_intent_llm = MagicMock()
  mock_intent_llm.ainvoke = AsyncMock(return_value=CloseIntentOutput(type="..."))
  mock_std.return_value.with_structured_output.return_value = mock_intent_llm
  ```
- **后端调用通过真实后端或集成测试环境**：E2E 测试直接对接真实后端（需真实后端 + VPN），单元测试 Mock 掉 Client Protocol

## Golden Set

- 所有新增意图必须在 `tests/fixtures/golden.jsonl` 加至少 2 条用例
- golden 格式见文件顶部注释
- 跑评估：`python scripts/langfuse_eval.py --local <fixture>`（`eval_golden.py` 为旧入口）

## 提交前自检

```bash
pytest tests/ -v                              # 全部通过
ruff check app/ tests/                        # lint 零警告
mypy app/                                     # 类型无错
```

## 何时写测试

- ✅ 新增节点函数 → 加路由测试
- ✅ 新增 Pydantic 模型 → 加字段校验测试
- ✅ 新增业务逻辑分支 → 加 E2E 覆盖
- ✅ 修 bug → 先写复现测试，再修
- ⚠️ 改活跃提示词 → 走 ADR 0022 D4 分档 + eval 门（PASS ≥ 上一版），`prompt(<scope>)` commit；改 `.md` 必须同步 `app/prompts/_manifest.yaml`

## 跑慢测试的技巧

```bash
pytest -v -k "not e2e"          # 跳过 E2E（只跑快速测试）
pytest -v -k "swap"             # 只跑互换相关
pytest -v --lf                  # last-failed（只跑上次失败的）
pytest -v -x                    # 遇到第一个失败就停
pytest --cov=app.nodes.route    # 覆盖率
```


# 附二：其余仓库规则（按需读取，同样具有约束力）

- `.claude/rules/git-workflow.md` — Git 工作流
- `.claude/rules/langgraph-patterns.md` — LangGraph 特定模式
- `.claude/rules/python-style.md` — Python 编码规范
