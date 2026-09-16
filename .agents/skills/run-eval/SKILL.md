---
name: run-eval
description: 用 harness 在 golden set 上跑端到端评估，输出 JSON + markdown 报告。使用场景：改完代码或提示词后快速验证；发布前的准确率基线；定期回归。
metadata:
  source: .claude/skills/run-eval/SKILL.md
  argument_hint: '[--category prefix] [--case id] [--out dir]'
---

> 自动生成自 `.claude/skills/run-eval/SKILL.md`（python scripts/sync_agents_md.py），禁止手改。

# Harness Golden Set 评估

## 参数

- `--category` 可选：只跑某个前缀的 case（如 `swap.place_order`）
- `--case` 可选：只跑单条 case（如 `g042`）
- `--out` 可选：输出目录（默认 `runs/<timestamp>`）

## 执行流程

### Step 1：前置检查

```bash
# 1. harness 可用
python -m harness --help

# 2. golden 文件存在
ls -la tests/fixtures/*.jsonl

# 3. LangFuse 在跑（trace 会写入）
docker compose -f infra/langfuse/docker-compose.yml --env-file infra/langfuse/.env ps | grep -E "(web|worker)"

# 4. MySQL 在跑（checkpointer）
docker compose ps mysql
```

任一不通就停下提示用户。

### Step 2：跑 harness

```bash
# 全集
python -m harness run

# 子集
python -m harness run --category swap

# 单条
python -m harness run --case g042

# 自定义输出目录
python -m harness run --out runs/eval-$(date +%Y%m%d_%H%M)
```

输出：
- `runs/<ts>/summary.json` — 汇总统计
- `runs/<ts>/summary.md` — markdown 报告
- `runs/<ts>/failures/<case_id>.json` — 每条失败 case 的详细 diff

### Step 3：解读 summary.json

字段（以 `harness/cli.py` 的实际输出为准）：
- 总 case 数 / pass / fail
- 按 category 分组的通过率
- LangFuse trace url（每条 case 一个）

### Step 4：生成诊断报告

```markdown
# Golden Set 评估报告

时间：<now>
样本量：N（category=<prefix or all>）
通过率：X/N (Y%)

## 按 category
- swap.place_order: P/Q (Y%)
- swap.confirm:     P/Q (Y%)
- option.intent:    P/Q (Y%)
- option_close.*:   P/Q (Y%)
- ticker.*:         P/Q (Y%)

## 失败分析（前 N 条）

### <case_id>（category）
- raw_content: <前 80 字>
- 期望：<expected JSON>
- 实际：<final_state JSON>
- 差异字段：<diff 路径>
- LangFuse trace: <url>
- 怀疑原因：<分析>

## 建议
- ≥ 98%：进入 shadow compare 阶段（用 shadow-test skill）
- 95-98%：针对性优化失败 category 占比最高的子图
- < 95%：暂停发布计划，深度排查
```

### Step 5：对比历史（可选）

```bash
# 列最近几次 run
ls -lt runs/ | head -5

# 简单对比两次的 summary.json（jq）
diff <(jq -S . runs/<ts1>/summary.json) <(jq -S . runs/<ts2>/summary.json)
```

标出：
- 哪些 category 通过率涨/跌
- 是否有回归（之前 PASS、现在 FAIL 的 case）

### Step 6：归档（可选）

```bash
# 长期保存的报告进 reports/
mkdir -p reports
cp runs/<ts>/summary.md reports/eval_$(date +%Y%m%d_%H%M).md
```

## 禁止

- **不要**自动修改代码去"凑"测试通过
- **不要**在评估期间改 `tests/fixtures/*.jsonl`（要改单独提 PR）
- **不要**跳过服务健康检查就直接跑（会产生无效报告 + 浪费 LLM 费用）

## 注意

- 每条 case 调用一次真实 LLM + 后端 → 评估有 API 费用
- 100 条 case 约 2-5 分钟（取决于并发）
- 想快速跑只选几条：`--case g001` 或 `--category swap.confirm`
- 所有 trace 自动写 LangFuse self-hosted，可在 Web UI 复盘节点级决策

## 相关

- `harness/cli.py` — 命令实现 + 报告渲染（JSON / markdown）
- `harness/multi_turn.py` — 多轮 case 的 HTTP 执行
- `harness/differ.py` — 字段级 diff
- ADR 0002 — harness 总体设计
- ADR 0014 — LangFuse 作为 harness 后端
