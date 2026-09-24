<!-- 自动生成：python scripts/sync_agents_md.py —— 禁止手改。
     真源是 scripts/CLAUDE.md；改那里再重新生成，提交前跑 python scripts/sync_agents_md.py --check 校验同步。 -->

# scripts · 运维与评估脚本

> 局部约定。所有脚本应是**幂等 + 可独立运行**的入口，业务逻辑在 `app/` 里实现。

## 脚本分类

### 评估入口

| 脚本 | 用途 |
|---|---|
| `local_eval.py` | 本地 HTTP 业务回归（显式 `tests/fixtures/categories`，真 Java 后端）|
| `langfuse/langfuse_eval.py` | 数据集评估：DeepSeek Judge + per-turn JSON → Langfuse；`--local tests/fixtures/intent` 为 CI 意图集 |
| `run_with_http_tape.py` | 启动本地应用并录制 / 回放工具层 HTTP（节点回归，ADR 0029）|

### 真后端探针（联调用）

| 脚本 | 用途 |
|---|---|
| `probe_real_backend_e2e.py` | 通用真后端连通性 |
| `probe_swap_write_e2e.py` | 互换下单写后端 |
| `probe_option_write_e2e.py` | 期权下单写后端 |
| `probe_close_write_e2e.py` | 平仓下单写后端 |
| `probe_fast_query.py` | 快速询价 GOATS 解析交互式探针（不调后端询价接口）|
| `probe_goats/` | GOATS 19 个业务接口逐个 / 一键探针（凭据从 `.env` 读，写类接口需 `--confirm-write`）|

> 探针**不参与**自动 CI（依赖真后端 + VPN）。本地或客户现场手动跑。

### 灰度与运维

| 脚本 | 用途 |
|---|---|
| `canary_status.py` / `metrics_snapshot.py` | 金丝雀状态查询 |
| `rollback_canary.sh` | 一键回切 |
| `drill_smoke.sh` | 上线 smoke checklist |
| `shadow_compare.py` | 可选的 shadow 对照工具（`DRY_RUN_BACKEND` 模式可用，不进评测门）|
| `run_alerts.py` | 告警轮询 |
| `llm_cost_report.py` | LLM 成本日报 |
| `reconcile_requests.py` | 不确定回执的只读对账；`--apply` 只落库已核实的 Java 原始回复（ADR 0026）|

### 部署与开发

| 脚本 | 用途 |
|---|---|
| `deploy-customer.sh` | 客户私有化部署一键脚本 |
| `local_backend_seed.py` | 本地 Java 后端测试数据准备（见 `docs/testing/local-backend-seed.md`）|

### 一致性 lint（提交前本地跑）

| 脚本 | 用途 |
|---|---|
| `check_alert_threshold_consistency.py` | 告警阈值一致性 lint |
| `check_fixture_consistency.py` | fixture 一致性 lint（categories 业务集 + intent 意图集 + unified）|
| `check_adr_refs.py` | ADR 互引虚悬 + 代码路径与 Markdown 链接存在性 lint（跳过删除线段）|

### 数据维护

| 脚本 | 用途 |
|---|---|
| `convert_csv_to_excel.py` | CSV 测试集 → 单个 Excel 工作簿（每 CSV 一个 sheet）|
| `convert_jsonl_to_csv.py` | JSONL 测试集 → 逐步中文 CSV（仅标准库）|
| `convert_excel_to_jsonl.py` | 黄金 Excel → 期权/互换 JSONL；严格匹配 10/13 列表头顺序，同用例多步合并为一行，支持 `--dry-run` |
| `convert_jsonl_to_excel.py` | categories JSONL → 黄金 Excel，便于人工查看和维护 |
| `derive_intent_fixtures.py` | categories 业务集 → 意图集草稿（只搬 product_type/intent 标签，未标注轮标 review.pending；`--only-labeled` 写入 `tests/fixtures/intent/`）|
| `derive_instrument_fixtures.py` | swap 业务集 → 标的识别意图集草稿（订单数以卡片 `标的代码` 行为准，原文表达任一候选 + 市场限定 → `expected.instruments`；`--dry-run` 出复核表，`--only-reviewed` 写入）|
| `langfuse/upload_golden_to_langfuse.py` | 本地 categories / intent fixture → Langfuse Dataset（`--suite` 按路径自动判定）|
| `langfuse/upload_prompt_to_langfuse.py` | git 提示词单向推送到 Langfuse 演练区（不拉回，ADR 0014）|
| `langfuse/upload_evaluators.py` / `langfuse/upload_score_configs.py` | 同步 Langfuse Code Evaluators 与人工标注 Score Configs |
| `cleanup_checkpoints.py` | checkpoint 三表按线程清理（客户现场运维）|
| `sync_agents_md.py` | CLAUDE.md + .claude/{rules,skills,agents} → AGENTS.md + .agents/skills/（Codex 读取；`--check` 供提交前自检，产物禁止手改）|

## 写新脚本的约定

1. **入口必须 `if __name__ == "__main__":`**，便于独立调用
2. **用 `argparse`**，禁止 `sys.argv` 手工解析
3. **结构化日志**：`logging.getLogger(__name__) + logger.info("k=%s ...", v)`，禁止 print
4. **配置走 `app.config.get_settings()`**，不读环境变量到模块全局
5. **业务逻辑必须在 `app/`**，scripts 只是入口胶水
6. **shell 脚本头**：`#!/usr/bin/env bash` + `set -euo pipefail`
