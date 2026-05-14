# 评估与迭代方案（M3 阶段）

> Judge：DeepSeek V4（Anthropic 兼容端点，thinking=4096 tokens）
> 范围：全链路（swap / option / option_close / ticker），golden.jsonl 当前 350+ 条
> 状态：基础设施完成 ✅，主基线已跑通；M3 阶段持续按子链路迭代

---

## 一、已完成

### 基础设施

| 组件 | 文件 | 状态 |
|---|---|---|
| 评估脚本（DeepSeek Judge + per-turn 富集 JSON）| `scripts/langfuse_eval.py` | ✅ 单轮 / 多轮 / Langfuse Cloud 写回 |
| Dataset 上传 | `scripts/upload_golden_to_langfuse.py` / `scripts/upload_option_dataset.py` | ✅ |
| JSONL 转换 | `scripts/convert_testcase_to_jsonl.py` | ✅ Excel/CSV → JSONL |
| 本地 golden | `tests/fixtures/golden.jsonl`（350+）+ `golden_ticker_2026-05.jsonl`（34）| ✅ |
| 真后端 e2e 探针 | `scripts/probe_*_e2e.py`（swap / option / close / ticker / real_backend） | ✅ |
| Token / 成本估算 | `harness/token_tracker.py` + `scripts/llm_cost_report.py` | ✅ |
| 报告器（按桶分桶 + 怀疑节点）| `harness/reporter.py` + `tests/test_reporter_*` | ✅ |
| 期权链路迭代 skill | `.claude/skills/iterate-option/SKILL.md` | ✅ |
| 通用评估 skill | `.claude/skills/run-eval/` | ✅ |

### 数据流

```
本地 tests/fixtures/golden.jsonl（350+ 条）
        │
        ├──→ scripts/upload_golden_to_langfuse.py
        │            │
        │            ▼
        │     Langfuse Dataset
        │            │
        ▼            ▼
scripts/langfuse_eval.py
  ├── InMemorySaver（不依赖 MySQL checkpoint）
  ├── 真实 Qwen LLM（测提示词效果）
  ├── 真实后端 / 本地 mock（OTC_API_BASE_URL 切换）
  ├── MySQL 标的池直查（aigc-test.stock_exchange_sec_data, ~14k 条）
  └── DeepSeek V4 Judge（Anthropic 端点, thinking=4096）
        │
        ▼
  Langfuse Cloud outer span output（结构化富集 JSON）
  + stdout per-turn 文本（trace / quote / reply）
```

每条 case 的 outer span output 包含 `expected` / `score` / `judge_comment` + `turns[i]`（含 product_type / intent / tickers / place_params / api_result / error / trace），见 CLAUDE.md "排查与修复流程" 小节。

---

## 二、当前进行（M3 工程联调）

### 主线 · 持续评估迭代

```bash
# 全量基线
python scripts/langfuse_eval.py --local tests/fixtures/golden.jsonl --concurrency 4

# 按 case 子集复跑（修一处 bug 后验证）
python scripts/langfuse_eval.py --local tests/fixtures/golden.jsonl --ids opt-001,opt-018 --concurrency 2

# 按子链路批量（option 链路）
.claude/skills/iterate-option/SKILL.md  # 跑→归因→TDD 修→重跑的自驱动循环
```

迭代闭环（每次发现失败）：

```
读 Langfuse outer span output  →  按 turns[i] 字段定位错误层
  ↓
TDD 修复（先写 RED 测试 → 写最小修复 → GREEN + 全量回归）
  ↓
跑对应 case ids 验证 → 扩到全量回归 → 满意打 production 标签
```

### 修复模式（高频）

| 问题类型 | 修复方式 | 关联文件 |
|---|---|---|
| 路由错误 | 改一级路由（rules-first，ADR 0015）或子图 intent 提示词 | `app/nodes/intent_route.py` / `app/subgraphs/*/intent.py` |
| 提示词不准 | LangFuse 推新版本（A/B 共存，ADR 0003），跑 eval 对比 | `app/prompts/**/*.md` |
| 渲染漏字段 | 改 `app/nodes/render.py` 的 product-aware 模板 | `app/nodes/render.py` |
| Ticker 识别错 | 跑 `probe_ticker_e2e.py` 复现 → 改 ticker 子图工具 | `app/subgraphs/ticker/` |
| 代码逻辑缺失 | 改对应节点（如加权限校验、补缺省字段） | 子图各 `*.py` |

---

## 三、关键命令

```bash
# 评估
python scripts/langfuse_eval.py --local tests/fixtures/golden.jsonl --concurrency 4
python scripts/langfuse_eval.py --local tests/fixtures/golden.jsonl --ids opt-001
python scripts/langfuse_eval.py --local tests/fixtures/golden.jsonl --dry-run --limit 5

# 数据集
python scripts/upload_golden_to_langfuse.py        # 全量 golden → Langfuse Dataset
python scripts/upload_option_dataset.py            # 期权 QA 原版（保留 priority / designer 字段）

# Harness CLI（无 Judge 快速 smoke）
python -m harness run
python -m harness diff <run-a> <run-b>

# 真后端 e2e
python scripts/probe_real_backend_e2e.py
python scripts/probe_{swap,option,close,ticker}_write_e2e.py

# 监控 / 告警
curl http://localhost:8000/metrics                 # Prometheus 端点
python scripts/run_alerts.py                       # 告警阈值干跑
python scripts/llm_cost_report.py                  # LLM 成本日报
```

## 四、不做（范围约束）

- 不做 shadow 双跑作为 M3 退出门（ADR 0016：Dify 自身有"标的不准 / 参数 bug / 评估缺失"三大缺陷，不能作 ground truth；shadow 仅作 M4 切流前的第二意见）
- Judge 不用 Qwen（自评不可信，会高估）
- 标的池不切回 HTTP API（ADR 0012：securities-instrument MySQL 直查更稳）
- 不为提高 PASS 率硬编码业务数据字典（CLAUDE.md "绝对禁止 · P0"）
