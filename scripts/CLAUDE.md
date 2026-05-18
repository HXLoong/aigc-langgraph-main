# scripts · 运维与评估脚本

> 局部约定。所有脚本应是**幂等 + 可独立运行**的入口，业务逻辑在 `app/` 里实现。

## 脚本分类

### 评估入口

| 脚本 | 用途 |
|---|---|
| `langfuse_eval.py` | **M3 主用**：DeepSeek Judge + per-turn JSON → Langfuse |
| `langfuse_eval_clean.py` | 清理 Langfuse 旧 run 记录 |
| `eval_golden.py` | 旧版本地评估（保留兼容）|
| `run_option_eval.sh` / `run_real_llm_harness.sh` | 评估封装 |

### 真后端探针（M3 联调）

| 脚本 | 用途 |
|---|---|
| `probe_real_backend.py` / `probe_real_backend_e2e.py` | 通用真后端连通性 |
| `probe_swap_write_e2e.py` | 互换下单写后端 |
| `probe_option_write_e2e.py` | 期权下单写后端 |
| `probe_close_write_e2e.py` | 平仓下单写后端 |
| `probe_ticker_e2e.py` / `probe_ticker_d2_4.py` | 标的识别真后端 |

> 探针**不参与**自动 CI（依赖真后端 + VPN）。本地或客户现场手动跑。

### 灰度与运维（M4 工具链）

| 脚本 | 用途 |
|---|---|
| `canary_status.py` / `metrics_snapshot.py` | 金丝雀状态查询 |
| `rollback_canary.sh` | 一键回切 |
| `drill_smoke.sh` | 上线 smoke checklist |
| `shadow_compare.py` | LangGraph vs Dify 双跑对比（`DRY_RUN_BACKEND` 模式可用）|
| `promote_langfuse_prompt.py` | Prompt 晋升（label `production`）|
| `run_alerts.py` | 告警轮询 |
| `llm_cost_report.py` | LLM 成本日报 |

### 部署与开发

| 脚本 | 用途 |
|---|---|
| `deploy-customer.sh` | 客户私有化部署一键脚本 |
| `dev.sh` / `start_backend.sh` | 本地开发起服务 |

### CI lint

| 脚本 | 用途 |
|---|---|
| `check_alert_threshold_consistency.py` | 告警阈值一致性 lint |
| `check_fixture_consistency.py` | golden fixture 一致性 lint |

### 数据维护

| 脚本 | 用途 |
|---|---|
| `convert_testcase_to_jsonl.py` | 客户原始用例 → golden.jsonl |
| `merge_golden.py` | 合并多个 golden 文件 |
| `upload_dataset_to_langfuse.py` | golden → Langfuse dataset |
| `export_dify_prompts.py` | Dify YAML → app/prompts/**/*.md |

### 一次性 / Demo

| 脚本 | 用途 |
|---|---|
| `demo_closed_loop.py` | 闭环 demo（教学/演示用）|

## 写新脚本的约定

1. **入口必须 `if __name__ == "__main__":`**，便于独立调用
2. **用 `argparse`**，禁止 `sys.argv` 手工解析
3. **结构化日志**：`logging.getLogger(__name__) + logger.info("k=%s ...", v)`，禁止 print
4. **配置走 `app.config.get_settings()`**，不读环境变量到模块全局
5. **业务逻辑必须在 `app/`**，scripts 只是入口胶水
6. **shell 脚本头**：`#!/usr/bin/env bash` + `set -euo pipefail`
