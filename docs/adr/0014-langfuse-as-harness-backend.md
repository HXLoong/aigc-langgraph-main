# ADR 0014 · LangFuse 作为 Harness 工程的后台服务

- 状态：已采纳（trace/dataset/eval 四件套决策有效；**部署模式与提示词闸门存在重大实现偏离**，见对应小节）
- 日期：2026-05-10
- 修订：2026-08-27 深度改写为现状口径（wayfinder map #138 / 核查 #142）
- 作者：图灵科技 + Tony

## 上下文

Harness（[ADR 0001](./0001-rewrite-app-with-harness-first.md) / [0002](./0002-comprehensive-runtime-harness.md)）需要后台承载四件套：**Trace**（节点级 LLM 调用）、**Dataset**（golden versioned 管理）、**Evaluation**（LLM judge，[ADR 0005](./0005-annotation-roles-judge-plus-business-spotcheck.md)）、**Annotation**（业务方抽检 UI）。

LangSmith 是海外 SaaS，所有 prompt + LLM 输出（含客户企微原话、订单参数）出境——与场外衍生品的金融数据合规要求冲突，单此一条驱动重新选型。LangFuse（开源，MIT 核心，LangGraph 原生集成）满足合规且功能覆盖需求。

## Decision

### D1 · 部署模式：Self-hosted（⚠️ 现状偏离）

**决策**：LangFuse 自托管内网，所有 trace、dataset、annotation 数据**不出境**；不选 LangFuse Cloud（连 EU Cloud 都因"仍是出境、金融审计争议"被否决）。

**落地资产**：`infra/langfuse/docker-compose.yml` —— 实际 **6 服务**：PostgreSQL + ClickHouse + MinIO + Redis + Worker + Web（原文写 3 组件，本次更正），约 6GB RAM。

**例外决策（#155 裁决，Tony 2026-08-27）**：

- **开发/评测期允许使用 LangFuse Cloud（us.cloud.langfuse.com）**——出境数据限定为 **golden 测试数据**（业务方手写种子 + LLM paraphrase，非生产客户流量）与提示词全文；此风险显式接受，M3.3 现场 sign-off 材料中须向业务方说明。
- **客户现场部署强制 self-hosted**——`.env.customer.template` 指向 `infra/langfuse/` 自托管栈，现场严禁配置 Cloud host。
- 附带闸门（同批落地）：生产环境 `USE_LANGFUSE_PROMPTS=true` 时 `load_prompt` 直接 raise（D3-2 硬闸门）；Langfuse 拉取/注入失败从静默降级升为 warning。

### D2 · 取代 LangSmith，不双跑 ✅

全库无 langsmith 引用，trace 走 LangFuse 单一通道（`app/graph/main.py` 注入 CallbackHandler）。

### D3 · 提示词管理：Git `.md` 是真理来源（⚠️ 实现与决策相反）

**决策**：真理来源永远是 `app/prompts/**/*.md`；生产绝不走 LangFuse 拉提示词；LangFuse Prompts 仅作 staging 演练区，演练通过后经 `promote_langfuse_prompt.py` 晋升为 `_v{N+1}.md` 走 git PR（保留审计屏障）。

**落地现状**：

- ✅ 晋升脚本 `scripts/promote_langfuse_prompt.py <category.name>`：按 [ADR 0003](./0003-prompt-versioning-by-file-coexistence.md) 扫描现有版本写 `_v{N+1}.md`，行为与设计一致。
- **双源开关追认现状**（#155 裁决）：实际机制是 `enable_langfuse && use_langfuse_prompts` 全局布尔（非原设计的 per-prompt `LANGFUSE_PROMPT_OVERRIDE` + `is_staging()`），且开关打开时 **Langfuse 优先、本地 .md 降级为 fallback**——优先级方向与"git 是真理来源"相反；拉取失败仅 `logger.debug` 静默回退，会掩盖"以为在用 Langfuse 版实则本地版"的错配。
- ✅ **生产硬闸门已补齐**（#155 裁决落地，2026-08-27）：`load_prompt` 在 `environment=production` 且 `use_langfuse_prompts=true` 时直接 raise（`tests/test_langfuse_prompt_gate.py` 覆盖）；拉取失败从 debug 静默升为 warning。
- D3-4"晋升后 7 天删 LangFuse 实验版"无自动化承载，降级为 checklist 纪律。

不走 LangFuse 作为生产提示词真理来源的理由不变：金融审计要求提示词改动走 git PR review；提示词与加载逻辑/Pydantic schema/节点函数耦合演进须同 commit；文件 diff 是最自然的 review 形式。

### D4 · 数据流向 ✅

| 数据类型 | 写入 | 读取 |
|---------|------|------|
| Trace | LangGraph CallbackHandler 自动写 | LangFuse UI / API |
| Dataset | `tests/fixtures/*.jsonl` 同步脚本（`upload_golden_to_langfuse.py` 等）| harness runner |
| Score | `scripts/langfuse_eval.py`（DeepSeek Judge）| LangFuse UI / 报告 |
| Annotation | 业务方 LangFuse Annotation Queue（Phase 4 运营待启动）| 回流脚本（待建）|

### D5 · Harness CLI 接入点（现状订正）

- `harness run` ✅、`harness promote-prompt` ✅（委托脚本）
- **`eval` / `diff` / `sync-golden` 仍是 stub（退出码 64）**——评估主入口现为 `scripts/langfuse_eval.py`（M3 主用）
- `harness/langfuse_client.py` 实为 **LangChain CallbackHandler 单例封装**（非 SDK client 封装；未启用返回 None 走 no-op）

### D6 · 数据保留策略（运维约定，仓库内无可验证载体）

Trace 90 天（LangFuse retention policy）/ Dataset、Score、Annotation 永久。落在 LangFuse 服务端配置，现场部署时核对。

### D7 · 失败报告格式 ✅

机器读 = LangFuse Trace API；人读 = LangFuse UI；suspected_node/prompt = harness reporter 启发式层；CI 离线 fallback = 本地 JSON。已落地（详见 ADR 0001 D7）。

### D8 · 安全与配置

- API Key 走 `get_settings()` 读 `LANGFUSE_PUBLIC_KEY/SECRET_KEY`，不硬编码 ✅
- `ENABLE_LANGFUSE` 开关 ✅（CI/本地可关）
- "实例部署在内网 VPC 仅内网可访问"——**同 D1 偏离**：实配公网 US Cloud
- PG/ClickHouse 备份纳入业务库同级——现场部署时随 self-hosted 生效

## 备选方案（历史论证）

1. **保留 LangSmith**：数据出境、厂商锁定、标注收费、国内访问差。
2. **自研 Trace + Eval**：1-2 人月起，UI 追不上，价值不抵成本。
3. **LangFuse Cloud（EU）**：仍是出境，金融审计争议——⚠️ 注意：此项当年被否决，而现状实际用的是更远的 US Cloud，见 D1 偏离。
4. **Prompts 也全用 LangFuse**：与 git 审计要求冲突。

## 后果（现状口径）

- 四件套统一、业务方独立操作、AI 工具可拉 REST API——均成立。
- 合规口径按 D1 例外决策执行：开发期 Cloud 仅承载 golden 测试数据（风险显式接受并向业务方披露），现场强制 self-hosted（#155 已裁决）。
- 文档残留（LangSmith 字样 5 处）随外部引用修正票清理。

## Related

- [ADR 0004](./0004-trace-granularity-node-level-with-langsmith.md)：trace 后台改 LangFuse（保留 node_trace 表结构性约束）
- [ADR 0005](./0005-annotation-roles-judge-plus-business-spotcheck.md)：标注平台改 LangFuse Annotation Queue
- [ADR 0003](./0003-prompt-versioning-by-file-coexistence.md)：D3 在其上叠加 staging 演练区
- 部署模板：`infra/langfuse/docker-compose.yml`
