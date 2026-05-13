# tests/fixtures/ — 测试基线数据集

> **本目录是测试基线的真相来源**。任何对 fixture 的改动必须遵循下方"职责矩阵"，跨文件改动需运行 `python scripts/check_fixture_consistency.py` 校验一致性。

## 1. 职责矩阵（5 份 fixture 各自定位）

| 文件 | 行数 | 用途 | 主消费者 | 写入约束 |
|---|---|---|---|---|
| `golden.jsonl` | 358 | **ADR 0015 规则层锚点**（g001-g030）+ 业务方第 1/2 批种子（g100+ / g200+） | `tests/test_intent_route.py` 锚点测试 / `tests/test_harness.py` loader smoke | 锚点 g001-g030 不许动；新种子只能加 g100+ 不能复用旧 id |
| `unified_golden.jsonl` | 489 | **harness 主基线**（schema 重组，含 `conversation` / `output` 字段） | `python -m harness run`（默认数据源） | 必须是 `golden.jsonl` 的 raw_content **超集**；CI lint 强约束（见 §3） |
| `option_golden.jsonl` | 131 | **业务方 QA 原版**（含 `priority` / `designer` / `precondition` 等 QA 字段） | `scripts/upload_option_dataset.py`（LangFuse Dataset 上传） / `scripts/merge_golden.py` 输入 | 只新增不修改（外部产物 from `场外衍生品AI交易指令模块-功能测试用例.xlsx`）|
| `golden_business_seeds_2026-05.jsonl` | 287 | **历史快照**（M2 业务方种子第 1 次大批量提交，归档用） | `docs/m2-business-seeds-review-*.md` 引用作 review baseline | **冻结**，不再修改；新种子加进 `golden.jsonl` |
| `golden_ticker_2026-05.jsonl` | 34 | **ticker 子图单测专用**（tokens / winner / needs_hitl 等 ticker 独有字段） | `tests/subgraphs/ticker/test_golden_ticker_fixture.py` | 标的相关 case 加这里，不要混进 golden.jsonl |

## 2. 数据流图

```
              ┌────────────────┐
              │  人工录入 / 收集 │
              └───┬────────┬───┘
                  │        │
            ┌─────▼──┐  ┌──▼──────────────┐
            │ Excel  │  │ 直接 jsonl 编辑 │
            │ 测试用例│  │  （业务方批改）  │
            └───┬────┘  └────┬────────────┘
                │            │
   scripts/convert_testcase_to_jsonl.py
                │            │
                ▼            ▼
       option_golden.jsonl  golden.jsonl ←── ticker 测试 ── golden_ticker_2026-05.jsonl
                │            │
                └─┬──────────┘
                  │ scripts/merge_golden.py
                  ▼
       unified_golden.jsonl ──→ python -m harness run
                  │
                  └──→ scripts/upload_to_langfuse_dataset.py（M2/M3 可选）
```

## 3. 不变量（由 CI lint 校验）

`scripts/check_fixture_consistency.py` 强制以下规则：

| # | 规则 | 违反后果 |
|---|---|---|
| 1 | `unified_golden.jsonl` 的 raw_content 集合必须 ⊇ `golden.jsonl` 的 raw_content 集合 | CI fail：`merge_golden.py` 没跑 |
| 2 | `golden.jsonl` 中 `g001-g030` 必须存在（30 条 ADR 0015 锚点） | CI fail：锚点被误删 |
| 3 | 5 个 fixture id 命名必须遵循 §1 表（g000/swap-000/opt-000/tk000） | CI fail：命名混乱 |

跑：
```bash
python scripts/check_fixture_consistency.py
```

退出码 0 = 一致 / 1 = 有违反 / 2 = 文件缺失。

## 4. 加新 case 的工作流

### 场景 A · 业务方提一批新种子（最常见）

1. 业务方在 Excel 标注 → `scripts/convert_testcase_to_jsonl.py` → 临时 jsonl
2. 编辑者把新 case 追加到 `golden.jsonl`（用下一可用的 g 编号）
3. 跑 `python scripts/merge_golden.py` 重生 `unified_golden.jsonl`
4. 跑 `python scripts/check_fixture_consistency.py` 校验
5. 跑 `pytest tests/test_harness.py tests/test_intent_route.py` 防回归
6. PR 含上述 3 个文件改动 + 业务方 review 截图

### 场景 B · 修订 ADR 0015 规则层锚点（罕见）

需先改 ADR 0015，再改 `golden.jsonl` g001-g030 范围，再跑 fixture consistency check。

### 场景 C · 加 ticker case

直接编辑 `golden_ticker_2026-05.jsonl`，不动其他 4 份。

## 5. 历史包袱说明

- `golden.jsonl` 和 `unified_golden.jsonl` 用了**不同 id schema**（g001-g358 vs swap-001 / opt-001）—— 历史决策，跨文件交叉引用不可能。**保持现状**：两份各自服务不同入口（pytest / harness CLI）。
- `docs/m2-real-llm-final-report.md` 写"Golden 总数 317 条（30 锚点 + 287 种子）" —— 实际 golden.jsonl 358 条，差额是后续追加的种子，文档没更新。新写 review 时引用本 README 而不是历史 report。

## 关联

- [ADR 0015 · 一级路由规则前置 + LLM 兜底](../../docs/adr/0015-intent-route-rules-first-llm-fallback.md)（g001-g030 锚点的依据）
- [ADR 0014 D9.2 · M2 退出门](../../docs/adr/0014-langfuse-as-harness-backend.md)（PASS 率口径）
- [docs/m2-real-llm-final-report.md](../../docs/m2-real-llm-final-report.md)（M2 92.5% PASS 历史）
- [grill-with-docs 2026-05-10 · B/C 桶阈值决策](../../CLAUDE.md)（business_seed ≥ 90% / llm_paraphrase ≥ 80%）
