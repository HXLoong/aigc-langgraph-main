# 真 LLM 跑 Harness 操作指南

> 在 317 条 golden 上跑真 LLM，验证 baseline + v1/v2 灰度对比。
> 适用场景：M2 退出门验证 / shadow 准备 / prompt v2 实证 A/B。

## 环境准备

### 1. 确认 `.env` 关键变量

```bash
# 必须
QWEN_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_API_KEY=<阿里云 DashScope key>
QWEN_MODEL_STANDARD=qwen-plus      # 或 qwen3.5-32b
QWEN_MODEL_THINKING=qwen-max

# 业务接口（mock 即可，harness 不真调订单）
OTC_API_BASE_URL=http://localhost:8099
SECURITIES_INSTRUMENT_URL=http://localhost:8099/admin-api/integration/securities-instrument/select
SECURITIES_INSTRUMENT_KEY=mock-securities-key
GOATS_BASE_URL=http://localhost:8099

# 可选：LangFuse trace（强烈建议开，便于事后按 prompt_name 分组分析）
ENABLE_LANGFUSE=true
LANGFUSE_PUBLIC_KEY=<...>
LANGFUSE_SECRET_KEY=<...>
LANGFUSE_HOST=http://localhost:3000   # self-hosted
```

### 2. 启动业务依赖（mock + LangFuse）

```bash
# Mock API（GOATS / securities / 后端订单）— 在另一个终端开起来
uvicorn mock_api.server:app --port 8099
# 或后台运行：
# nohup uvicorn mock_api.server:app --port 8099 > /tmp/mock_api.log 2>&1 &

# 健康检查（应返回 JSON 不报错）
curl -s http://localhost:8099/admin-api/integration/securities-instrument/select?keyword=test | head -c 200

# LangFuse self-hosted（可选，开了能在 UI 按 prompt_name 过滤 trace）
docker compose -f infra/langfuse/docker-compose.yml --env-file infra/langfuse/.env up -d
```

> docker-compose.yml 里只有 `mysql` 和 `app` 两个 service，没有 mock-api — mock_api 是 Python 直跑的 FastAPI 子进程。

### 3. 验证 LLM 连通性

```bash
python -c "
import asyncio
from app.llm.clients import get_qwen_structured
from pydantic import BaseModel

class Out(BaseModel):
    type: str

async def main():
    llm = get_qwen_structured().with_structured_output(Out)
    r = await llm.ainvoke([('user', '你只输出 JSON: {\"type\": \"ping\"}')])
    print('OK:', r)

asyncio.run(main())
"
```

预期输出：`OK: type='ping'`。报错说明 API key / base 不通。

## 跑测流程（推荐三阶段）

### 阶段 A · 锚点烟测（30 条 / ~3 分钟 / ~¥0.5）

仅跑原 30 条手写锚点，确认环境就绪 + 链路无 crash：

```bash
python -m harness run --category swap --out .harness-runs/anchor-swap
python -m harness run --category option --out .harness-runs/anchor-option
python -m harness run --category option_close --out .harness-runs/anchor-close
```

**通过门**：每子集 PASS ≥ 85%（业务 baseline）。低于则查 `.harness-runs/<name>/failures/<case>.json` 看 suspected_node。

### 阶段 B · 业务种子全集（287 条 / ~25 分钟 / ~¥4-5）

```bash
python -m harness run --out .harness-runs/business-seeds-2026-05
```

**通过门**：
- business_seed 桶 PASS ≥ 90%（grill-with-docs 第 4 决策硬阈值）
- swap 链路 PASS ≥ 85% / option ≥ 85% / option_close ≥ 85%

打开 `.harness-runs/business-seeds-2026-05/summary.md` 看：
- 总 PASS 率
- 按 category 分布的失败数
- 按 case source 分桶（`business_seed` 必须 ≥ 90%）
- 按 prompt 版本分桶（v1/v2 对比表，前提是有 case 命中 v2）

### 阶段 C · v1/v2 灰度对比（5% 自然分流 / 同上时长）

阶段 B 已自动覆盖 — 5% × 317 ≈ 16 条命中 v2，但样本偏小。
若需更可靠对比，强制 50/50 跑两次：

```bash
# 全量 v1（控制组）
OTC_PROMPT_SWAP_INTENT_VERSION=v1 \
    python -m harness run --out .harness-runs/v1-control

# 全量 v2（实验组，仅 swap.intent 切 v2，验证 g008 修复）
OTC_PROMPT_SWAP_INTENT_VERSION=v2 \
    python -m harness run --out .harness-runs/v2-canary

# 对比两次 PASS 率（只看 swap 链路）
diff <(jq '.pass_rate, .by_category' .harness-runs/v1-control/summary.json) \
     <(jq '.pass_rate, .by_category' .harness-runs/v2-canary/summary.json)
```

**v2 通过门**（实证 A/B）：
- swap 整体 PASS ≥ v1 PASS（不下降）
- g008 同类 case（含「确认改单 H-」/「确认修改」）PASS 100%
- swap 平均延迟 ≤ v1 + 10%

满足后逐阶段扩流量：5% → 25% → 50% → 100%（修改 `app/prompts/_versions.yaml` weight）。

## 报告解读

每次 `harness run` 输出到 `--out` 目录：

```
<out_dir>/
├── summary.json              # 机器可读
├── summary.md                # 人读（按 category / source / prompt 版本分桶）
└── failures/
    ├── g142.json             # 单 case 失败详情
    │   {
    │     "case_id": "g142",
    │     "expected": {...},
    │     "actual": {...},
    │     "diff": [{"path": "intent", "expected": "...", "actual": "..."}],
    │     "suspected_node": "swap_intent",
    │     "suspected_prompt": "app/prompts/swap/intent.md",
    │     "trace": [...]
    │   }
    └── ...
```

### 常见失败模式

| diff path | 常见嫌疑节点 | 处置 |
|---|---|---|
| `intent` | swap_intent / option_intent / close_intent | 看 prompt 是否漏覆盖该口语化表达 |
| `product_type` | intent_route | ADR 0015 三层路由有漏；加关键词或 LLM tweaks |
| `tickers` | swap_place_order / option_extract_inquiry | ticker resolver 白名单或 LLM 解析问题 |
| `place_params.*` | swap_place_order / option_extract_place_or_modify | LLM 提取参数错；看 prompt 示例 |
| `close_params.*` | close_place_close / close_holding_query | 同上 |

`failures/<case>.json` 中 `suspected_prompt` 字段已自动给出对应 .md 路径。

## 成本估算（参考阿里云 DashScope qwen-plus）

- 单 case ≈ 4-6 个 LLM 调用（intent_route + 子图 intent + 1-2 个 extract + ticker resolver）
- 单 case 平均 token ≈ 2k input + 200 output ≈ ¥0.015
- 317 条 ≈ ¥4.5 / 跑

阶段 A + B + C × 2 总计约 ¥15-20。

## 异常处理

### 全部 case crash

```
FAIL: ConnectionError ...
```

→ 检查 `OTC_API_BASE_URL` mock-api 是否启动，`QWEN_API_KEY` 是否有效。

### 部分 case PASS 部分 crash

→ LLM rate limit。在 .env 加：
```bash
QWEN_REQUEST_INTERVAL_MS=200  # 串行间隔
```

或减小并发（harness runner 默认串行，不应发生）。

### v2 PASS 率低于 v1（>2%）

→ v2 prompt 引入了反作用，不要扩流量。
→ 看 `.harness-runs/v2-canary/failures/` 排查；必要时回滚 `_versions.yaml` 删 swap.intent override。

### 单条 case PASS 但下次跑 FAIL（LLM 抖动）

→ 重跑单条：
```bash
python -m harness run --category swap/confirm --out .harness-runs/retry
```

→ 抖动率 > 5% 视为 prompt 健壮性问题，记 `docs/archive/m2/m2-prompt-improvements-backlog.md`。

## 结果上报

跑完后告诉我：
1. **summary.json 的 PASS 率 + by_category** — 我据此判断退出门
2. **`failures/` 目录前 3 条 suspected_node 集中在哪** — 帮诊断
3. **summary.md 中"按 prompt 版本分桶"章节是否出现** — 验证 reporter A/B 对比能力实际生效

如要我远程协助分析，把 `summary.md` + `failures/*.json` 贴出来即可。

## 参考

- ADR 0014 — Harness 评测台架构
- ADR 0015 — 一级路由三层
- ADR 0003 — Prompt 灰度切流
- `docs/archive/m2/m2-prompt-ab-testing.md` — 灰度操作手册
- `docs/archive/m2/m2-g008-canary.md` — g008 修复说明
