---
name: shadow-test
description: 用 harness 跑 LangGraph vs Dify 双跑对比，定位差异。使用场景：M3 灰度切换前的差异验证、M3 期间的差异监控、某条具体指令的对齐问题排查。
argument-hint: [--category prefix] [--n count]
allowed-tools: Read, Bash, Grep
---

# Shadow 双跑对比（基于 harness）

> **状态**：harness `diff` 子命令在 M3 启用（`harness/cli.py` 注释标记 M3）。M1/M2 阶段本 skill 仅用于规划与命令演练；真正能跑要等 M3 实装 differ。

## 参数

- `--category` 可选，golden 子集前缀（如 `swap.place_order`）
- `--n` 可选，采样上限

## 执行流程

### Step 1：前置检查

```bash
# 1. 确认 harness 入口可用
python -m harness --help

# 2. 确认 LangFuse self-hosted 在跑（ADR 0014）
docker compose -f infra/langfuse/docker-compose.yml --env-file infra/langfuse/.env ps

# 3. 确认 LangGraph 服务可达
curl -sf http://localhost:8000/v1/workflows/run -X POST -H 'Content-Type: application/json' \
    -d '{"inputs":{},"response_mode":"blocking","user":"healthcheck"}' || echo "LangGraph 未启动"

# 4. 确认 Dify 影子端点可达
curl -sf "$DIFY_BASE_URL/v1/workflows/run" -H "Authorization: Bearer $DIFY_API_KEY" || echo "Dify 不可达"
```

任一不通**立即停下**，告诉用户该启哪个服务或检查哪个配置。

### Step 2：跑两次 harness run（A=LangGraph，B=Dify）

```bash
# A 跑：LangGraph
LANGGRAPH_BASE_URL=http://localhost:8000 \
    python -m harness run --category ${CATEGORY:-} --out runs/run-langgraph-$(date +%s)

# B 跑：Dify（通过 BASE_URL + API_KEY 切到 Dify 后端）
USE_DIFY_SHADOW=true DIFY_BASE_URL=$DIFY_BASE_URL DIFY_API_KEY=$DIFY_API_KEY \
    python -m harness run --category ${CATEGORY:-} --out runs/run-dify-$(date +%s)
```

> 具体环境变量名以 `harness/runner.py` 实装为准。M1 阶段 runner 只调用 LangGraph，M3 启用 shadow 模式后会暴露 Dify 切换开关。

### Step 3：跑 diff

```bash
python -m harness diff runs/run-langgraph-<ts> runs/run-dify-<ts>
```

输出按 `harness/differ.py` 的字段级 diff 规则（按业务对象路径），输出 JSON + markdown 报告。

### Step 4：分析差异

按 `differ.py` 的归类：
- `product_type` 不一致 → 路由规则差异，看 `app/graph/main.py` + ADR 0015
- `intent` 不一致 → 子图意图识别提示词差异
- API 调用 body 不一致 → 参数提取节点的 Pydantic 模型差异
- API 返回 code 不一致 → 后端 Protocol Client（option/swap/ticker）调用差异

### Step 5：报告

```markdown
# Shadow 双跑结果

样本：N（category=...）
一致率：X/N (Y%)
LangFuse trace: <run-langgraph url> vs <run-dify url>

## 差异分类
- 路由差异：K 条（case_id 列表）
- 意图差异：K 条
- 参数差异：K 条
- API code 差异：K 条

## Top 3 差异案例
1. <case_id>：<raw_content 摘要>
   - LangGraph: product=..., intent=..., body=...
   - Dify:      product=..., intent=..., body=...
   - 怀疑原因：<初步分析>
   - 建议：跑 dify-reviewer agent 做对齐审查

## 建议动作
- [ ] 一致率 ≥ 99%：可进 5% 金丝雀
- [ ] 95% ≤ X < 99%：用 dify-reviewer 做深度对齐
- [ ] X < 95%：暂停灰度，回 feature branch 修复
```

## 注意

- **不自动改代码**：shadow-test 是诊断工具
- **大样本预警**：N > 100 会产生显著 LLM 调用费用
- **trace 写到 LangFuse**：每次 run 的 trace 都在 LangFuse self-hosted（ADR 0014），可在 Web UI 比对
- **M3 之前**：differ 命令尚未实装，先用 `harness run` 输出的 `runs/<ts>/summary.json` 手工对比
