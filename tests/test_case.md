# 全模块测试报告

> 更新时间：2026-05-06  |  总用例：**116 条全部通过**

## 一、测试概览

| 测试文件 | 用例数 | 类型 | 需服务 | 耗时 |
|----------|--------|------|--------|------|
| `test_models.py` | ~2 | 模型/路由单测 | 否 | <0.1s |
| `test_route.py` | ~7 | 路由纯函数单测 | 否 | <0.1s |
| `test_prompts_and_history.py` | ~17 | 提示词/历史加载 | 否 | <0.2s |
| `test_ticker.py` | 27 | ticker 子图专项 | 否 | ~1s |
| `test_option.py` | 40 | option 子图专项 | 否 | ~1s |
| `test_e2e.py` | ~14 | 端到端测试 | 否(Mock) | ~2s |
| `run_integration_test.py` | 14 | 全链路集成 | **是** | ~3min |
| **合计** | **116** | — | — | — |

---

## 二、测试分类与运行命令

### 2.1 快速单测（不需要任何服务）

```bash
cd e:/VSCode/aigc-langgraph

# 全部单测（116 条，约 3 秒）
uv run pytest tests/ -v

# 按模块跑
uv run pytest tests/test_models.py -v           # 模型/路由纯函数
uv run pytest tests/test_route.py -v            # 路由优先级
uv run pytest tests/test_prompts_and_history.py -v  # 提示词加载
uv run pytest tests/test_e2e.py -v              # 端到端（Mock LLM）

# 子图专项
uv run pytest -s tests/test_ticker.py -v        # ticker 子图 27 条
uv run pytest -s tests/test_option.py -v        # option 子图 40 条
```

`-s` 参数显示每条的 INPUT/OUTPUT 对比（推荐加）。

### 2.2 集成测试（需要完整服务栈）

```bash
python tests/run_integration_test.py
```

**前置条件**：mock_api (8099) + LangGraph (8000) 都在运行。

---

## 三、各模块测试详情

### 3.1 ticker 子图 — `test_ticker.py`（27 条，1.03s）

**Mock 策略**：完全不需联网、不连数据库、不需要 VPN。

| 依赖 | Mock 方式 | Patch 位置 |
|------|-----------|-------------|
| Qwen LLM | `MagicMock` + `AsyncMock` | `app.llm.clients.get_qwen_standard` |
| 标的查询 API | `AsyncMock` 返回假数据 | `app.subgraphs.ticker.search_securities_instrument` |

**测试分组**：

| 分组 | 条数 | 覆盖内容 |
|------|------|----------|
| TestRouteFunctions | 6 | cache hit/miss、分词后路由、搜索后路由 |
| TestTokenizeKeywords | 3 | 正常分词、需重试标记、LLM 异常降级 |
| TestRetokenize | 1 | 重试分词 |
| TestSearchCandidates | 3 | 批量搜索、空关键词、API 异常 |
| TestRankCandidates | 3 | ≤6 透传、LLM 排序 top5、LLM 异常退回 top6 |
| TestFinalizeTickers | 1 | 直接确认 |
| TestTickerGraph | 6 | 5 条拓扑路径 + 图结构 |
| TestSearchSecuritiesInstrument | 4 | 工具层：批量搜索、空输入、业务异常、超时 |

**5 条拓扑路径**：

```
路径1: 缓存命中 → 直接 END
路径2: tokenize → search → finalize
路径3: tokenize → retokenize → search → finalize
路径4: tokenize → search → rank → finalize
路径5: 空消息 → tokenize → search → finalize
```

---

### 3.2 option 子图 — `test_option.py`（40 条，0.99s）

**Mock 策略**：同 ticker，纯内存。

| 依赖 | Mock 方式 | Patch 位置 |
|------|-----------|-------------|
| Qwen thinking | `MagicMock` + `AsyncMock` | `app.llm.clients.get_qwen_thinking` |
| 后端 HTTP | `MagicMock` + `AsyncMock` | `app.subgraphs.option.OtcBackendClient` |

**测试分组**：

| 分组 | 条数 | 覆盖内容 |
|------|------|----------|
| TestRouteQuickQuery | 2 | 快速询价路由 yes/no |
| TestDetectQuickQuery | 5 | 3 种关键词("参与型看涨/看跌"、"雪球") + 标准路径 + 空输入 |
| TestFastQueryApi | 3 | 正常响应、后端 error、网络异常 |
| TestExtractOption | 6 | 全部 7 种 intent、空标的、带历史、LLM 异常 |
| TestCheckParamLimit | 7 | 空跳过、正常、标的/行权价/期限/组合数超限、去重 |
| TestCallOptionApi | 4 | 正常、已有 error 跳过、后端 500、网络异常 |
| TestOptionGraph | 7 | 6 条拓扑路径 + 图结构校验 |
| TestOptionModels | 6 | OrderLeg/ExtractOutput/ParamLimit 默认值与校验 |

**6 条拓扑路径**：

```
路径1: 快速询价(参与型看涨) → detect_quick → fast_query_api → END
路径2: 快速询价(雪球)       → detect_quick → fast_query_api → END
路径3: 标准询价              → detect_quick → ticker → extract → check → call_api
路径4: 标准询价(参数超限)    → detect_quick → ticker → extract → check → END(提前)
路径5: 标准询价(LLM异常)     → detect_quick → ticker → extract → @safe_node 兜底
路径6: 标准询价(后端报错)    → ... → call_api 返回 api_code≠0
```

---

### 3.3 提示词与历史 — `test_prompts_and_history.py`（17 条）

| 分组 | 覆盖内容 |
|------|----------|
| 提示词加载 | swap intent/place_order/confirm、close intent、ticker 全部 4 个 |
| 异常处理 | 文件不存在、未知 category |
| User 消息渲染 | 简单模板、变量缺失保留占位符 |
| Markdown 解析 | `load_prompt()` 内部格式解析 |
| 历史加载 | 空 checkpoint、异常降级、有快照 |
| 历史格式化 | 空消息、截断、内容截断 |

---

### 3.4 路由 — `test_route.py`（7 条）

覆盖 7 种路由规则：

| 测试 | 输入特征 | 期望 product |
|------|----------|--------------|
| route_close_by_order_number | 包含 CO- 单号 | `option_close` |
| route_close_by_contract_number | 包含 OPT 合约号 | `option_close` |
| route_swap_by_keyword | 包含"互换" | `swap` |
| route_swap_by_attachment | 附件类型是互换合同 | `swap` |
| route_option_by_keyword | 包含"期权" | `option` |
| route_unknown | 无关键词 | `unknown` |
| route_priority_close_over_swap | 同时有 CO- 和"互换" | `option_close`（单号优先） |

---

## 四、全链路集成测试（14 条）

### 运行方式

```bash
# 终端 A：Mock API
uv run uvicorn mock_api.server:app --host 0.0.0.0 --port 8099

# 终端 B：LangGraph
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 终端 C：跑集成测试
python tests/run_integration_test.py
```

### 用例详情

| # | 用例 | product | intent | 核心 trace 节点 |
|---|------|---------|--------|----------------|
| 01 | Swap-文本下单 | swap | place_order_request | dispatch → ticker → classify → extract_place_order → call_swap_api |
| 02 | Swap-确认下单 | swap | confirm_order | dispatch → ticker → classify → extract_order_id → call_swap_api |
| 03 | Swap-请求撤单 | swap | cancel_order_request | dispatch → ticker → classify → extract_order_id → call_swap_api |
| 04 | Swap-确认改单 | swap | confirm_modify_order | dispatch → ticker → classify → extract_order_id → call_swap_api |
| 05 | Swap-查询订单 | swap | query_order_status | dispatch → ticker(含rank) → classify → extract_order_id → call_swap_api |
| 06 | Option-快速询价(参与型) | option | new_inquiry | detect_quick_query → fast_query_api |
| 07 | Option-快速询价(雪球) | option | new_inquiry | detect_quick_query → fast_query_api |
| 08 | Option-标准询价 | option | (LLM偶返unknown) | detect_quick → ticker → extract → check → call_api |
| 09 | Close-持仓查询 | option_close | close_order_query | classify_close → extract_holding_query → call_close_api |
| 10 | Close-请求平仓 | option_close | close_order_request | classify_close → extract_place_close → call_close_api |
| 11 | Close-确认平仓 | option_close | close_order_confirm | classify_close → extract_order_no_list → call_close_api |
| 12 | Close-撤销平仓单 | option_close | close_order_cancel | classify_close → extract_order_no_list → call_close_api |
| 13 | Unknown-兜底 | unknown | None | render_reply |
| 14 | 优先级-单号格式优先 | option_close | close_order_request | classify_close → extract_place_close → call_close_api |

**判定规则**：
- **PASS** = 路由 + 意图 + 子图链路 + 后端 API 全部正确
- 预期 `api_code=0`（mock 模拟成功返回）
- Unknown 兜底场景 `api_code=None`（不调后端）

---

## 五、环境依赖对照

| 测试类型 | 命令 | 需要 Docker | 需要 mock_api | 需要 LangGraph | 需要 VPN |
|----------|------|:-----------:|:-------------:|:--------------:|:--------:|
| 全部单测 | `pytest tests/ -v` | 否 | 否 | 否 | 否 |
| ticker 专项 | `pytest -s tests/test_ticker.py -v` | 否 | 否 | 否 | 否 |
| option 专项 | `pytest -s tests/test_option.py -v` | 否 | 否 | 否 | 否 |
| 端到端 | `pytest tests/test_e2e.py -v` | 否 | 否 | 否 | 否 |
| 全链路集成 | `python tests/run_integration_test.py` | **是** | **是** | **是** | 否 |

---

## 六、一键检查清单

```bash
# 1. 快速自检（0 依赖，3 秒）
uv run pytest tests/ -v

# 2. Lint 检查
uv run ruff check app/ tests/

# 3. 集成测试（需先启动服务栈）
# 终端 A: uv run uvicorn mock_api.server:app --port 8099
# 终端 B: uv run uvicorn app.main:app --port 8000 --reload
python tests/run_integration_test.py
```
