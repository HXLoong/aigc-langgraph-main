---
name: run-eval
description: 在 golden set 上评估当前 LangGraph 的端到端准确率，生成分类报告。使用场景：改完代码或提示词后快速验证；发布前的准确率基线；定期回归。
argument-hint: [--sample path]
allowed-tools: Read, Bash, Grep
---

# Golden Set 评估

## 参数
- `--sample` 可选，默认 `tests/fixtures/golden.jsonl`

## 执行流程

### Step 1：前置检查
```bash
# 确认服务在跑
curl -sf http://localhost:8000/health || { echo "服务未启动"; exit 1; }

# 确认 golden set 存在
SAMPLE=${1:-tests/fixtures/golden.jsonl}
[ -f "$SAMPLE" ] || { echo "golden set 不存在：$SAMPLE"; exit 1; }
wc -l "$SAMPLE"
```

### Step 2：运行评估
```bash
python scripts/eval_golden.py "$SAMPLE" \
    --endpoint http://localhost:8000/v1/message \
    --parallel 5
```

### Step 3：解读输出

`eval_golden.py` 会输出：
- 总准确率
- P50 / P95 延迟
- 按 category 分组的准确率
- 失败用例明细

### Step 4：生成诊断报告

基于输出给用户一份简报：

```markdown
# Golden Set 评估报告

时间：<now>
样本量：N
准确率：X/N (Y%)

## 延迟
- 平均：Xms
- P95：Xms
- 最慢用例：<id>（<description>）

## 按 category
- swap/place_order: N/N (100%)
- swap/confirm: X/N (Y%)
- option_close/request: X/N (Y%)
- ...

## 失败分析
### 失败用例 1: <id>
- raw_content: <前 80 字>
- 期望: product=A, intent=B
- 实际: product=A, intent=C
- 可能原因：<分析>

## 建议
[按准确率提建议]
- 若 ≥ 98%：可以进入 shadow compare 阶段
- 若 95-98%：看失败 category 的分布，针对性优化
- 若 < 95%：暂停发布计划，深度排查
```

### Step 5：对比历史（如有）

若存在历史评估报告（如 `reports/eval_YYYYMMDD.md`）：
```bash
# 查最近一次评估
ls -lt reports/ | head -5
```

对比当前准确率 vs 上次，标出：
- 哪些 category 的准确率上升/下降
- 是否有回归（之前通过，现在失败的用例）

### Step 6：保存报告（可选）
```bash
# 若用户需要存档
mkdir -p reports
cat > "reports/eval_$(date +%Y%m%d_%H%M).md" <<EOF
<生成的报告内容>
EOF
```

## 禁止

- **不要**自动修改代码去"凑"测试通过
- **不要**在评估期间改 golden set（要改必须单独提 PR）
- **不要**跳过服务状态检查就直接跑（会产生无效报告）

## 注意

- 每条 case 会调用一次真实的 LLM + 后端 → 评估有 API 费用
- 100 条 golden case 在 parallel=5 下约 2-5 分钟
- 若想快速跑只选几条：`head -10 tests/fixtures/golden.jsonl > /tmp/mini.jsonl` 再跑
