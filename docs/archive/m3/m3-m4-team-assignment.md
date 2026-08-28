# M3/M4 分工方案 · 数据集 SOP + 开发工单

> 编制日期：2026-05-11
> 关联：`docs/m3-m4-roadmap.md`
> 团队规模：**数据集 1-2 人 + 开发 1 人（Claude Code 协助）**

---

## 0. 总体分工

| 角色 | 人数 | 主要交付 | 工具栈 |
|---|---|---|---|
| **数据工程师 A** | 1 | B 桶（业务方种子）扩充 + 数据质量审计 + 与 PM 对齐 case 业务合理性 | 文本编辑器 + `python -m harness run` |
| **数据工程师 B** | 0-1（可选） | C 桶（LLM paraphrase 候选）review + D 桶客户真实样本收集与脱敏 | 同上 + LangFuse Cloud 看板 |
| **开发工程师** | 1 | 阶段 0-4 全部代码任务（PR #41 修绿 / 代码补全 / 真后端联调 / 部署能力 / 监控） | Claude Code + git + harness |
| **Tony**（你） | 1 | 协调 / 业务方对接 / 灰度决策 / 与客户 IT 对齐 / 现场 smoke | — |
| **PM** | 1 | case 业务合理性 sign-off / 客户真实样本协调 / 业务方培训组织 | — |

**核心思路**：开发 1 人 + Claude Code，按本文档"开发工单 W1-W6"顺序串行推进；数据集 1-2 人独立并行，不阻塞开发。

---

## 1. 数据集准备 · 详细 SOP

### 1.1 背景与目标

我们要把 golden 集从当前的 **353 条 / 92.5% pass rate** 推到上线前的"四桶齐全"状态：

| 桶 | 来源 | 当前 | 目标 | 阈值 |
|---|---|---|---|---|
| **B 桶** business_seed | 业务方手写 | 312 条 | ≥ 350 条（按意图均衡）| PASS ≥ 90% |
| **C 桶** llm_paraphrase | LLM 对抗变体 | 11 条 | ≥ 100 条 | PASS ≥ 80% |
| **集成集** | 多轮对话 / interrupt / cascade | 0 条 | ≥ 15 条 | PASS = 100% |
| **D 桶** customer_real | 客户真实历史话术 | 0 条 | ≥ 30 条 | PASS ≥ 75%（容忍真实噪音）|
| 其他 | anchor / priority | 30 条 | 保持 | PASS = 100% |

**为什么按桶分**：B 桶是业务定义的"正确性 ground truth"，必须高 PASS；C 桶是抗噪能力测试，容忍 80%；D 桶是真实流量样本，最接近上线情况但噪音最大。

### 1.2 数据工程师 A 的工作流（B 桶扩充）

#### 第 1 步：环境准备（半天）

```bash
# 1. clone 仓库
git clone git@github.com:GZTL-AI/aigc-langgraph.git
cd aigc-langgraph

# 2. 装依赖（用 venv 避免污染系统）
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 3. 跟开发工程师拿 .env（含 QWEN_API_KEY / LANGFUSE_* / MySQL 连接串）

# 4. 跑 smoke 验证环境通
pytest tests/test_smoke.py -v

# 5. 启 mock_api（数据扩充期不需要真后端）
uvicorn mock_api.server:app --reload --port 8099 &

# 6. 跑一条 case 验证 harness 通
python -m harness run --case g001
# 应看到：PASS 行
```

> 🔧 卡环境超过 1 小时，直接找开发工程师 pair。

#### 第 2 步：理解 golden schema（15 分钟）

打开 `tests/fixtures/golden.jsonl`，**每行是一条独立 JSON**，结构：

```json
{
  "id": "g001",                          // 全局唯一，按时间顺序递增
  "category": "swap/place_order",        // <产品>/<场景> 分类
  "raw_content": "用户原话",              // 必填
  "quote_content": "上一条客服话",         // 可选，引用消息场景才填
  "expected": {
    "product_type": "swap",              // 必填：swap / option / option_close / unknown
    "intent": "place_order_request"      // 必填：意图枚举（按 product_type 不同）
  },
  "source": "business_seed",             // 必填：business_seed / llm_paraphrase / customer_real
  "notes": "测什么场景"                   // 可选
}
```

**合法 intent 枚举**（按 product_type）：

| product_type | 合法 intent |
|---|---|
| `swap` | `place_order_request` / `cancel_order_request` / `confirm_order` / `confirm_modify_order` / `confirm_cancel_order` / `query_order_status` / `unknown_intent` |
| `option` | `new_inquiry` / `place_order_from_quote` / `request_modify_order` / `request_cancel_order` / `confirm_order` / `confirm_cancel_order` / `query_order_status` / `unknown_intent` |
| `option_close` | `close_order_request` / `close_order_confirm` / `close_order_cancel_request` / `close_order_cancel_confirm` / `close_order_query` / `unknown_intent` |
| `unknown` | （不填 intent） |

#### 第 3 步：每天扩充一批（推荐节奏）

**节奏建议**：每天扩 20-30 条，分 3 个时段。

**操作流程**：

```bash
# 1. 拉最新代码（避免冲突）
git pull origin main

# 2. 起一个 feature 分支
git checkout -b data/golden-batch-2026-05-12

# 3. 打开 tests/fixtures/golden.jsonl，在末尾追加新行（不要插入中间）
#    新 case id 从当前最大 + 1 开始，建议每天用 g500-g520 这种连号

# 4. 每加 5 条，跑一次 harness 验证
python -m harness run --case-prefix g50
# 期望：5/5 PASS 或 4/5 PASS（B 桶 ≥ 90%）

# 5. 如果有 FAIL：
#    a. 先确认 case 写错了还是节点 bug
#    b. case 写错 → 修 expected
#    c. 节点 bug → 不要改 expected！在 FAIL 行加 notes="suspected_node_bug" 标记，找开发工程师

# 6. 全部 5 条 PASS 后，commit
git add tests/fixtures/golden.jsonl
git commit -m "test(golden): +5 条 B 桶 case g501-g505 (swap.place_order)"

# 7. 每天结束前 push + 提 PR
git push -u origin data/golden-batch-2026-05-12
# 在 GitHub 提 PR，标题：test(golden): +XX 条 B 桶 case (g500-g520)
```

#### 第 4 步：选 case 的策略（重要）

**优先级**：找当前 PASS 率最低的意图补，而不是补已经很好的。

跑覆盖率统计：

```bash
python -c "
import json
from collections import Counter
intents = Counter()
with open('tests/fixtures/golden.jsonl') as f:
    for line in f:
        d = json.loads(line)
        key = f\"{d['expected'].get('product_type')}/{d['expected'].get('intent')}\"
        intents[key] += 1
for k, v in sorted(intents.items(), key=lambda x: x[1]):
    print(f'{v:4d}  {k}')
"
```

**当前覆盖薄弱的意图**（来自 2026-05-11 统计）：

| 意图 | 当前条数 | 建议补到 |
|---|---|---|
| `swap/query_order_status` | 5 | 10+ |
| `option/place_order_from_quote` | 28 | 35+ |
| `option/cancel_request` | 7 | 12+ |
| `option/modify_request` | 4 | 10+ |
| `option_close/place` | 21 | 30+ |
| `option_close/query` | 6 | 12+ |

**每条 case 的 5 种变体**（同一意图建议至少各 1 条）：

1. **标准表达**：完整、规范，如"互换下单 帮我买入 1000 股腾讯控股"
2. **缩写/简称**：如"撤 H-20260304-0001"
3. **口语化**：如"那个茅台帮我平了吧"
4. **多目标**：如"同时买茅台和五粮液各 100 股"
5. **边界 / 负例**：如"今天天气不错"（→ unknown）

#### 第 5 步：与 PM 对齐节奏

**每 20 条 stop 一次**找 PM 做 case 业务合理性 sign-off：

- "这话客户真会说吗？"
- "expected intent 是否符合业务理解？"
- "是否漏了某个常见场景？"

PM sign-off 通过的批次才合 PR。

#### 第 6 步：周度产出（建议 KPI）

| 周 | 累计 B 桶 | 累计 C 桶 | D 桶 |
|---|---|---|---|
| W1 | 312 → 330 | 11（保持）| 0 |
| W2 | 330 → 350 | 11 → 50 | 0 → 15 |
| W3 | 保持 350 | 50 → 100 | 15 → 30 |

### 1.3 数据工程师 B 的工作流（C 桶 review + D 桶收集）

#### C 桶（LLM paraphrase）流程

**LLM 自动生成候选 → 人工 review → 合入**。

```bash
# 1. 自动生成候选（每 B 桶种子 paraphrase 出 3 个变体）
python -m harness.case_generator paraphrase --num 3 \
    --out docs/m2-llm-generated-cases-2026-05-12.md

# 2. 打开生成的 markdown 文件，逐条 review
#    - 表达确实和种子不同？✅
#    - expected 仍然一致？✅
#    - 没出现"为变而变"的怪话？✅
#    （通过 → 标 ✓；不通过 → 标 ✗ + 写原因）

# 3. 通过的候选转 jsonl 追加到 golden.jsonl
#    可手工拷贝，或用脚本（脚本由开发工程师配合写）

# 4. 跑 harness 验证
python -m harness run --case-prefix <新批次>

# 5. PASS 率 < 80% 的话先不合入，调整 paraphrase prompt 或减少 num
```

> ⚠️ 重要：C 桶 case **必须经业务方或 PM sign-off** 才合入。

#### D 桶（客户真实历史话术）流程

**与客户 IT / 业务方协调，拿真实流量样本**：

1. **数据来源**：客户企微历史会话日志 / 业务方收集本（推荐找最近 1-2 周的）
2. **样本量**：30-50 条（一期足够，后续二期 #37 走自动回流）
3. **脱敏要求**（金融合规硬约束）：
   - 客户名（公司/个人）→ 替换为占位符 `<客户A>` / `<张某>`
   - 真实订单号 → 替换为脱敏 `H-XXXXXXXX-XXXXXXXX` 格式
   - 金额若过敏感 → 量级保留（如"1000 万"→"XX 万"）
   - 真实手机号 / 身份证 / 银行账号 → 完全删除
4. **expected 标注**：业务方协助标 product_type + intent
5. **特别关注**：客户日常但 B 桶可能没覆盖的表达（行业黑话、客户公司内部代号、独特方言等）
6. **合入**：source 标 `customer_real`，PASS 率门槛 75%（容忍真实噪音）

```bash
# 假设业务方给了 raw_samples.txt，每行一条
# 1. 转 jsonl 模板
python scripts/convert_testcase_to_jsonl.py raw_samples.txt --source customer_real \
    --start-id g800 > /tmp/customer_real_candidates.jsonl

# 2. 人工 review 每条的 expected 字段（业务方协助）

# 3. 脱敏检查（grep 敏感模式）
grep -E '(1[3-9]\d{9}|\d{15,18}|H-2026[0-9]{4}-[A-Z0-9]{6,})' /tmp/customer_real_candidates.jsonl
# 如有命中 → 必须脱敏

# 4. 合入 golden.jsonl，跑 harness
cat /tmp/customer_real_candidates.jsonl >> tests/fixtures/golden.jsonl
python -m harness run --case-prefix g8
```

### 1.4 数据质量审计（每周一次）

**数据工程师 A 在每周五跑一次审计**：

```bash
# 1. 自动检测脚本（开发工程师协助写到 scripts/golden_audit.py）
python scripts/golden_audit.py tests/fixtures/golden.jsonl

# 期望输出：
# ✓ 353 条 case，0 条 schema 错
# ✓ 0 条重复 raw_content
# ✓ 0 条 intent 不在合法枚举
# ✓ B/C/D 桶分布：B 350 / C 11 / D 0

# 2. 跑全集
python -m harness run --output .harness-runs/audit-$(date +%F)/

# 3. 按桶看 PASS 率（harness reporter 已支持按 source 分桶）
# 4. PASS 率掉了 → 找开发工程师 root cause
```

### 1.5 数据集任务清单 · 时间表

| 周 | 数据工程师 A | 数据工程师 B（可选） |
|---|---|---|
| W1 | 环境 + B 桶 +15 条（低覆盖意图）| 启动 C 桶 paraphrase 工具，生成 20 条候选 |
| W2 | B 桶 +20 条 + ticker fixture 扩到 30 条（#20 退出门） | C 桶 review +30 条入 golden + D 桶启动协调 |
| W3 | 集成集 15 条（多轮对话/interrupt）+ 周度审计 | D 桶收集 30 条 + 脱敏 + review |
| W4 | 配合开发工程师做真后端回归 + 错例修复 | D 桶按真后端跑测，错例归类 |

---

## 2. 开发工程师工单（Claude Code 协助）

**串行推进**，6 个工单按编号顺序做。每个工单建议独立 PR。

### W1 · 阶段 0：PR #41 CI 修绿 + merge（0.5-1 天）

```
任务：
1. 拉 GitHub Actions log：访问 https://github.com/GZTL-AI/aigc-langgraph/actions/runs/25682413598
2. 看 fail 的是哪条 pytest / ruff / mypy
3. 本地复现：
   git fetch origin feature/m2-ticker-subgraph
   git checkout feature/m2-ticker-subgraph
   pytest tests/ -v
4. 修 → 推到 feature/m2-ticker-subgraph → CI 绿
5. PR #41 review + merge → main
退出门：main 拿到 92.5% pass rate 的 ticker 子图代码
```

### W2 · 阶段 1B：剩余代码节点（4-5 天）

```
任务（按优先级）：
1. swap.intent v2 prompt 调优（修 g008 短指令路由，known limitation）
   - 用 v1/v2 共存机制（ADR 0003）
   - 灰度 5% → 看 pass 率 → 50% → 100%
2. #29 swap.hand_to_share 节点 + 5 条 golden
3. （视时间）其他 swap P2 节点
退出门：swap 链路 PASS ≥ 85%
```

### W3 · 阶段 1C：可观测性 + 监控（3-4 天）

```
任务：
1. 业务指标埋点（响应延迟 / PASS 率 / fallback 触发 / HITL 触发）
   - 写到 app/observability/metrics.py
2. 告警规则（用 Prometheus 或 LangFuse alerts）
3. LLM 成本监控（tokens 按节点拆分）
4. trace 完整性：node_trace 表 DDL + 写入逻辑
退出门：客户测试环境跑通 1 个 case，能在监控面板看到完整指标
```

### W4 · 阶段 1D：客户现场部署能力（3-5 天）

```
任务：
1. .env.customer.template + 私有化部署文档
2. 一键部署脚本 scripts/deploy-customer.sh
3. LangFuse self-hosted 部署包验证（已有 infra/langfuse/，补完客户文档）
4. 离线依赖包（pip wheel + docker image 离线包）
5. 健康检查 /health + /ready 端点
退出门：在客户测试环境一键起来 + smoke 自检通过
```

### W5 · 阶段 2：真后端联调（5 天）

```
任务：
1. 三个 client 切真后端 endpoint（读接口先 → 写接口 sandbox 后）
2. 真后端字段对齐验证（用 anchor case）
3. 不可达降级开关
4. ticker 真 GOATS 联调
5. InferCode 动态 prompt 真后端拉取
退出门：anchor 全集真后端跑通无 5xx
```

### W6 · 阶段 3：golden 回归 + 现场 smoke（5 天）

```
任务：
1. 真后端跑 anchor / business_seed / customer_real 全集
2. 错例聚类（按 suspected_node）+ root cause + 修补
3. 现场 smoke checklist 落地
4. 与客户 Java 后端真实流程联调（下单/撤单/查询/平仓）
5. 业务方培训 + sign-off
退出门：业务方书面 sign-off，可进入阶段 4
```

---

## 3. 协同节奏

### 3.1 周一同步会（30 分钟）

- 数据工程师汇报：上周新增 case 数 / 按桶 PASS 率 / 卡点
- 开发工程师汇报：上周完成工单 / 本周计划 / 阻塞
- Tony：客户侧进展 / 与 PM 同步业务方反馈

### 3.2 每日异步同步（GitHub Issue 评论）

- 数据工程师在 #31 / #20 评论里贴当日新增 case 数 + PASS 率
- 开发工程师在对应工单 issue 里贴 commit 链接

### 3.3 阻塞升级

| 卡点 | 升级路径 |
|---|---|
| harness 跑不起来 | 找开发工程师 pair |
| case FAIL 不确定是 case 错还是节点 bug | 在 GitHub Issue 标 `needs-info` + @ 开发工程师 |
| 业务理解不清 | 找 PM / Tony |
| 客户网络 / 后端可达性 | Tony 协调客户 IT |

---

## 4. 关键文件索引

| 文件 | 谁维护 | 用途 |
|---|---|---|
| `tests/fixtures/golden.jsonl` | 数据工程师 | golden case 主集 |
| `tests/fixtures/golden_ticker_2026-05.jsonl` | 数据工程师 | ticker 专项 fixture |
| `docs/archive/m2/m2-golden-seeds/` | 数据工程师 + PM | 业务方种子收集模板 |
| `docs/archive/m2/m2-llm-generated-cases.md` | 数据工程师 B | C 桶 review 工作台 |
| `docs/customer-smoke-checklist.md` | 开发工程师 + Tony | 客户现场 smoke 清单 |
| `harness/case_generator/` | 开发工程师 | C 桶 paraphrase 工具 |
| `app/prompts/**/*.md` | 开发工程师 | 提示词资产 |
| `app/subgraphs/<product>/` | 开发工程师 | 业务节点 |

---

## 5. 给数据工程师的"5 分钟上手"卡片

```
1. clone + pip install -e ".[dev]"
2. 拿 .env（找开发工程师）
3. pytest tests/test_smoke.py -v  → 全绿表示环境通
4. uvicorn mock_api.server:app --reload --port 8099 &
5. 看 tests/fixtures/golden.jsonl 末尾 3 条理解格式
6. 选一个低覆盖意图（见本文 1.2 第 4 步表格）
7. 在 golden.jsonl 末尾追加 5 条
8. python -m harness run --case-prefix <新 id 前缀>
9. PASS → commit + PR；FAIL → 找开发工程师讨论
10. 每 20 条找 PM sign-off 业务合理性
```

---

## 6. 下一步行动

讨论本分工方案后请：

1. **指定数据工程师 A 是谁** + 给 .env / 仓库 access
2. **决定是否上数据工程师 B**（可选，但建议有；不上则 C 桶 + D 桶产出节奏延后 1-2 周）
3. **开发工程师立即启动 W1**（PR #41 修绿）
4. **第 1 个周一同步会时间**

数据工程师在 W1 当周即可与开发工程师并行启动，不互相阻塞。
