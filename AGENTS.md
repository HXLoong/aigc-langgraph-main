<!-- 自动生成：python scripts/sync_agents_md.py —— 禁止手改。
     真源是 CLAUDE.md + .claude/rules/*.md；改那里再重新生成，提交前跑 python scripts/sync_agents_md.py --check 校验同步。 -->


# otc-agent · 图灵科技 Project Memory

场外衍生品 AI 指令助手。**FastAPI + LangGraph + MySQL + LangFuse self-hosted**，从 Dify 工作流迁移而来。
企微群客户消息 → 意图解析 → 后端业务/交易系统。

> 目标（[ADR 0030](./docs/adr/0030-goal-restatement-native-langgraph-dataset-eval-harness.md)）：**原生 LangGraph 重构 + 数据集评测与评估 + Harness 工程**；里程碑与 GitHub issue 口径已退役，现状与待办见 [docs/work-plan.md](./docs/work-plan.md)。标的识别归 Java（ADR 0025）；灰度与部署工具链（rollback_canary / drill_smoke / shadow_compare / deploy-customer / Grafana 模板 + on-call runbook）已就绪。

## 关键命令

```bash
# 安装
pip install -e ".[dev]"

# 启动业务依赖
# 先在 Java 现有数据库执行初始化；MYSQL_URI 为唯一数据库连接配置
mysql -h <HOST> -P <PORT> -u <USER> -p --database=<JAVA_DATABASE> < sql/init.sql
cp infra/langfuse/.env.example infra/langfuse/.env   # 首次：填 3 个密钥，见 infra/langfuse/README.md
docker compose -f infra/langfuse/docker-compose.yml --env-file infra/langfuse/.env up -d  # LangFuse self-hosted

# 启动应用
uvicorn app.main:app --reload                # FastAPI（POST /v1/workflows/run，兼容 Dify）

# 轻量测试；当前 .env 开启持久化，单测通过命令级配置隔离数据库依赖
USE_MYSQL_CHECKPOINTER=false REQUEST_IDEMPOTENCY=false ENABLE_LANGFUSE=false pytest tests/test_smoke.py -q
# 完整 pytest / categories 业务集全量 / 性能测试按用户统一验收安排执行，不逐批重复。

# 本地 HTTP 业务回归（仅在准备好授权测试账号和数据后，由主代理或用户执行）
python scripts/local_eval.py --base-url http://127.0.0.1:8201 --data tests/fixtures/categories --case case-025 --concurrency 1
# 全量验收时去掉 --case；只跑显式 categories，不并入 unified。
# 本地真实联调：ENVIRONMENT=staging uvicorn app.main:app --host 127.0.0.1 --port 8201

# Langfuse Dataset Experiment（Judge + 自动 Evaluator；不替代 HTTP/Java 写回与幂等验收）
python scripts/langfuse/langfuse_eval.py --dataset golden_option_inquiry_case --ids case-022 --concurrency 1
# 意图集（不依赖 Java/GOATS；冻结上下文的用例由 harness/intent_runner.py 只跑意图子链、只调 LLM，
# 拒绝验收（及引用上一轮回复的回放）用例走主图 + mock_api；确定性评分本地算，--fail-under 给退出码；
# CI：.github/workflows/intent-eval.yml 仅手动触发；业务集 categories/ 依赖 Java 后端只在开发环境跑；docs/langfuse/workflow-guide.md §8）
python scripts/langfuse/langfuse_eval.py --local tests/fixtures/intent --concurrency 3 --fail-under 0.95 --report .harness-runs/intent-eval.json

# Harness CLI（备用 / 本地快速 smoke，无 Judge；run 需授权测试身份，见 harness/README.md）
python -m harness doctor
python -m harness run --backend real|mock|dry-run
python -m harness node-run --data tests/fixtures/nodes   # 节点级回归（ADR 0029）

# 真后端探针（联调用）
python scripts/probe_real_backend_e2e.py
python scripts/probe_swap_write_e2e.py
python scripts/probe_option_write_e2e.py
python scripts/probe_close_write_e2e.py
```

## 项目结构

```
app/
├── main.py                  # FastAPI 入口 + lifespan + HTTPMetricsMiddleware + /metrics
├── config.py                # pydantic-settings 配置加载
├── api/                     # 仅 HTTP 层：routes.py（POST /v1/workflows/run）/ nodes.py（/v1/nodes/*）/ health.py（/health, /ready）
│                            # / turn_state.py（一轮输入 → State）/ notifications / errors
├── graph/                   # state（AgentState）/ main（主图组装；app/graph 内唯一依赖业务节点的模块）/ safe_node
│                            # / retry（io_node + RetryPolicy）/ cascade / business_params（写入前形状校验）
├── nodes/                   # 主图节点：ingest / entry_route / fast_query（快速询价 + 存量指令）/ pre_route
│                            # / route_rules + intent_route（规则 → LLM → sticky）/ persist_intent / render / fallback
│                            # / remember_confirmed / record_history / persist
├── subgraphs/               # 三个业务子图（互不依赖）+ common.py（意图分发路由 + <product>_unknown 兜底）
│   ├── swap/                # intent / place_order（候选 → normalize → submit）/ select_counterparty / select_ticker
│   │                        # / fresh_counterparty / apply_picks / confirm（确定性口令与引用校验）/ cancel / query_order
│   │                        # / multimodal（图片 + Excel）+ backend / graph / models
│   ├── option/              # intent + extract_inquiry（LLM）+ 其余 extract_*（确定性）+ place_params / sanitize / backend
│   └── close/               # intent / place_close（引用解析链）/ cancel_close / confirm_close / confirm_cancel
│                            # / holding_query / query_status + reference_parser / aggregate / backend
├── domain/                  # 纯业务规则（无 IO）：order_ids（订单号形态单一来源）/ numerals / confirmation
│                            # （七条最终确认路径的范围校验，ADR 0021）/ tenor / fast_execution / sanitize
├── extraction/              # 字段证据契约：FieldCandidate / FieldRecord / 锁定（ADR 0027）
├── node_execution/          # 节点契约真源 catalog.py + 单节点执行（registry / prepare / executor）
├── tools/                   # Client Protocol：option_client / swap_client / message_client / goats_agent_client
│                            # （ticker_client 只供本地验收脚本）+ http_pool / receipts / bot_context
├── llm/clients.py           # LLM 工厂（get_qwen_*）：模型由 .env 的 QWEN_MODEL_* 选择，按 ADR 0020 统一 DeepSeek-V4-pro
├── checkpointer/factory.py  # AIOMySQLSaver 连接池
├── storage/                 # MySQL 表与读写：mysql（MYSQL_URI 唯一解析）/ idempotency / reconciliation / node_trace
├── observability/           # tracing / metrics / alerts / canary / health_probes / logs / privacy / node_labels
└── prompts/                 # 提示词资产（git 唯一真源；router / swap / option / option_close + judge / system）

# 分层依赖方向见 docs/architecture/README.md §分层，由 tests/test_architecture_layers.py 守护

harness/                     # 评测台：run（HTTP 回归）/ node-run（节点回归）/ 意图级 runner / Langfuse Evaluator，见 harness/README.md
scripts/                     # 评估入口、真后端探针、灰度与运维、一致性 lint，目录页见 scripts/CLAUDE.md
infra/                       # langfuse/（self-hosted Compose）+ grafana/（面板模板）
docs/                        # 文档地图与存放规则见 docs/README.md（lint 强制）
tests/                       # 3500+ 条，布局见 tests/CLAUDE.md
tests/fixtures/              # intent/（意图集，只调 LLM）+ categories/（业务验收集，6 文件，依赖 Java）+ nodes/（节点级）
                             # + unified_golden.jsonl（B 方言历史参考集，显式 --include-unified 加载），见 tests/fixtures/README.md
```

## 团队工具链：Claude Code 与 Codex 共用一份纪律

团队主用 Codex。Codex 只读根目录与各级子目录的 `AGENTS.md` 和 `.agents/skills/<name>/SKILL.md`，不读本文件、
`.claude/rules/`、`.claude/skills/`、`.claude/agents/`。因此这些 **Codex 产物全部由 `python scripts/sync_agents_md.py` 生成，禁止手改**：

- 根 `AGENTS.md` = 本文件 + 并入 `.claude/rules/{prompt-management,testing,docs,langgraph-patterns}.md`，其余 rules 只列路径（控制上下文体积）
- `app/prompts` / `tests` / `scripts` 下的 `AGENTS.md` = 各自的 `CLAUDE.md`
- `.agents/skills/<name>/` = `.claude/skills/<name>/`（frontmatter 收敛为 Agent Skills 标准的 `name` / `description` / `metadata`）
  + `.claude/agents/*.md`（生成可复用角色技能）；Codex 支持显式授权的子代理，技能通过 `$name` 调用

改纪律或流程只改 `CLAUDE.md` / `.claude/**`，再跑生成脚本一起提交；提交前跑 `python scripts/sync_agents_md.py --check` 守同步。

## 并行实施与验证范围

- 用户明确授权后可使用主代理与最多三个子代理。实现任务使用独立 worktree 和分支；子代理提交后由主代理审阅、集成。
- 每个任务指定文件所有者与验收用例；公共 State、配置、数据库结构及服务生命周期由主代理统一处理。子代理提出公共契约需求，不互相覆盖共享文件。
- Java 源码不修改；本地 Java 48080 → 48081，LangGraph 使用本地端口，禁止使用 10.49.91.229:8201；应用持久化统一 MYSQL_URI。
- 当前重构采用轻量验证：业务改动先最小 RED，再 GREEN 与相关关键测试；用户要求最终统一测试时，不逐批跑全套 pytest、categories 全量真实回归或压测。
- 真实写入测试仅由主代理调度；先确认授权测试账号、群、对手及持仓。业务回归使用 scripts/local_eval.py 和显式 tests/fixtures/categories，不并入 unified。
- 新建或移动文档先按 `.claude/rules/docs.md` 判定归属目录（一次性报告进 `docs/reports/YYYY-MM-DD-<topic>.md`），跑 `python scripts/check_docs_layout.py`。
- 任务和证据记录在 tmp；区分实现完成、专项通过、待用户验收、外部阻塞。外部阻塞不可写成已完成；全量结果未经运行不得宣称通过。
- 不 push、不创建 PR；保留用户原有未提交改动。新 worktree 显式准备依赖与所需本地配置，禁止输出或提交密钥。
- 2026-09-22 issue 裁决：#218 不处理；#219 仅待部署环境核查；#220 categories 标注后续单列；#221 暂不改脱敏默认值与审计原文；#222 协议迁移暂缓，保持 Java 源码、配置、agentUrl、DTO 和现行 wire 契约；#224 的 shadow_compare 保留待 F4.1 裁决。

## 子目录陷阱页（按需加载）

只在三个目录下有 `CLAUDE.md`，承载**根文件不便展开的局部陷阱**，不是必读层级：

- `app/prompts/CLAUDE.md` — 目录易错点（命名不对称 / judge·system 非 PromptSpec / `_versions.yaml`）+ `.md` 文件格式
- `tests/CLAUDE.md` — 目录布局 + 命令级隔离依赖等局部陷阱
- `scripts/CLAUDE.md` — 脚本分类目录页 + 写新脚本约定

## 核心原则（永远有效）

1. **提示词不硬编码在代码里** —— 从 `app/prompts/**/*.md` 加载；LLM 节点用 `PromptSpec`（`app/prompts/spec.py`，ADR 0023）声明 `inputs`（AgentState 字段）/ `output_model` / `injects` / `user_builder`，`SPEC.build_messages(state)` 拼消息；user 里的规则文本住 `.md` `[user]` 段，代码只供变量；共享拼装用 `app/prompts/blocks.py`，不在子图里复制 `_format_history`
2. **LLM 输出用 `with_structured_output(PydanticModel)`** —— 绝不手工解析 JSON；输出模型每个字段写 `Field(description=)`，这是输出语义的唯一真源（经 function calling schema 下发），提示词正文不再维护 JSON 骨架 / 字段表
3. **每个节点用 `@safe_node` 装饰** —— 异常降级到 `state['error']`，不让图崩；只读 IO 节点（LLM / 后端查询）改用 `@io_node` + `add_io_node` 注册挂 `RetryPolicy`，写类节点绝不自动重试（ADR 0024 D3）
4. **State 字段只通过 TypedDict 约定** —— 新增字段必须先在 `app/graph/state.py` 中声明
5. **TDD 强制** —— 任何 bug fix / 新功能必须先写失败测试：
   - 写测试 → 跑到 RED（测试失败） → 写最小修复代码 → 跑到 GREEN → 受影响测试回归（全量按统一验收，见 testing.md「验证范围」）
   - 禁止先改代码再补测试，也禁止跳过 RED 验证
   - 完整步骤见 `test-driven-development` skill（用户显式调用 `/test-driven-development` 或说"用tdd"时加载）
6. **git 里的提示词是唯一真源** —— 改提示词直接改 `app/prompts/**/*.md` + 普通 PR review，`prompt(<scope>)` commit；Dify 已退出上游地位（ADR 0024 D1），YAML 快照只作历史证据（commit `fddd94e`），不再有同步 / 导出链路
7. **单动作多订单** —— 每条消息只执行一个业务动作，多笔订单共用该动作；不提供多动作编排（细则见 `.claude/rules/langgraph-patterns.md`）。
8. **标的原文交后端识别**（ADR 0025）—— LangGraph 只提取代码/名称原文和用户候选选择，不补代码、不计算近月、不查证券池；Java 业务接口负责调用标的工具及权威校验。原文及引用候选不标记为 `from_goats=True`；HTTP `tickers` 保留为空的兼容字段。详见 `docs/architecture/backend-instrument-boundary.md`。
9. **节点失败必须 cascade 防御** —— 任一节点写入 `state['error']` 后，下游条件路由必须先检查错误并转兜底，禁止 cascade 失败：主图 `_route_after_intent` 等转 `fallback` / `render`，子图 `_route_after_<p>_intent` 先查 `has_error` 转 `<p>_unknown`。兜底输出统一的未知指令引导文案（`Settings.default_reply`）+ trace 记录原 fail 节点名。LLM 结构化解析失败由 `@io_node` + RetryPolicy 重试（默认最多 2 次，SDK `max_retries=0`），耗尽后写入 error；写操作的二次确认统一走文本二阶段（ADR 0021），不使用 interrupt

## 排查与修复流程（Bug Debug Workflow）

### 1. 从 Langfuse 富 output 定位根因（首选）

`scripts/langfuse/langfuse_eval.py` 每跑完一条 case 会把**结构化富集 JSON** 写到自托管 LangFuse
（地址取 `LANGFUSE_BASE_URL`，本地默认 http://127.0.0.1:3000），outer span output 包含：

```jsonc
{
  "expected": "Judge 期望输出",
  "score": 0.0,
  "judge_comment": "Judge 一句话评语",
  "turns": [
    {"turn": 1, "raw": "用户原始输入", "reply": "机器人回复",
     "product_type": "option", "intent": "new_inquiry",
     "tickers": [],
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
   - `place_params` 字段漏 → swap 看 `swap/place_order.md` 提示词与 `normalize`，close 看 `option_close/place_close.md`，option 看 `option/place_params.py`（确定性解析）
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
- `trace` 每轮由 ingest 清空（reducer 为 `merge_by_id`），只含本轮节点

**常见根因模式**：

| 现象 | 根因 | 文件 |
|---|---|---|
| 第2轮路由走了 LLM 而非规则 / sticky | 规则层未命中或 sticky 继承条件不满足 | `app/nodes/route_rules.py` / `app/nodes/intent_route.py` |
| 标的未匹配 | 核对 Java 真实回复与提交的原始证券表达；不根据空 `tickers` 生成本地拒绝 | 子图 `backend.py` |
| 多轮 tickers/params 丢失 | 业务对象是 per-turn（ingest 清空，ADR 0024 D2）；跨轮上下文只靠 `history_messages` + `last_confirmed_params`（上一轮已确认订单号，仅作上下文；七条最终确认路径均必须引用当前订单并明确确认具体动作，范围校验统一由 `app/domain/confirmation.py` 执行） | `app/nodes/ingest.py` / `app/nodes/remember_confirmed.py` |
| 后端返回"订单不存在" | 参数中 orderId/Q- 单号提取错误 | 子图 extract 节点 + 提示词 |

### 2. TDD 修复（强制）

找到根因后，**必须先写失败测试再改代码**（`.claude/skills/test-driven-development/SKILL.md` 流程）：

```bash
# 1. 写 tests/xxx/test_yyy.py，体现 bug 的最小复现
# 2. 确认 RED
USE_MYSQL_CHECKPOINTER=false REQUEST_IDEMPOTENCY=false ENABLE_LANGFUSE=false python -m pytest tests/xxx/test_yyy.py -v
# 3. 写最小修复
# 4. 确认 GREEN + 受影响测试回归（全量由 CI / 统一验收跑）
```

### 3. eval 回归

修完跑对应 case 确认：

```bash
python scripts/langfuse/langfuse_eval.py --local tests/fixtures/categories --ids case-025,case-026 --concurrency 2   # 依赖 Java，由主代理调度
```

## 绝对禁止

- **硬编码 API Key / Secret** —— 必须通过 `app.config.get_settings()`，读环境变量
- **在节点函数内抛未捕获异常** —— 用 `@safe_node` 包住
- **MySQL 版本不符合 8.0.19 ≤ v < 9.6.0 的假设** —— AIOMySQLSaver 兼容性硬约束
- **直接 `httpx.AsyncClient` 调后端** —— 走 `app/tools/*_client.py` 的 Client Protocol + `http_pool`（见 langgraph-patterns「IO 与错误」）
- **在 main 分支直接改业务子图** —— 走 feature branch + PR
- **面向测试编程** —— 禁止为提高通过率硬编码白名单标的，禁止在 `app/` 业务代码里内置"备用实现"开关（如 `DEFAULT_MODE` 环境变量切换查询路径），禁止在 `conftest.py` 用 `autouse` fixture 全局绕过真实业务路径。测试慢应在 HTTP 层 mock（`httpx.MockTransport` 或 `tests/integration` 的 mock_api），不改业务代码路径
- **P0 · 业务代码不能掩盖后端真实响应** —— 严禁在 `app/nodes/render.py` 或子图里加"如果后端返回 X 就改成 Y"的回退逻辑（典型反例：后端返回"正在处理，请勿重复提交"时改用本地 LLM 抽取结果伪造订单卡）。即使 eval 通过率因此下跌，也必须如实透传后端响应。Why: 生产环境下用户会被错误引导，看到伪造的订单卡以为已下单，实际请求被后端 dedup 丢弃；调试时也会误以为业务流程通了。如果是 eval 节奏导致的偶发问题（如多轮间隔太短撞 dedup），workaround 必须放在 `scripts/langfuse/langfuse_eval.py`（如 turn 间 sleep），**绝不进业务代码**。业务方确认的展示规则：Java 业务 `code=500` 的用户文案统一为“交易指令服务暂不可用”，原始 `api_code/api_result` 保留审计；有效成功卡片仍完全由 Java 生成。
- **P0 · 迭代过程中禁止 `git push` / `gh pr create`** —— `/goal` `/iterate-option` 这类自驱动循环里**严禁**调用 `git push` 或 `gh pr create`（即使 commit 已落地）。Why: 这两个命令默认会触发 permission 弹窗 → 循环阻塞等用户点 Yes，被强制 pause。`/goal` 的语义是"持续推进不打断"，远程操作必须等用户**显式**说"push" / "pr" 才能做。本地 `git commit` 可以正常做（不触发权限弹窗），但远程推送和 PR 创建必须留到用户主动指示
- **P0 · 硬编码业务数据字典** —— 严禁在代码或本仓 YAML/JSON 配置里维护**业务数据映射清单**（如"命名指数 → ETF 代码"、"中文名 → windCode"、"产品名 → 行业代码"等）。理由：业务数据规模会快速膨胀到 100+ 条且持续变化（新 ETF/新指数/新产品每月发行），代码侧维护必然过期、漂移、出错。正确做法是 **原文提取 + 后端权威识别**：LangGraph 保留用户证券表达，由 Java 调用对应标的工具识别并校验。把"业务清单"留给后端或业务方维护的数据库，代码侧只负责调用与校验

## 代码风格

- Python 3.11+，严格类型提示
- ruff lint，目标行宽 100（E501 未强制）
- 异步优先：能 async 就 async
- 中文注释 OK，docstring 简洁清晰
- 不加 emoji（生产代码）

## 当前工作面（按 ADR 0030）

三条主线的已落地项与未完成项只在 [docs/work-plan.md](./docs/work-plan.md) 维护；评测门只有一套（ADR 0030 D3）：数据集 PASS 率不低于前值 → 节点 fixture 回归 → CI 全绿（ruff / mypy / 一致性 lint / 全量 pytest）→ 上线观察指标。golden case 来源分桶（B / C / D）的定义见 `CONTEXT.md`。

详见：

- 领域语言：`@CONTEXT.md`
- 架构决定：`@docs/adr/`（索引见 `docs/adr/README.md`）
- LangGraph 原生重构目标架构：ADR 0024
- Java 契约：`@docs/api-contracts/java-backend.md`
- 工作计划：`@docs/work-plan.md`
- on-call SOP：`@docs/operations/on-call-runbook.md` + `@docs/operations/troubleshooting-sop.md`

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

> 真源与契约：ADR 0023（`docs/adr/0023-prompt-as-code-langgraph.md`，PromptSpec）；版本化 / 灰度：ADR 0003（`docs/adr/0003-prompt-versioning-by-file-coexistence.md`）。
> 局部陷阱：`app/prompts/CLAUDE.md`。本文件只写"怎么做"。

## 占位符纪律

`.md` 里的 `{{var}}` 没有独立渲染层，只有两种合法形态：

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

## 来源优先级（ADR 0014 D3）

生产真源永远是 git 里的 `app/prompts/**/*.md`，生产环境不从 Langfuse 拉取提示词；`USE_LANGFUSE_PROMPTS=true` 只允许开发 / staging 演练（生产开启即 fail-fast）。提示词改动直接在 git 里改、走 PR，演练结果不回写 git。

## 改提示词的两条路

| 场景 | 做法 | 门槛 |
|---|---|---|
| 瘦身 / 修规则 | 直接改 `app/prompts/**/*.md`；需要时先跑 `scripts/langfuse/langfuse_eval.py` 对比 | 普通 PR review；`prompt(<scope>)` commit |
| 新 LLM 节点 | `.md` 放对目录 + Pydantic Output 模型（每字段 `Field(description=)`）+ `PromptSpec` 声明 + `@io_node` 节点（`add_io_node` 注册）+ golden case | 普通 PR review |

## 字符数 / 延迟

输入预算统计 system、user 与 function-calling schema；实际 token 和缓存收益以模型 usage 为准。长提示词显著影响 P95 延迟，评估时关注延迟指标。

## Loader 缓存

`load_prompt()` 有 `@lru_cache`；测试里要重载用 `from app.prompts import clear_cache; clear_cache()`。


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

- 所有测试在 CI 占位环境变量下必须 import 成功（不联网、不依赖真实 MySQL；占位 env 见 `.github/workflows/ci.yml` fast job）
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
- **后端调用**：单元测试 mock Client Protocol 的使用点；集成测试走 `mock_api`（`tests/integration/`，ASGITransport 内存直连）；真后端联调只用 `scripts/probe_*.py`，不进 pytest

## Golden Set

- 所有新增意图必须在 `tests/fixtures/categories/` 加至少 2 条用例，并在 `tests/fixtures/intent/` 补逐轮意图标签（`scripts/check_fixture_consistency.py` 校验一致性）
- case 格式沿用对应文件既有方言（详见 `tests/fixtures/README.md`）
- 跑评估：意图集 `python scripts/langfuse/langfuse_eval.py --local tests/fixtures/intent`；依赖 Java 的业务集按 `run-eval` skill 由主代理调度

## 验证范围

用户指定轻量验证时，只执行最小复现、受影响的关键测试和相关静态检查。全量 pytest、真实黄金集及性能测试留到统一验收，不循环重复；交付中明确未运行的检查。该范围调整不取消业务改动的 RED → GREEN。

## 提交前自检（CI fast job 同款）

```bash
T="USE_MYSQL_CHECKPOINTER=false REQUEST_IDEMPOTENCY=false ENABLE_LANGFUSE=false"
env $T pytest <受影响的测试路径> -q               # 全量 pytest 由 CI / 统一验收跑
ruff check app/ tests/ harness/ scripts/probe_goats/
python -m mypy app/ harness/
python scripts/check_alert_threshold_consistency.py
python scripts/check_fixture_consistency.py
python scripts/check_adr_refs.py
python scripts/check_docs_layout.py
python scripts/sync_agents_md.py --check
```

## 何时写测试

- ✅ 新增节点函数 → 加路由测试
- ✅ 新增 Pydantic 模型 → 加字段校验测试
- ✅ 新增业务逻辑分支 → 加 E2E 覆盖
- ✅ 修 bug → 先写复现测试，再修
- ⚠️ 改活跃提示词 → 直接改 `.md` + 普通 PR review，`prompt(<scope>)` commit；需要时自行跑 `scripts/langfuse/langfuse_eval.py` 验证

## 选择性运行

```bash
pytest -k "not e2e"             # 跳过 E2E
pytest -k "swap"                # 只跑互换相关
pytest --lf -x                  # 只跑上次失败的，遇错即停
pytest --cov=app.nodes          # 覆盖率
```


<!-- 来源：.claude/rules/docs.md -->

# 文档存放规则

> 唯一真源：`docs/README.md`「存放规则」（归属判定表 + 硬性约束 + 评审约定），CI 由 `scripts/check_docs_layout.py` 强制。

agent 新建或移动文档时：

1. **先读 `docs/README.md`「存放规则」判定归属**；能并入已有文档的一节就不新建文件
2. 一次性的评估 / 审阅 / 调研 / 复盘结论写 `docs/reports/YYYY-MM-DD-<topic>.md`；现状与待办更新 `docs/work-plan.md`
3. 不在仓库根目录或 `docs/` 根散落分析、计划、方案类 `.md`；生成物写 `.harness-runs/` 或 `tmp/`
4. 文件名小写 kebab-case；新文档登记到所在目录的 `README.md`
5. 移动 / 改名时全仓更新引用，跑 `python scripts/check_docs_layout.py` 零违规


<!-- 来源：.claude/rules/langgraph-patterns.md -->

# LangGraph 模式

## 状态与边界

- 共享输入/输出字段在 app/graph/state.py 的 AgentState 声明；子图临时字段可放继承它的私有 TypedDict，output_schema 限制写回范围。
- 一轮唯一输入入口为 app/api/turn_state.py::inputs_to_state。per-turn 字段在 ingest 重置；跨轮记忆、会话活动时间遵循已实现的过期逻辑。
- trace 使用 merge_by_id，history_messages 使用 merge_history，field_records 使用 merge_fields；新并行通道选择明确的 reducer，不照搬累加以免重复。
- 节点返回 partial update，不原地修改输入；交易最终值由 Code 归一化和权威源校验。来源记录及锁定必须在实际后端请求边界生效。
- 子图已返回 CompiledStateGraph 时直接嵌入，不再次 compile；以 app/subgraphs/*/graph.py 当前函数签名为准。

## IO 与错误

- 纯计算及写类节点用 @safe_node；只读 IO 用 @io_node，并通过 add_io_node 注册 RetryPolicy。默认最多2次尝试，LLM SDK max_retries=0；写接口不自动重试。
- add_io_node 在最后一次可重试失败时由原节点返回 ErrorInfo，沿原图边完成汇合、回复和审计；with_error_handler=False 才在耗尽后继续抛出。主图与并行错误收尾由 tests/graph/test_retry_recovery.py 守护。
- 错误由 ErrorInfo 和 cascade 路由处理；后端查询失败不能伪装成空记录继续交易。
- 条件路由为纯函数，错误优先转兜底：主图 `_route_after_intent` 等转 `fallback` / `render`，子图内 `_route_after_<p>_intent` 转 `<p>_unknown`（先查 `has_error`）；副作用只在节点里执行。
- 外部请求只经 `app/tools/*_client.py` 的 Protocol（OptionClient / SwapClient / MessageClient / GoatsAgentClient）+ `app.tools.http_pool` 单例池，不在节点里 new `httpx.AsyncClient`；TickerClient 只供本地验收脚本。子图 backend.py 负责 DTO 构造、BotContext 身份、字段锁定和真实回复透传。
- 每条消息按既有产品与意图优先级进入一个业务分支，该分支识别出的多笔订单统一使用本轮动作；混合措辞不按分句拆成不同动作，也不新增多动作识别门禁。例如识别为撤单申请后，A、B 两笔订单都按撤单申请处理。原有身份、归属、状态和确认校验继续执行；提交保留原 messageId，遵守 Java 幂等与批量契约。

## 提示词

- 每个 LLM 节点声明 PromptSpec；模型使用 with_structured_output，字段说明由 Pydantic Field(description=) 提供。
- 原文候选含 evidence/confidence/source；Code 验证原文并做单位/枚举/身份解析。禁止手工 JSON 容错或模型直接决定交易最终值。
- 无新增 ReAct/ToolNode/bind_tools 路线；工具由 Code 节点选择调用。

## 持久化与运行

- 生产 checkpointer 使用 app/checkpointer/factory.py 的池及表前缀适配，唯一连接配置 MYSQL_URI。
- 首次通过 sql/init.sql 初始化；启动只读校验，不在节点调用 saver.setup 建表，不使用生产单连接 from_conn_string。
- 测试使用 InMemorySaver；没有跨轮要求的纯计算子图可显式 checkpointer=False。
- thread_id 固定为 conversation_id；消息、群、用户身份必须沿用真实入口，禁止截断数字ID。
- 确认采用文本两阶段：七条最终确认路径均须明确动作并引用当前订单，范围由 app/domain/confirmation.py 校验；历史记忆及程序生成的引用不能替代用户引用。
- 不引入 interrupt 确认；递归上限通过 API 的统一 config 设置。
- Langfuse callbacks 由请求入口统一注入，子图自然继承；本地审计写 langgraph_node_trace。
- 节点公共契约只维护在 app/node_execution/catalog.py；执行平台负责 schema 与客户端注入，harness 负责展示和回放策略。暴露范围可不同，写节点保持禁止回放。


# 附二：其余仓库规则（按需读取，同样具有约束力）

- `.claude/rules/git-workflow.md` — Git 工作流
- `.claude/rules/python-style.md` — Python 编码规范
