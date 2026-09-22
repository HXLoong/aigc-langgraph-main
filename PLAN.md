# 评估与迭代方案（M3 阶段）

> Judge：DeepSeek V4（Anthropic 兼容端点，thinking=4096 tokens）
> 范围：全链路（swap / option / option_close / ticker），fixture 现役数据源 `tests/fixtures/categories/`（350+ 条）
> 状态：基础设施完成 ✅；M3.1 mock 跑通 ✅；M3.2 真后端联调 ✅；当前推进 **M3.3 真后端 golden 回归 + 错例修 P0/P1 + 业务方现场 sign-off**（issues #82–#87）

## M3 阶段三段定义（来自 ADR 0016）

| 阶段 | 状态 | 退出门 | 关联 |
|---|---|---|---|
| **M3.1 · Mock 跑通** | ✅ 完成 | harness anchor 全集 PASS ≥ 85%（达成 84.6%）| `docs/archive/m2/m2-real-llm-final-report.md` |
| **M3.2 · 真后端联调** | ✅ 完成 | D2.1–D2.6 + Dx.1/Dx.2 全 closed；HTTP 5xx = 0 / 4xx = 0 | issues #72–#80 |
| **M3.3 · 真后端 Golden 回归** | 🔄 进行中 | PASS ≥ M3.1 mock baseline + 错例 P0/P1 全修 + 现场 sign-off | issues #82–#87 |

## M3.3 具体子任务（open）

| Issue | 任务 | 退出门 |
|---|---|---|
| #82 E3.1 | 真后端跑 B 桶全集 → PASS rate 报告 | 总 PASS ≥ 92.5%（mock baseline 同口径）|
| #83 E3.2 | business_seed 全集按桶分别评估 | B 桶 ≥ 90% / C 桶 ≥ 80% |
| #84 E3.3 | 真后端跑 D 桶（客户真实输入）| 依赖 PM 收集 30+ 条 |
| #85 E3.4 | 错例聚类 + 根因分析，**只修 P0/P1**（cascade fail / 5xx / 严重参数错 / 标的错），P2 延后到 F4.6 | 修完回归 PASS rate |
| #86 E3.5 | 现场 smoke checklist + 客户 Java 后端真实联调 | ≥ 5 条真实业务流走通 |
| #87 E3.6 | 业务方培训 + 现场 sign-off | 业务方盲测 ≥ 5 条 case PASS sign-off |
| #59 C1.14 | 离线依赖包（pip wheel + docker save）| 离线环境完整跑通客户部署 |
| #113 | fixture 数据集质量修复（执行价格缺失 / 反案例标错 / 重复指令）| 业务方 review pass |

---

## 一、已完成

### 基础设施

| 组件 | 文件 | 状态 |
|---|---|---|
| 评估脚本（DeepSeek Judge + per-turn 富集 JSON）| `scripts/langfuse/langfuse_eval.py` | ✅ 单轮 / 多轮 / Langfuse Cloud 写回 |
| Dataset 上传 | `scripts/langfuse/upload_golden_to_langfuse.py`（categories → Langfuse） | ✅ |
| 数据转换 | `scripts/convert_csv_to_excel.py` / `convert_jsonl_to_csv.py` | ✅ |
| 本地 fixture | `tests/fixtures/categories/`（A 方言，6 文件 / 389 条）+ `unified_golden.jsonl`（B 方言，921 条，harness 默认并入，ADR 0024 D6）；`old_typing/` 归档 | ✅ |
| 真后端 e2e 探针 | `scripts/probe_*_e2e.py`（swap / option / close / ticker / real_backend） | ✅ |
| Token / 成本估算 | `harness/token_tracker.py` + `scripts/llm_cost_report.py` | ✅ |
| 报告 | Langfuse per-turn 富集 JSON + `harness/cli.py` markdown 报告 | ✅ |
| 期权链路迭代 skill | `.claude/skills/iterate-option/SKILL.md` | ✅ |
| 通用评估 skill | `.claude/skills/run-eval/` | ✅ |

### 数据流

```
本地 tests/fixtures/categories/（现役，350+ 条）
        │
        ├──→ scripts/langfuse/upload_golden_to_langfuse.py
        │            │
        │            ▼
        │     Langfuse Dataset
        │            │
        ▼            ▼
scripts/langfuse/langfuse_eval.py
  ├── InMemorySaver（不依赖 MySQL checkpoint）
  ├── 真实 DeepSeek-V4-pro（测提示词效果，ADR 0020）
  ├── 真实后端 / 本地 mock（OTC_API_BASE_URL 切换）
  ├── TickerClient 标的查询（securities-instrument HTTP，ADR 0012）
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
python scripts/langfuse/langfuse_eval.py --local tests/fixtures/categories --concurrency 4

# 按 case 子集复跑（修一处 bug 后验证）
python scripts/langfuse/langfuse_eval.py --local tests/fixtures/categories --ids case-025,case-026 --concurrency 2

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
python scripts/langfuse/langfuse_eval.py --local tests/fixtures/categories --concurrency 4
python scripts/langfuse/langfuse_eval.py --local tests/fixtures/categories --ids case-025
python scripts/langfuse/langfuse_eval.py --local tests/fixtures/categories --dry-run --limit 5

# 数据集
python scripts/langfuse/upload_golden_to_langfuse.py        # categories → Langfuse Dataset

# Harness CLI（无 Judge 快速 smoke）
python -m harness doctor
python -m harness run

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
- Judge 不用业务同源模型自评（会高估）；统一 DeepSeek Judge
- 不做标的池 MySQL 直查（ADR 0012：恢复 securities-instrument HTTP，走 `TickerClient`）
- 不为提高 PASS 率硬编码业务数据字典（CLAUDE.md "绝对禁止 · P0"）
- M3.3 错例修复**只修 P0/P1**（cascade fail / 5xx / 严重参数错 / 标的错），P2 错例（个别意图识别错 / 低频边界 case）延后到 F4.6 金丝雀期再修

## 五、二期持续优化（全量上线后启动）

来自客户内部汇报方案（2026-05-11）的三件套，**不在 T+3~4 全量上线范围内**：

- **Issue #35** · 评估→优化→更新→再评估自动闭环（错例聚类 / A/B 自动评估 / 自动 PR 生成 / 3-6 周）
- **Issue #36** · 智能体异常干预 + 沉淀记忆机制（跨会话 agentic memory / 4-8 周）
- **Issue #37** · 回流集自动化打通（生产真实流量 → D 桶 golden，含脱敏 + 业务方人工标注 / 6-10 周）
