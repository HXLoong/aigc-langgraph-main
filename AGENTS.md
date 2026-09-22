<!-- 自动生成：python scripts/sync_agents_md.py —— 禁止手改。
     真源是 CLAUDE.md + .claude/rules/*.md；改那里再重新生成，提交前跑 python scripts/sync_agents_md.py --check 校验同步。 -->


# otc-agent · 图灵科技 Project Memory

场外衍生品 AI 指令助手。**FastAPI + LangGraph + MySQL + LangFuse self-hosted**，从 Dify 工作流迁移而来。
企微群客户消息 → 意图解析 → 后端业务/交易系统。

> 当前阶段：**M1 / M2 / M3.1 / M3.2 已完成**（M2 PR #41 已合 main，主干 24 节点蓝图实际落地 20 节点：swap 6 + option 6 + option_close 7 + ticker 1；mock_api baseline PASS ≥ 92.5%，真 LLM baseline 84.6%）→ **M3.3 真后端 golden 回归 + 错例修 P0/P1 + 业务方现场 sign-off 进行中**（open issues #82–#87，参见 [ADR 0016](./docs/adr/0016-m3-scope-engineering-loop-not-shadow.md) 与 [docs/m3-m4-roadmap.md](./docs/m3-m4-roadmap.md)）；**M4 灰度工具链已就绪**（rollback_canary / drill_smoke / shadow_compare / deploy-customer / Grafana 模板 / Prompt 晋升 + on-call runbook，详见 README "M4 准备就绪的工具链"）

## 关键命令

```bash
# 安装
pip install -e ".[dev]"

# 启动业务依赖
# 先在 Java 现有数据库执行初始化；MYSQL_URI 为唯一数据库连接配置
mysql -h <HOST> -P <PORT> -u <USER> -p --database=<JAVA_DATABASE> < sql/init.sql
docker compose -f infra/langfuse/docker-compose.yml --env-file infra/langfuse/.env up -d  # LangFuse self-hosted

# 启动应用
uvicorn app.main:app --reload                # FastAPI（POST /v1/workflows/run，兼容 Dify）

# 轻量测试；当前 .env 开启持久化，单测通过命令级配置隔离数据库依赖
USE_MYSQL_CHECKPOINTER=false REQUEST_IDEMPOTENCY=false ENABLE_LANGFUSE=false pytest tests/test_smoke.py -q
# 完整 pytest / 388 条业务集 / 性能测试按用户统一验收安排执行，不逐批重复。

# 本地 HTTP 业务回归（仅在准备好授权测试账号和数据后，由主代理或用户执行）
python scripts/local_eval.py --base-url http://127.0.0.1:8201 --data tests/fixtures/categories --case case-025 --concurrency 1
# 全量验收时去掉 --case；显式 categories 当前388条，不并入 unified。
# 本地真实联调：ENVIRONMENT=staging uvicorn app.main:app --host 127.0.0.1 --port 8201

# Langfuse Dataset Experiment（Judge + 自动 Evaluator；不替代 HTTP/Java 写回与幂等验收）
python scripts/langfuse/langfuse_eval.py --dataset golden_option_inquiry_case --ids case-022 --concurrency 1
# 意图集（只调 LLM + 仓库内 mock_api，不依赖 Java/GOATS；确定性评分本地算，--fail-under 给退出码；
# CI：.github/workflows/intent-eval.yml；业务集 categories/ 依赖 Java 后端只在开发环境跑；workflow-guide §8）
python scripts/langfuse/langfuse_eval.py --local tests/fixtures/intent --concurrency 3 --fail-under 0.95 --report .harness-runs/intent-eval.json

# Harness CLI（备用 / 本地快速 smoke，无 Judge）
python -m harness doctor
python -m harness run --backend real|mock|dry-run

# 真后端探针（M3 联调）
python scripts/probe_real_backend_e2e.py
python scripts/probe_swap_write_e2e.py
python scripts/probe_option_write_e2e.py
python scripts/probe_close_write_e2e.py
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
│                            # 标的识别、分词与排序由 Java 调对应工具处理（2026-09-20）
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
└── prompts/                 # 提示词资产（git 唯一真源，ADR 0024 D1；router / swap / option / option_close）

harness/                     # 评测台（经 HTTP 调本地 /v1/workflows/run，与 app/ 解耦）
├── golden.py                # categories fixture 加载（两方言归一化）
├── multi_turn.py            # 多轮 case 的 HTTP runner
├── differ.py                # 字段级 diff（按业务对象路径）+ 文本 / 结构化断言
├── langfuse_client.py       # LangFuse SDK 封装（v4 OTel-based）
├── token_tracker.py         # LLM token / 成本估算
├── case_generator/          # LLM 对抗式 paraphrase 生成 C 桶
└── cli.py                   # python -m harness <doctor|run> + 报告渲染

scripts/                     # langfuse_eval.py（Judge 评估，M3 主用） / probe_*.py
                             # upload_golden_to_langfuse.py / promote_langfuse_prompt.py / canary_status.py
                             # rollback_canary.sh / run_alerts.py / llm_cost_report.py / shadow_compare.py 等

infra/langfuse/              # LangFuse self-hosted Docker Compose（PG + ClickHouse + Redis + MinIO + Web + Worker）
docs/adr/                    # 架构决定 ADR 0000-0024（共 25 篇）+ README 索引
docs/api-contracts/          # Java 后端真实业务 API 契约
docs/m3-m4-roadmap.md        # M3/M4 端到端任务图（6 个交付面，2026-05-11 修订）
docs/on-call-runbook.md      # 上线 on-call SOP
tests/                       # 2900+ passed（2026-09-22；按 graph / nodes / subgraphs / api_wire / harness / prompts / scripts 归位）
tests/fixtures/              # categories/（A 方言业务集，6 文件 / 389 条）+ intent/（意图集：逐轮 product_type/intent，只调 LLM + mock 后端）
                             # + unified_golden.jsonl（B 方言，921 条，harness 默认并入）+ 历史归档见 docs/archive/fixtures/old_typing/
```

## 团队工具链：Claude Code 与 Codex 共用一份纪律

团队主用 Codex。Codex 只读根目录与各级子目录的 `AGENTS.md` 和 `.agents/skills/<name>/SKILL.md`，不读本文件、
`.claude/rules/`、`.claude/skills/`、`.claude/agents/`。因此这些 **Codex 产物全部由 `python scripts/sync_agents_md.py` 生成，禁止手改**：

- 根 `AGENTS.md` = 本文件 + 并入 `.claude/rules/{prompt-management,testing}.md`，其余 rules 只列路径（控制上下文体积）
- `app/prompts` / `tests` / `scripts` 下的 `AGENTS.md` = 各自的 `CLAUDE.md`
- `.agents/skills/<name>/` = `.claude/skills/<name>/`（frontmatter 收敛为 Agent Skills 标准的 `name` / `description` / `metadata`）
  + `.claude/agents/*.md`（生成可复用角色技能）；Codex 支持显式授权的子代理，技能通过 `$name` 调用

改纪律或流程只改 `CLAUDE.md` / `.claude/**`，再跑生成脚本一起提交；提交前跑 `python scripts/sync_agents_md.py --check` 守同步。

## 并行实施与验证范围

- 用户明确授权后可使用主代理与最多三个子代理。实现任务使用独立 worktree 和分支；子代理提交后由主代理审阅、集成。
- 每个任务指定文件所有者与验收用例；公共 State、配置、数据库结构及服务生命周期由主代理统一处理。子代理提出公共契约需求，不互相覆盖共享文件。
- Java 源码不修改；本地 Java 48080 → 48081，LangGraph 使用本地端口，禁止使用 10.49.91.229:8201；应用持久化统一 MYSQL_URI。
- 当前重构采用轻量验证：业务改动先最小 RED，再 GREEN 与相关关键测试；用户要求最终统一测试时，不逐批跑全套 pytest、388 条真实回归或压测。
- 真实写入测试仅由主代理调度；先确认授权测试账号、群、对手及持仓。业务回归使用 scripts/local_eval.py 和显式 tests/fixtures/categories，不并入 unified。
- 任务和证据记录在 tmp；区分实现完成、专项通过、待用户验收、外部阻塞。外部阻塞不可写成已完成；全量结果未经运行不得宣称通过。
- 不 push、不创建 PR；保留用户原有未提交改动。新 worktree 显式准备依赖与所需本地配置，禁止输出或提交密钥。
- 2026-09-22 issue 裁决：#218 不处理；#219 仅待部署环境核查；#220 categories 标注后续单列；#221 暂不改脱敏默认值与审计原文；#222 协议迁移暂缓，保持 Java 源码、配置、agentUrl、DTO 和现行 wire 契约；#224 的 shadow_compare 保留待 F4.1 裁决。

## 子目录陷阱页（按需加载）

只在三个目录下有 `CLAUDE.md`，承载**根文件不便展开的局部陷阱**，不是必读层级：

- `app/prompts/CLAUDE.md` — 提示词加载器 + ADR 0001 D5 改写纪律
- `tests/CLAUDE.md` — Mock "patch where it's looked up" 陷阱 + TDD 红线
- `scripts/CLAUDE.md` — 25+ 脚本分类目录页

## 核心原则（永远有效）

1. **提示词不硬编码在代码里** —— 从 `app/prompts/**/*.md` 加载；LLM 节点用 `PromptSpec`（`app/prompts/spec.py`，ADR 0023）声明 `inputs`（AgentState 字段）/ `output_model` / `injects` / `user_builder`，`SPEC.build_messages(state)` 拼消息；user 里的规则文本住 `.md` `[user]` 段，代码只供变量；共享拼装用 `app/prompts/blocks.py`，不在子图里复制 `_format_history`
2. **LLM 输出用 `with_structured_output(PydanticModel)`** —— 绝不手工解析 JSON；输出模型每个字段写 `Field(description=)`，这是输出语义的唯一真源（经 function calling schema 下发），提示词正文不再维护 JSON 骨架 / 字段表
3. **每个节点用 `@safe_node` 装饰** —— 异常降级到 `state['error']`，不让图崩；只读 IO 节点（LLM / 后端查询）改用 `@io_node` + `add_io_node` 注册挂 `RetryPolicy`，写类节点绝不自动重试（ADR 0024 D3）
4. **State 字段只通过 TypedDict 约定** —— 新增字段必须先在 `app/graph/state.py` 中声明
5. **TDD 强制**（`.claude/skills/test-driven-development/SKILL.md` 流程）—— 任何 bug fix / 新功能必须先写失败测试：
   - 写测试 → 跑到 RED（测试失败） → 写最小修复代码 → 跑到 GREEN → 全量回归
   - 禁止先改代码再补测试，也禁止跳过 RED 验证
   - `.claude/skills/test-driven-development/SKILL.md` 流程 包含完整 workflow，修改代码前调用
6. **git 里的提示词是唯一真源** —— 改提示词直接改 `app/prompts/**/*.md` + 普通 PR review，`prompt(<scope>)` commit；Dify 已退出上游地位（ADR 0024 D1），YAML 快照冻结在 tag `dify-assets-frozen-20260917（指向 commit fddd94e；tag 仅存本地，远端拒绝 tag 推送，维护者可从该 sha 重建）`，不再有同步 / 导出链路
7. **单动作多订单** —— 每条消息按既有产品与意图优先级执行一个业务动作，多笔订单共用该动作；主图、节点执行接口和评测目录均不提供多动作编排。
8. **标的原文交后端识别** —— LangGraph 只提取代码/名称原文和用户候选选择，不补代码、不计算近月、不查证券池；Java 业务接口负责调用标的工具及权威校验。原文及引用候选不标记为 `from_goats=True`；HTTP `tickers` 保留为空的兼容字段。详见 `docs/backend-instrument-boundary.md`。
9. **节点失败必须 cascade 防御** —— 任一节点写入 `state['error']` 后，下游 conditional 路由必须检查并跳到 fallback render，禁止 cascade 失败。具体：主图 `_route_by_product` 与每子图首节点后的 conditional 都加 `if state.get('error'): return 'fallback'`。fallback 节点输出友好回复（"我没完全理解你的意思，能换种说法重新告诉我吗"）+ trace 记录原 fail 节点名。LLM 解析失败由 `with_structured_output` 自带 1 次重试 + `@safe_node` 兜底捕获 ValidationError 写入 error；不走 HITL（HITL 仅用于 ADR 0006 的业务参数二次确认场景）

## 排查与修复流程（Bug Debug Workflow）

### 1. 从 Langfuse 富 output 定位根因（首选）

`scripts/langfuse/langfuse_eval.py` 每跑完一条 case 会把**结构化富集 JSON** 写到 Langfuse Cloud
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
   - 标的结果错误 → 核对传给 Java 的原文及后端工具日志；本地 `tickers` 不再承载解析结果
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
| 标的未匹配 | 核对 Java 真实回复与提交的原始证券表达；不根据空 `tickers` 生成本地拒绝 | 子图 `backend.py` |
| option place_order 显示"互换订单参数" | render 第3分支缺 `product_type=="swap"` 条件 | `app/nodes/render.py` |
| 多轮 tickers/params 丢失 | 业务对象是 per-turn（ingest 清空，ADR 0024 D2）；跨轮上下文只靠 `history_messages` + `last_confirmed_params`（上一轮已确认订单号，仅作上下文；七条最终确认路径均必须引用当前订单并明确确认具体动作，范围校验统一由 `app/execution/confirmation.py` 执行） | `app/nodes/ingest.py` / `app/nodes/remember_confirmed.py` |
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
.venv/bin/python scripts/langfuse/langfuse_eval.py --local tests/fixtures/categories --ids case-025,case-026 --concurrency 2
```

## 绝对禁止

- **硬编码 API Key / Secret** —— 必须通过 `app.config.get_settings()`，读环境变量
- **在节点函数内抛未捕获异常** —— 用 `@safe_node` 包住
- **MySQL 版本不符合 8.0.19 ≤ v < 9.6.0 的假设** —— AIOMySQLSaver 兼容性硬约束
- **直接 `httpx.AsyncClient` 调后端** —— 走 `OptionClient` / `SwapClient` / `TickerClient` 三个 Protocol（ADR 0001 D2 修订版）
- **在 main 分支直接改业务子图** —— 走 feature branch + PR
- **面向测试编程** —— 禁止为提高通过率硬编码白名单标的，禁止在 `app/` 业务代码里内置"备用实现"开关（如 `DEFAULT_MODE` 环境变量切换查询路径），禁止在 `conftest.py` 用 `autouse` fixture 全局绕过真实业务路径。测试慢应 mock HTTP 层（`_make_client`），不改业务代码路径
- **P0 · 业务代码不能掩盖后端真实响应** —— 严禁在 `app/nodes/render.py` 或子图里加"如果后端返回 X 就改成 Y"的回退逻辑（典型反例：后端返回"正在处理，请勿重复提交"时改用本地 LLM 抽取结果伪造订单卡）。即使 eval 通过率因此下跌，也必须如实透传后端响应。Why: 生产环境下用户会被错误引导，看到伪造的订单卡以为已下单，实际请求被后端 dedup 丢弃；调试时也会误以为业务流程通了。如果是 eval 节奏导致的偶发问题（如多轮间隔太短撞 dedup），workaround 必须放在 `scripts/langfuse_eval.py`（如 turn 间 sleep），**绝不进业务代码** 2026-09-20 用户确认的 Dify 展示规则：Java 业务 `code=500` 的用户文案统一为“交易指令服务暂不可用”，原始 `api_code/api_result` 保留审计；有效成功卡片仍完全由 Java 生成。
- **P0 · 迭代过程中禁止 `git push` / `gh pr create`** —— `/goal` `/iterate-option` 这类自驱动循环里**严禁**调用 `git push` 或 `gh pr create`（即使 commit 已落地）。Why: 这两个命令默认会触发 permission 弹窗 → 循环阻塞等用户点 Yes，被强制 pause。`/goal` 的语义是"持续推进不打断"，远程操作必须等用户**显式**说"push" / "pr" 才能做。本地 `git commit` 可以正常做（不触发权限弹窗），但远程推送和 PR 创建必须留到用户主动指示
- **P0 · 硬编码业务数据字典** —— 严禁在代码或本仓 YAML/JSON 配置里维护**业务数据映射清单**（如"命名指数 → ETF 代码"、"中文名 → windCode"、"产品名 → 行业代码"等）。理由：业务数据规模会快速膨胀到 100+ 条且持续变化（新 ETF/新指数/新产品每月发行），代码侧维护必然过期、漂移、出错。正确做法是 **原文提取 + 后端权威识别**：LangGraph 保留用户证券表达，由 Java 调用对应标的工具识别并校验。把"业务清单"留给后端或业务方维护的数据库，代码侧只负责调用与校验

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
2. **数据集完整性** ✅：fixture 集已扩到 350+；fixture 职责矩阵 + 一致性 lint 已就位（PR #109）；按 B / C / D 桶分别维护
3. **客户现场部署能力** ✅：infra/langfuse self-hosted、`scripts/deploy-customer.sh`（C1.13 / Issue #58）、`.env.customer.template`（C1.12 / Issue #52）、私有化部署文档（C1.11 / Issue #51）
4. **联调与回归** ✅：真后端 e2e 探针（`scripts/probe_*_e2e.py`，D2.1–D2.6 + Dx.1–Dx.2 已 closed）+ DeepSeek Judge 评估（`scripts/langfuse/langfuse_eval.py`）+ business 子图 → 真 client → mock_api 全链路（PR #110，27 测试）
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

按桶 PASS 率与退出门口径见 `docs/m3-m4-roadmap.md`；`scripts/check_fixture_consistency.py` 守 fixture 一致性 lint（提交前本地跑）。

详见：

- 领域语言：`@CONTEXT.md`
- 架构决定：`@docs/adr/`（ADR 0000-0024 共 25 篇，索引见 `docs/adr/README.md`）
- LangGraph 原生重构评估与路线：`@docs/langgraph-architecture-assessment.md` + ADR 0024
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

> 真源与契约：[ADR 0023](../../docs/adr/0023-prompt-as-code-langgraph.md)（PromptSpec）；版本化 / 灰度：[ADR 0003](../../docs/adr/0003-prompt-versioning-by-file-coexistence.md)。
> 局部陷阱：`app/prompts/CLAUDE.md`。本文件只写"怎么做"。

## 占位符纪律

`.md` 里的 `{{var}}` 没有独立渲染层，只有两种合法形态（Dify 时代的 `{{#node_id.var#}}` 已全部改为原生名，ADR 0024 D1）：

- system 段占位符 → 在 `PromptSpec.injects` 登记渲染器（当前业务 system 无动态占位符），`build_messages` 构造期校验存在性
- `[user]` 段占位符 → 只在 user 含规则文本的节点存在（`swap/fresh_counterparty.md`），经 `render_user()` 渲染；其它节点没有 `[user]` 段，user 消息由 `user_builder` 拼变量
- 代码不注入的占位符是悬空规则，LLM 看到的是变量名；属零风险删除档，围绕它的整段规则一起删

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
    gray=True,                                        # 走 _versions.yaml 灰度（resolve_prompt_version）
))

messages, prompt_name = SPEC.build_messages(state)    # [("system", ...), ("user", ...)]
result = await model.with_structured_output(SwapIntentOutput).ainvoke(messages)
```

- 节点默认只用 system 段 + 代码拼变量的 user；user 里若有**规则文本**，写进 `.md` 的 `[user]` 段用 `{{var}}` 占位，`user_builder` 里用 `load_prompt(...).render_user(**vars)` 渲染（先例 `swap/fresh_counterparty.md`）
- **禁止**把提示词正文硬编码进 Python（含"后置追加一段格式指令"这种写法）；**禁止**在 `.md` 里维护 JSON 骨架 / 字段表——字段语义只写在 Pydantic `Field(description=)`
- 共享拼装（历史、对手列表、JSON 列表）只在 `app/prompts/blocks.py` 定义一次，不在子图里复制
- `injects` 登记的占位符必须在 `.md` system 段里真实存在，`build_messages` 构造期校验（`tests/prompts/test_prompt_spec.py`）
- 灰度节点必须把 `build_messages` 返回的 `prompt_name` 写进 `TraceEntry.llm_output["prompt_name"]`（ADR 0003 硬前置：进 `_versions.yaml` 前必须先写 trace，否则版本对比失真）
- 当前 14 个业务 PromptSpec；标的工具在后端执行。system 使用固定资产，历史和参考数据经 `blocks.source_payload` 放入 user。`fresh_counterparty` 的 `[user]` 模板继续经 `render_user` 渲染。

## 来源优先级（ADR 0014 D3-2）

生产真源永远是 git 里的 `app/prompts/**/*.md`；`USE_LANGFUSE_PROMPTS=true` 只允许开发/staging 演练，生产开启即 fail-fast。LangFuse 演练稿用 `scripts/langfuse/promote_langfuse_prompt.py` 晋升为 `_v{N+1}.md`，再走 PR。

## 改提示词的三条路

| 场景 | 做法 | 门槛 |
|---|---|---|
| 瘦身 / 修规则 | 直接改 `app/prompts/**/*.md`；需要时先跑 `scripts/langfuse/langfuse_eval.py` 对比 | 普通 PR review；`prompt(<scope>)` commit |
| 新 LLM 节点 | `.md` 放对目录 + Pydantic Output 模型（每字段 `Field(description=)`）+ `PromptSpec` 声明 + `@safe_node` 节点 + golden case | 普通 PR review |

## 字符数 / 延迟

输入预算统计 system、user 与 function-calling schema；实际 token 和缓存收益以模型 usage 为准。历史瘦身前基线仅作存档。

## Loader 缓存

`load_prompt()` 有 `@lru_cache`；测试里要重载用 `from app.prompts import clear_cache; clear_cache()`。

## 相关 ADR

- ADR 0001 D5：改写决定登记表
- ADR 0003：同目录并存 + `_versions.yaml` 灰度（唯一版本化形态）
- ADR 0014：LangFuse 作为演练区，git 为真源
- ADR 0022：代码迁移完成后的提示词治理模型（**已废弃**）
- ADR 0023：提示词即代码（PromptSpec / AgentState inputs / Pydantic description 输出契约）


<!-- 来源：.claude/rules/testing.md -->

# 测试规范

## 三层测试金字塔

```
   E2E 集成测试 (tests/integration/ + tests/test_cascade_e2e.py)   ← 慢，少，Mock LLM + Mock 后端
   ─────────────────────────────
   子图 / 节点测试 (tests/subgraphs/ · tests/nodes/ · tests/graph/) ← 中等，覆盖关键路径
   ─────────────────────────────
   模型与路由测试 (tests/subgraphs/*/test_models.py · tests/test_intent_route.py) ← 快，多，纯函数单测
```

## pytest 约定

- 所有测试必须 import 时能成功（不联网、不依赖真实 MySQL）
- 异步测试用 `@pytest.mark.asyncio`（`asyncio_mode = "auto"` 已在 pyproject.toml 配置）
- Mock 必须 patch "where it's looked up"，不是定义处

## Mock 陷阱提醒

```python
# ❌ 错误：patch 原定义位置
monkeypatch.setattr("app.tools.option_client.OptionClientHttpx", factory)
# 因为 option/backend.py 与 close/backend.py 都 `from ... import OptionClientHttpx`
# 名字已绑到各自模块，改原模块不生效

# ✅ 正确：patch 所有使用点（先例：tests/test_inquiry_continuation.py）
for target in (
    "app.subgraphs.option.backend.OptionClientHttpx",
    "app.subgraphs.close.backend.OptionClientHttpx",
):
    monkeypatch.setattr(target, factory)
# swap 同理：app.subgraphs.swap.backend.SwapClientHttpx（标的识别已委托 Java，本地无 ticker 子图）
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

- 所有新增意图必须在 `tests/fixtures/categories/` 加至少 2 条用例（现役数据源，`scripts/check_fixture_consistency.py` 校验一致性）
- case 格式沿用对应文件既有方言（详见 `scripts/ai_test_langgraph/README.md`）
- 跑评估：`python scripts/langfuse/langfuse_eval.py --local <fixture>`

## 验证范围

用户指定轻量验证时，只执行最小复现、受影响的关键测试和相关静态检查。全量 pytest、真实黄金集及性能测试留到统一验收，不循环重复；交付中明确未运行的检查。该范围调整不取消业务改动的 RED → GREEN。

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
- ⚠️ 改活跃提示词 → 直接改 `.md` + 普通 PR review，`prompt(<scope>)` commit；需要时自行跑 `scripts/langfuse/langfuse_eval.py` 验证

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
- `.claude/rules/langgraph-patterns.md` — LangGraph 模式
- `.claude/rules/python-style.md` — Python 编码规范
