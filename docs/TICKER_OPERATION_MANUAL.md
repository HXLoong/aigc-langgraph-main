# 标的识别操作手册 P0

> 标的识别（Ticker Identification）是 LangGraph 智能助手的核心子图，负责从用户自然语言消息中提取金融标的代码。
> 本文档面向开发、测试、联调人员，覆盖从启动服务到接口测试的完整操作链路。

---

## 1. 架构速览

**拓扑**：`tokenize → [retokenize] → search → [rank] → finalize`，5 节点，LLM 1-3 次。

```
START → cache? → tokenize(LLM) → quality? → retokenize(LLM) → search(API) → count>6? → rank(LLM) → END
                  │                │                        │              │
                  └→ END(cache)    └→ search(API)           └→ finalize   └→ finalize
```

**核心文件**：[ticker.py](../app/subgraphs/ticker.py)（子图）、[ticker_tools.py](../app/subgraphs/ticker_tools.py)（API工具）、[ticker_models.py](../app/subgraphs/ticker_models.py)（模型）、[state.py](../app/state.py)（TickerCandidate）。

**硬约束**：所有标的必须 `from_goats=True` | 候选>6 必须 LLM 排序 | 分词不足自动重试1次 | 缓存命中跳过全图。

---

## 2. 环境准备

```bash
pip install -e ".[dev]"          # 安装依赖
```

**.env 关键配置**：`SECURITIES_INSTRUMENT_URL`（内网标的查询，需VPN）、`QWEN_API_KEY`（LLM分词/排序）、`OTC_API_BASE_URL=http://localhost:8099`（Mock后端）。

**VPN 验证**：`curl http://172.16.8.28:8807/admin-api/integration/securities-instrument/select`

---

## 3. 启动服务

```bash
# 终端 1：Mock 服务器（26个接口，端口 8099）
cd mock_goats_api && uvicorn server:app --reload --port 8099

# 终端 2：LangGraph 主服务（端口 8002）
uvicorn app.main:app --reload --port 8002
```

验证：`curl localhost:8099/` → `{"service":"GOATS Mock API",...}` | `curl localhost:8002/docs` → Swagger。

---

## 4. Apifox 接口测试

### 4.1 导入 OpenAPI 文档

Mock 服务器的 OpenAPI 文档已导出至 [mock_goats_api/openapi.json](../mock_goats_api/openapi.json)，可直接导入 Apifox：

1. 打开 Apifox → 项目设置 → 导入数据
2. 选择 `mock_goats_api/openapi.json`
3. 导入后项目名：**GFZQ → LangGraph广发接口模拟**
4. 共 26 个接口：20 个 GOATS + 6 个后端业务

### 4.2 接口分类

| Tag | 数量 | 说明 |
|-----|------|------|
| GOATS Option | 11 | 场外期权：询价/下单/撤单/平仓 |
| GOATS Swap | 6 | 收益互换：下单/撤单/改单/查询 |
| GOATS Counterparty | 1 | 交易对手查询 |
| GOATS Trading | 1 | 交易时间配置 |
| Dify | 1 | LLM rerank |
| OTC Backend | 6 | 后端业务 API（互换/期权/交易对手/订单/Bot/意图） |

### 4.3 测试标的识别链路

标的识别通过主服务 `/v1/message` 接口触发。在 Apifox 中发送 POST 请求：

**请求示例（POST `http://localhost:8002/v1/message`）**：
```json
{
    "conversation_id": "test-apifox-001",
    "message_id": "msg-001",
    "room_id": "test-room",
    "user_id": "test-user",
    "guid": "test-guid",
    "raw_content": "帮我查一下600519和000858的报价",
    "quote_content": null,
    "quote_appinfo": null,
    "attachments": []
}
```

**预期响应**：
```json
{
    "product_type": "swap",
    "intent": "place_order_request",
    "api_code": 0,
    "reply": "...",
    "trace": [
        {"node": "tokenize_keywords", "decision": "extracted 2 keywords"},
        {"node": "search_candidates", "decision": "found 2 candidates"},
        {"node": "finalize_tickers", "decision": "confirmed 2 tickers"}
    ]
}
```

### 4.4 典型测试用例

| 用例 | raw_content | 预期 product_type | 预期 trace 关键节点 |
|------|-------------|-------------------|-------------------|
| 代码查询 | `600519 000858` | swap | tokenize → search → finalize |
| 中文名查询 | `贵州茅台和五粮液` | swap | tokenize → search → finalize |
| 模糊查询 | `mt` | swap | tokenize → retokenize → search → finalize |
| 多标的排序 | `0 1 2 3 4 5 6 7 8 9` | swap | tokenize → search → rank |
| 空输入 | `` | unknown | render_reply |
| 无关输入 | `今天天气怎么样` | unknown | render_reply |

---

## 5. 自动化测试

### 5.1 单元测试（标的识别子图）

```bash
# 运行全部 ticker 测试（带 INPUT/OUTPUT 可视化输出）
pytest -s tests/test_ticker.py -v

# 只跑路由函数
pytest -s tests/test_ticker.py::TestRouteFunctions -v

# 只跑节点函数
pytest -s tests/test_ticker.py::TestTokenizeKeywords -v
pytest -s tests/test_ticker.py::TestSearchCandidates -v
pytest -s tests/test_ticker.py::TestRankCandidates -v

# 只跑子图整体（5 条拓扑路径）
pytest -s tests/test_ticker.py::TestTickerGraph -v
```

**测试覆盖的 5 条路径**：

| 路径 | 场景 | LLM 调用 |
|------|------|----------|
| path1 | 缓存命中，直接跳过 | 0 |
| path2 | 分词→搜索(≤6)→确认 | 1 |
| path3 | 分词→重试→搜索→确认 | 2 |
| path4 | 分词→搜索(>6)→排序 | 2 |
| path5 | 空消息→直接返回空 | 1 |

### 5.2 集成测试

```bash
# Mock 后端全链路（14 条用例，覆盖 Swap/Option/Close/Unknown）
python tests/run_integration_mock.py
```

预期输出：
```
结果: 14 PASS, 0 TRACE, 0 FAIL, 14 total
```

### 5.3 全量测试

```bash
pytest tests/ -v
# 76 个测试全部通过
```

---

## 6. 代码级测试（Mock LLM）

不想调真实 LLM 时，可以用 Mock 跑图测试：

```python
from unittest.mock import AsyncMock, MagicMock, patch
from app.subgraphs.ticker_models import TokenizeOutput

# 1. Mock 分词 LLM
mock_tok = MagicMock()
mock_tok.ainvoke = AsyncMock(return_value=TokenizeOutput(
    keywords=["600519", "000858"], needs_refinement=False
))

# 2. Mock 标的查询 API
api_data = [
    {"keyword": "600519", "windCode": "600519.SH", "insShtDesc": "贵州茅台",
     "insFamily": "EQUITY", "currency": "CNY", "exchange": "SH", "from_goats": True},
]

# 3. 跑图
with patch("app.llm.clients.get_qwen_standard") as m_std, \
     patch("app.subgraphs.ticker.search_securities_instrument") as m_api:
    m_std.return_value.with_structured_output.return_value = mock_tok
    m_api.ainvoke = AsyncMock(return_value=api_data)

    result = await graph.ainvoke(state, config)
    print(result["resolved_tickers"])  # [TickerCandidate(...), ...]
```

---

## 7. 关键 State 字段

标的识别涉及的核心 State 字段（定义在 [app/state.py](../app/state.py)）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `raw_tickers` | `list[str]` | LLM 从用户消息中分词提取的原始关键词 |
| `ticker_candidates` | `list[TickerCandidate]` | search_securities_instrument 返回的候选 |
| `resolved_tickers` | `list[TickerCandidate]` | 排序过滤后的最终标的列表（from_goats=True） |
| `_needs_refinement` | `bool` | 分词质量不足标记，触发 retokenize |
| `trace` | `list[TraceEntry]` | 每个节点的决策记录（追加合并） |

**TickerCandidate 结构**：

```python
class TickerCandidate(BaseModel):
    keyword: str              # 原始关键字
    wind_code: str | None     # Wind 代码（如 "600519.SH"）
    ins_sht_desc: str | None  # 简称（如 "贵州茅台"）
    ins_lng_desc: str | None  # 全称
    ins_family: str | None    # EQUITY / FUTURE / FUND
    currency: str | None      # CNY / HKD / USD
    exchange: str | None      # SH / SZ / HK / NYM
    is_complete: bool         # 是否有完整 wind_code
    from_goats: bool          # 是否经 goats 验证（强制 True）
```

---

## 8. 常见问题

### 8.1 标的查询超时

**现象**：每次请求等待 15s，日志显示 `search_securities_instrument 连接超时`

**原因**：VPN 未连通，`172.16.8.28:8807` 不可达

**解决**：
1. 确认 VPN 已连接
2. `curl http://172.16.8.28:8807/admin-api/integration/securities-instrument/select` 验证
3. 本地开发可设 `OTC_API_BASE_URL=http://localhost:8099` 走 Mock

### 8.2 分词结果为空

**现象**：`raw_tickers = []`，后续节点全跳过

**原因**：LLM 未识别到任何标的关键词（纯闲聊消息正常），或 Qwen API 不可用

**排查**：
1. 检查 `QWEN_API_KEY` 是否有效
2. 看 trace 中 `tokenize_keywords` 节点的 `output_preview`
3. 对模糊输入期望走 retokenize 路径

### 8.3 from_goats 全为 False

**现象**：resolved_tickers 为空或标的缺少 from_goats 标记

**原因**：search_securities_instrument 未被调用或 API 返回了非 goats 数据

**排查**：
1. 检查 trace 中是否有 `search_candidates` 节点
2. 查看 `search_candidates` 的 `decision` 和 `output_preview`
3. 如果 decision 是 "no_keywords"，说明上游分词未产出关键词

### 8.4 端口占用

**现象**：`uvicorn` 启动报 `Address already in use`

**解决**：
```powershell
# 查找占用端口的进程
netstat -ano | findstr :8002
netstat -ano | findstr :8099

# 强制结束
taskkill /PID <PID> /F
# 或 PowerShell
Stop-Process -Id <PID> -Force
```

### 8.5 Mock 接口返回 400/500

**现象**：集成测试 `api_code=400` 或 `api_code=500`

**原因**：Mock 服务未重启或旧进程仍占用端口

**解决**：
```bash
# 确认 Mock 服务已更新后重启
taskkill /F /IM python.exe   # 慎用，会关掉所有 Python
# 更好的方式：找到特定 PID 后 kill
```

---

## 9. 文件索引

| 文件 | 用途 |
|------|------|
| [app/subgraphs/ticker.py](../app/subgraphs/ticker.py) | 子图定义（核心） |
| [app/subgraphs/ticker_models.py](../app/subgraphs/ticker_models.py) | TokenizeOutput 模型 |
| [app/subgraphs/ticker_tools.py](../app/subgraphs/ticker_tools.py) | search_securities_instrument 工具 |
| [app/state.py](../app/state.py) | AgentState + TickerCandidate |
| [app/prompts/ticker/tokenize_v2.md](../app/prompts/ticker/tokenize_v2.md) | 分词提示词（当前版本） |
| [app/prompts/ticker/rank.md](../app/prompts/ticker/rank.md) | 排序提示词 |
| [tests/test_ticker.py](../tests/test_ticker.py) | 27 个测试（路由/节点/图/工具） |
| [tests/run_integration_mock.py](../tests/run_integration_mock.py) | 14 条全链路集成测试 |
| [mock_goats_api/server.py](../mock_goats_api/server.py) | Mock 服务器（26 个接口） |
| [mock_goats_api/openapi.json](../mock_goats_api/openapi.json) | Apifox 可导入的 OpenAPI 文档 |
| [docs/TICKER_GRAPH_REFACTOR.md](../docs/TICKER_GRAPH_REFACTOR.md) | ReAct→StateGraph 重构记录 |
