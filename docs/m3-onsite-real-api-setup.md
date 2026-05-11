# 客户现场切真接口 · 配置指南

> 场景：开发机已通过客户内网 / VPN，能访问真实 api 后端 + goats 服务
> 目标：把 LangGraph 从 mock_api 8099 切到真 api / goats endpoint，跑通业务流

---

## Step 1 · 需要业务方现场确认的 5 项信息

请先把这 5 项填实再改 .env（缺任一都跑不通）：

| 项 | 用途 | 填写位置 | 当前值 |
|---|---|---|---|
| ① **真实 api 后端 URL** | LangGraph 调 9 个 admin-api/* 端点 | `OTC_API_BASE_URL` | `http://localhost:8099` (mock) |
| ② **api 后端鉴权 secret** | 内部接口 token | `OTC_API_SECRET` | 已有占位（确认是否客户现场最新） |
| ③ **真 goats URL** | ticker / counterparty 数据源 | `GOATS_BASE_URL` | `http://localhost:8099` (mock) |
| ④ **goats client_id** | 鉴权 | `GOATS_CLIENT_ID` | **`your-client-id` 占位 ❌** 必填 |
| ⑤ **goats client_secret + extapp_salt** | 鉴权 | `GOATS_CLIENT_SECRET` / `GOATS_EXTAPP_SALT` | 已有占位（确认是否客户现场最新） |

**最关键的卡点**：④ `GOATS_CLIENT_ID` 仍是占位 `your-client-id`，必须问业务方拿实际 client_id。

---

## Step 2 · 联通性预检（改 .env 前必做）

不动 .env，先用 curl 验证客户现场内网能 ping 通真实 endpoint：

```bash
# 假设真后端域名是 X，真 goats 域名是 Y
TRUE_API="http://<真实 api base URL>"
TRUE_GOATS="http://<真实 goats base URL>"

# 1) api 后端 admin-api 联通（任一 read endpoint）
curl -sv --max-time 5 "$TRUE_API/admin-api/integration/securities-instrument/select" \
  -X POST -H 'Content-Type: application/json' -d '{}' 2>&1 | head -20

# 2) goats 端点联通（按 goats 实际路径）
curl -sv --max-time 5 "$TRUE_GOATS/api/internal/agent/listinstrument" 2>&1 | head -20
```

**预检通过标志**：HTTP 200 + JSON 响应（即使是 401/403 也可接受 — 说明域名可达只是缺鉴权）。
**预检失败**：HTTP 000 / DNS 解析失败 → 网络 / VPN / hosts 配置问题，先解决再继续。

---

## Step 3 · 切换 .env

按以下 diff 改 `.env`（**不要直接覆盖**，逐行核对）：

```diff
 # === 后端业务接口 ===
-OTC_API_BASE_URL=http://localhost:8099
+OTC_API_BASE_URL=http://<真实 api 后端 URL>
 OTC_API_SECRET=<客户现场最新 secret>

 # === goats 标的数据库 ===
-GOATS_BASE_URL=http://localhost:8099
+GOATS_BASE_URL=http://<真实 goats URL>
-GOATS_CLIENT_ID=your-client-id
+GOATS_CLIENT_ID=<业务方提供的真 client_id>
 GOATS_CLIENT_SECRET=<客户现场最新 secret>
 GOATS_EXTAPP_SALT=<客户现场最新 salt>
```

**其他保持不变**（不需要改）：
- `QWEN_API_BASE` / `QWEN_API_KEY` — Qwen 是公网 LLM 服务
- `CHECKPOINT_MYSQL_URI` / `BUSINESS_MYSQL_URI` — 仍指本地 MySQL（除非客户现场也接真 MySQL）
- `LANGFUSE_*` — 仍指本地 self-hosted（除非客户也有自己 LangFuse）

---

## Step 4 · 关闭 mock_api（避免误调）

```bash
# 找 mock_api 进程并杀掉
lsof -ti :8099 | xargs kill -9 2>/dev/null
# 验证
curl -s --max-time 2 http://localhost:8099 > /dev/null && echo "mock 还在跑（异常）" || echo "mock 已停 ✅"
```

---

## Step 5 · 重启 LangGraph + 跑联通性测试

```bash
# 重启 LangGraph（让它重读 .env）
lsof -ti :8000 | xargs kill -9 2>/dev/null
uvicorn app.main:app --port 8000 &
sleep 3

# 跑 ticker react 真链路验证（连真 goats / api）
TICKER_RESOLVER_MODE=react python -c "
import asyncio
from app.subgraphs.ticker.resolver import resolve_ticker
async def main():
    for raw in ['腾讯', '600519', '0700.HK']:
        r = await resolve_ticker(raw)
        print(f'raw={raw!r:<15} → {[(c.windCode, c.insShtDesc) for c in r]}')
asyncio.run(main())
"
```

**预期输出**（如果真接口工作正常）：
```
raw='腾讯'           → [('00700.HK', '腾讯控股')]
raw='600519'         → [('600519.SH', '贵州茅台')]
raw='0700.HK'        → [('00700.HK', '腾讯控股')]
```

**异常排查**：
- 全部 0 命中 → ticker 自动降级白名单 → 业务流仍 OK 但**没用上真 goats**，看日志是不是 401/403 鉴权失败
- 部分 5xx → 真后端某些端点不通，看 `tail /tmp/langgraph_app.log` 看具体 endpoint

---

## Step 6 · 跑一条 anchor 真实端到端

```bash
# 跑 1 条 g001 验证业务流完整闭环
python -m harness run --category swap --out /tmp/onsite-smoke
```

只看 g001 是否 PASS（rest 可以跑或不跑，看你时间）。

PASS = 真 api + 真 goats + 真 LLM 端到端业务流闭环 ✅

---

## Step 7 · 跑 anchor 全集（可选，~25 min）

确认 g001 PASS 后再跑全集对比 mock baseline：

```bash
bash scripts/run_real_llm_harness.sh anchor 2>&1
```

**通过标准（M3.3 退出门）**：
- swap PASS ≥ mock baseline 80.8%
- option PASS ≥ mock baseline 84.7%
- option_close PASS ≥ mock baseline 91.3%

任一退化 >5pp → 看 `.harness-runs/*/failures/` 排查（多半是真 goats 响应字段比 mock 少 / DTO 不对齐）。

---

## 紧急回滚（任一环节失败时）

```bash
# 1. 一行命令切回 mock_api（不改 .env）
export OTC_API_BASE_URL=http://localhost:8099
export GOATS_BASE_URL=http://localhost:8099
export GOATS_CLIENT_ID=your-client-id

# 2. ticker 紧急回退白名单（不调任何后端）
export TICKER_RESOLVER_MODE=whitelist

# 3. 重启 mock_api + LangGraph
nohup uvicorn mock_api.server:app --port 8099 > /tmp/mock_api.log 2>&1 &
lsof -ti :8000 | xargs kill -9 2>/dev/null
uvicorn app.main:app --port 8000 &
```

---

## 常见问题速查

| 症状 | 原因 | 修复 |
|---|---|---|
| curl 通但 Python 503 | macOS 系统代理拦截 | 已修：`httpx.AsyncClient(trust_env=False)` — 应不会再现 |
| ticker 全降级白名单 | goats 鉴权失败 | 检查 `GOATS_CLIENT_ID` 是否仍是 `your-client-id` 占位 |
| swap.place_order DTO 报错 | 真 api 响应字段比 mock 多/少 | 看 `app/tools/swap_client.py` Pydantic 模型，`extra="allow"` 应能兼容 |
| 全部 case 一致 FAIL | LangGraph 没读到新 .env | 关掉 `uvicorn` 重启 |
| ticker 多命中 HITL 阻塞 | 真 goats 模糊匹配返回多条 | M3.2 后期接 LangGraph interrupt（暂时跳过该 case 不阻塞）|

---

## 信息回报

跑完 Step 6 / Step 7 后，请把以下信息发我：

1. **g001 是否 PASS** + 看到的 final state.tickers 列表
2. **anchor 三链路 PASS 率**（如果跑了全集）
3. **失败 case 的 suspected_node 集中度**（前 3 类 `cat .harness-runs/*/failures/*.json | jq -r .suspected_node | sort | uniq -c`）
4. **真 goats 与 mock_api 行为差异**（如果发现）— 我据此决定是否要补 Pydantic 模型字段
