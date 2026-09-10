# 基准数据职责与恢复来源

## 1. 职责矩阵

| 文件 | 用途 | 编号 | 记录数 |
| --- | --- | --- | ---: |
| `golden.jsonl` | 当前业务回归主集，保留现有编号、输入和预期 | `swap-` / `opt-` / `opt_close-` / `query-` | 535 |
| `unified_golden.jsonl` | 历史合并集及当前主集的累计归档 | 产品前缀 + 数字；兼容历史 `close-` / `unknown-` | 921 |
| `option_golden.jsonl` | 历史期权业务 QA 数据 | `opt-` | 131 |
| `golden_business_seeds_2026-05.jsonl` | 历史业务种子快照 | `g` + 数字 | 287 |
| `golden_ticker_2026-05.jsonl` | 标的回归数据 | `tk` + 三位数字 | 34 |
| `golden_rule_anchors.jsonl` | ADR 0015 原始规则锚点 | `g001`–`g030` | 30 |

## 2. 恢复来源

三个缺失文件恢复自 Git 提交 `68e11d5519e4d0e90546f4c4436293e9187b793b`，即删除提交 `e4c132a` 的父提交。

- `option_golden.jsonl`：131 条，恢复后与 Git blob 逐字节一致。SHA-256：`9b02c3f787c9c84a52429ded805098bc9bbe031dfef5f95c3f1ba4950715212a`。
- `golden_business_seeds_2026-05.jsonl`：287 条，恢复后与 Git blob 逐字节一致。SHA-256：`a178829cd8047b12ee285f49366cb9d5d11d7116cf04c27533eacc4df8f4c837`。
- `unified_golden.jsonl`：先恢复原始 325 条，再通过同步脚本追加数据；原始 325 条的编号和内容保持不变。
- `golden_rule_anchors.jsonl`：从同一提交的 `golden.jsonl` 原样抽取 `g001`–`g030`，保留输入、预期和编号。

当前主集已由历史的 `g` 编号、单轮平铺结构迁移为产品编号和 `conversation` 结构。恢复独立锚点文件，避免为了满足旧检查而覆盖当前主集或改写其编号。快照用于历史追溯，不代表其中所有旧意图仍适用于当前业务契约。

## 3. 一致性要求

- 所有文件必须存在、非空，编号唯一且符合各自命名约定。
- `unified_golden.jsonl` 的首轮输入集合必须覆盖当前 `golden.jsonl` 和规则锚点集。
- 规则锚点 `g001`–`g030` 必须全部存在。
- 合并脚本保留已有归档，只追加内容变化的记录；当前多轮消息及预期完整保留，不按首轮输入去重。
- 追加记录用 `source_fixture` 和 `source_case_id` 记录来源；分配归档编号以避免与历史记录冲突。重复执行同步不产生新记录。

## 4. 更新与检查

```powershell
$env:PYTHONUTF8 = '1'
.venv/Scripts/python.exe scripts/merge_golden.py
.venv/Scripts/python.exe scripts/check_fixture_consistency.py --verbose
```

新增或修改业务回归记录时，先更新当前主集，再执行同步与一致性检查。历史 QA 和业务种子快照保持可追溯，不用于覆盖当前业务预期。
