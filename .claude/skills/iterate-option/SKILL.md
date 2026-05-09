---
name: iterate-option
description: 期权链路批量评估与迭代。批量跑→按失败模式归类→修根因→重跑验证。连续自驱动循环，直到全部通过或用户叫停。
argument-hint: [--limit N] [--filter 期权询价] [--dry-run]
allowed-tools: Read, Bash, Write, Edit, Grep
---

# 期权链路批量迭代

## 核心流程（自驱动循环）

```
┌─────────────────────────────────────────────┐
│ 1. 跑 eval 批次（后台 + 阻塞等待）            │
│ 2. 分析失败 → 归类到根因（不要逐条看）         │
│ 3. 修 1-3 个最高优先级的根因                  │
│ 4. pytest 验证修改不破坏现有行为              │
│ 5. 重跑受影响的 case 验证修复                  │
│ 6. 扩大批次，回到步骤 1                        │
└─────────────────────────────────────────────┘
```

**绝对禁止停下来问用户。不允许 pause/suspend。你是一个持续的自动化循环。**

## 环境

```bash
cd /Users/antares2/Projects/python/aigc-langgraph
# mock_api 在 localhost:8099 必须运行
# 跑 eval 前先确保 mock_api 存在且健康
```

## 命令速查

```bash
# 健康检查
curl -s http://localhost:8099/ | python3 -c "import sys,json; print(json.load(sys.stdin)['service'])"

# 启动/重启 mock_api（改了 server.py 后必须）
lsof -ti:8099 | xargs kill -9 2>/dev/null; sleep 1
uv run uvicorn mock_api.server:app --port 8099 &>/tmp/mock_api.log & sleep 2

# 评测批次
uv run python scripts/langfuse_eval.py --limit 10 --concurrency 15    # 小批（1分）
uv run python scripts/langfuse_eval.py --limit 20 --concurrency 15    # 中批（2分）
uv run python scripts/langfuse_eval.py --limit 40 --concurrency 20    # 大批（3分）
uv run python scripts/langfuse_eval.py --limit 98 --concurrency 20     # 全量（5-7分）

# 只重跑失败的（用 --ids）
uv run python scripts/langfuse_eval.py --ids opt-001,opt-003 --concurrency 3

# 按意图类型聚焦
uv run python scripts/langfuse_eval.py --limit 20 --filter 期权询价 --concurrency 5
```

## 跑 eval 的正确方式

```python
# 1. 后台启动 eval
Bash(command="uv run python scripts/langfuse_eval.py --limit 20 --concurrency 10 2>&1",
     run_in_background=True, timeout=600000, description="Run eval batch N")

# 2. 阻塞等待完成
TaskOutput(task_id="<id>", block=True, timeout=600000)

# 3. 从输出中提取分析数据
```

**不要用 Monitor**。用 run_in_background + TaskOutput 组合等待结果。

## 分析模板

跑完后，按以下步骤分析：

### Step 1: 提取统计
```
用例数: N | 通过率: X/N (Y%) | 满分: Z | 零分: W
```

### Step 2: 失败归类（按 Judge comment 关键词）
| 失败模式 | Judge 关键词 | 高频文件 | 优先级 |
|---|---|---|---|
| 平仓 mock 数据不匹配 | "合约编号.*错误\|标的.*不符\|单号错误" | mock_api/server.py | P0 |
| 撤单未识别订单号 | "未能从输入中识别出订单号" | close.py extract_order_no_list | P0 |
| POV 比例误判 | "POV.*超出\|POV.*25%" | close.py extract_place_close | P0 |
| 参数校验缺失 | "未提示.*参数不完整\|未拦截\|应拒绝" | close.py | P1 |
| 意图识别错误 | "未识别.*意图\|意图.*错误" | 提示词 | P1 |
| 持仓查询返回错误 | "持仓.*错误\|应返回持仓" | mock_api + close.py | P1 |
| 反案例穿透 | "不应.*但\|未拒绝\|错误执行" | route.py / close.py | P2 |
| LLM 超时 | "超时" | LLM 配置 | P2 |
| Judge JSON 解析失败 | "JSON解析失败" | 非代码 bug，忽略 | - |

### Step 3: 按优先级修根因
P0 先修 → 每个 P0 修完通常能救 3-10 条 case

## mock_api 改法

mock_api 是通用模拟后端，不要写 `if case_id == "xxx"` 这种 hardcode。

```python
# ✅ 正确：按操作类型区分
if type_ in ("close_order_query",):
    return backend_ok(format_holdings(_POSITIONS))

# ✅ 正确：使用共享的持仓数据库
_POSITIONS: list[dict] = [{...}, {...}]  # 模拟持仓数据

# ❌ 错误：per-case 硬编码
if "opt-082" in body.get("messageId", ""):
    return special_response
```

## 改 close.py 时注意

close 子图节点顺序：
```
classify_close_intent → extract_holding_query / extract_place_close / extract_order_no_list
    → call_close_api → END
```

- `call_close_api` 在 close_order_request 时跳过后端调用（确认卡已在 extract_place_close 生成）
- regex fallback 加在 LLM 返回空结果之后
- POV 校验在 extract_place_close 的客户端预校验段

## pytest 守卫

修改 app/ 下任何代码后，跑一次快速 pytest 确认没破坏现有行为：

```bash
pytest tests/test_option.py tests/test_ticker.py tests/test_e2e.py tests/test_closed_loop.py tests/test_route.py -v --tb=line 2>&1 | tail -5
```

必须全部通过再继续 eval。

## 迭代节奏

```
Round 1: --limit 20 --concurrency 10   (4分钟)
  → 分析失败归类，修 P0 根因
  → pytest 验证
  → 重跑失败的 --ids (1分钟)

Round 2: --limit 40 --concurrency 10   (8分钟)
  → 同上

Round 3-5: --limit 98 --concurrency 15  (15-20分钟)
  → 全量迭代直到 98/98 pass
```

**不要手动逐条 debug**。批量归类 → 修根因 → 验证。

## 关键文件

| 文件 | 用途 | 可改？ |
|---|---|---|
| `scripts/langfuse_eval.py` | 评估脚本 | ❌ 绝对不准 |
| `mock_api/server.py` | 模拟后端 | ✅ 通用逻辑可改 |
| `app/subgraphs/close.py` | 平仓子图 | ✅ |
| `app/subgraphs/option.py` | 期权子图 | ✅ |
| `app/nodes/route.py` | 产品路由 | ✅ |
| `app/prompts/option/intent_extract.md` | 期权提示词 | ✅ 可改（创 _v2 副本） |
| `app/prompts/option_close/*.md` | 平仓提示词 | ✅ 可改（创 _v2 副本） |
| 测试用例 Dataset | Langfuse 云端 | ❌ 不准改 |

**提示词改法**：不直接改原始 Dify 导出的 .md，而是：
1. 复制 `xxx.md` → `xxx_v2.md`
2. 在代码中 `load_prompt("option", "intent_extract_v2")` 加载新版
3. A/B 对比验证后，满意了再把 _v2 覆盖回原文件（此时说明新版优于 Dify 原始版）
