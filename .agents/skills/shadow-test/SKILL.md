---
name: shadow-test
description: 用 scripts/shadow_compare.py 对同一批样本同时请求 LangGraph 与 Dify，输出字段级差异。使用场景：业务方需要"新旧系统输出对比"作为决策参考、某条具体指令的差异排查。只是可选对照工具，不是合格性判定标准。
metadata:
  source: .claude/skills/shadow-test/SKILL.md
  argument_hint: '[--sample path] [--max-cases N]'
---

> 自动生成自 `.claude/skills/shadow-test/SKILL.md`（python scripts/sync_agents_md.py），禁止手改。

# Shadow 对照（可选工具）

> 合格性以数据集评测门为准（ADR 0030 D3）。Dify 自身有标的不准、参数错误等已知缺陷，shadow 差异**不是** ground truth，只作决策参考。

## 参数

- `--sample`：JSONL 样本，每行至少 `id` + `raw_content`（`tests/fixtures/categories/` 不是该格式，需先转换或用导出的真实流量样本）
- `--max-cases`：只跑前 N 条

## 执行流程

### Step 1：前置检查

```bash
# LangGraph 本地服务（端口按 CLAUDE.md：本地联调 8201）
curl -sf http://127.0.0.1:8201/health || echo "LangGraph 未启动"
```

Dify 端点与 API Key 由用户提供；任一不可达**立即停下**，告诉用户缺什么。写类样本必须在 LangGraph 侧开 `DRY_RUN_BACKEND=true`，避免真下单。

### Step 2：跑对照

```bash
python scripts/shadow_compare.py \
    --langgraph http://127.0.0.1:8201/v1/workflows/run \
    --dify "$DIFY_URL" --dify-api-key "$DIFY_API_KEY" \
    --sample <样本.jsonl> --max-cases ${N:-20} \
    --output .harness-runs/shadow.json --markdown-report .harness-runs/shadow.md
```

### Step 3：分析差异

- `product_type` 不一致 → 一级路由（`app/nodes/intent_route.py`；联合解析目标见 ADR 0031）
- `intent` 不一致 → 子图意图提示词
- 参数不一致 → 子图 extract 节点与 Pydantic 模型
- `tickers[i].*` 差异 → 结构性差异：LangGraph 的 `tickers` 是恒为空的兼容字段（标的识别归 Java，ADR 0025），无需排查；标的问题核对传给后端的原文

差异确认是 LangGraph 的问题时，先在 `tests/fixtures/categories/` 补 case，再按 TDD 修复。

### Step 4：报告

给出样本数、一致率、按字段的差异分布与 Top 3 差异案例（原话摘要、两侧输出、初步判断）。

## 注意

- **不自动改代码**：只做诊断
- **大样本预警**：N > 100 会产生显著 LLM 调用费用
- 脚本去留待裁决（见 CLAUDE.md issue 裁决），不要扩展其功能
