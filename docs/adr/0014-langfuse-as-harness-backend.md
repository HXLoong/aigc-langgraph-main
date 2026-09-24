# ADR 0014 · LangFuse 作为 Harness 工程的后台服务

- 状态：已采纳
- 日期：2026-05-10
- 关系：修订 [ADR 0004](./0004-trace-granularity-node-level-with-langsmith.md)（trace 后台）与 [ADR 0005](./0005-annotation-roles-judge-plus-business-spotcheck.md)（标注平台）
- 作者：图灵科技 + Tony

## 背景

Harness 需要一个后台承载四件套：**Trace**（节点级 LLM 调用）、**Dataset**（数据集版本管理）、**Evaluation**（LLM Judge 评分）、**Annotation**（业务方标注界面）。原选型 LangSmith 是海外 SaaS，客户企微原话与订单参数会出境，与场外衍生品的金融数据合规要求冲突。LangFuse 开源、可自托管、与 LangGraph 原生集成，满足合规与功能要求。

## 决策

### D1 · 部署模式：生产自托管，数据不出境

- **客户现场强制自托管**：`infra/langfuse/docker-compose.yml`（PostgreSQL + ClickHouse + Redis + MinIO + Web + Worker），trace、数据集、标注数据均留在内网；现场配置严禁指向 LangFuse Cloud。

### D2 · 取代 LangSmith，不双跑

trace 只走 LangFuse 一条通道，由请求入口统一注入 CallbackHandler，子图自然继承。

### D3 · 提示词真源永远是 git

- 生产提示词只从 `app/prompts/**/*.md` 加载；提示词改动走 git PR review（金融审计要求可追溯；提示词须与加载逻辑、Pydantic 输出模型同 commit 演进）。
- LangFuse Prompts 仅作开发演练区：`scripts/langfuse/upload_prompt_to_langfuse.py` 单向把 git 提示词推送到 LangFuse 用于实验，**不从 LangFuse 拉回**（原"LangFuse → git 晋升脚本"已于 2026-09-23 下线）。
- 硬闸门：`environment=production` 且 `USE_LANGFUSE_PROMPTS=true` 时 `load_prompt` 直接报错。

### D4 · 数据流向

| 数据 | 写入 | 读取 |
|---|---|---|
| Trace | LangGraph CallbackHandler | LangFuse UI / API |
| Dataset | `scripts/langfuse/upload_golden_to_langfuse.py` 从 `tests/fixtures/` 同步 | 评测脚本 |
| Score | `scripts/langfuse/langfuse_eval.py`（LLM Judge） | LangFuse UI / 报告 |
| Annotation | 业务方经 Annotation Queue（线上标注待启动） | 回流脚本（待建） |

### D5 · 安全与保留

- API Key 经 `get_settings()` 读取环境变量，不硬编码；`ENABLE_LANGFUSE` 可关闭（CI / 本地）。
- 保留策略（服务端配置，现场部署时核对）：Trace 90 天；Dataset / Score / Annotation 永久。自托管 PostgreSQL / ClickHouse 备份纳入业务库同级。

## 备选方案

- **保留 LangSmith**：数据出境、厂商锁定、国内访问差。
- **自研 Trace + Eval**：投入大，UI 追不上，价值不抵成本。
- **LangFuse Cloud 用于生产**：仍是出境，金融审计有争议。
- **提示词也以 LangFuse 为真源**：绕过 git PR 审计。

## 后果

- 四件套统一，业务方可独立操作，AI 工具可通过 REST API 读取。
- 合规口径：现场强制自托管，trace 与数据不出境。
