# ADR 0012 · 标的查询恢复走后端 HTTP API，弃用 MySQL 直连

- 状态：已采纳（不直连标的数据库的边界继续有效；Python 标的查询编排已于 2026-09-20 退役）
- 日期：2026-05-10
- 修订：2026-08-27 深度改写为现状口径（wayfinder map #138 / 核查 #141）
- 作者：图灵科技 + Tony

## 当前职责（2026-09-22 修订）

主链经既有 Java 业务接口提交标的原文，由 Java 完成识别与权威校验，见
[标的识别边界](../backend-instrument-boundary.md)。保留的 `app/tools/ticker_client.py`
是遗留客户端，不代表现役业务仍由 Python 查询证券池。本轮不修改 Java 源码、配置或契约。
下文端点、性能与遗留待办为 2026-08-27 快照，保留作历史依据。

## 上下文（历史）

V1 闭环为脱离 VPN 依赖，曾把标的查询从 Dify 的后端 HTTP 接口改成 aiomysql 直连标的池表（`aigc-test.stock_exchange_sec_data`）。这次"优化"丢失了后端 `InstrumentApiSearchHelper.searchAndScore` 的非平凡业务规则，导致"找得到但找得不准"。决定**恢复走后端 HTTP API**，把 `yudao-module-integration` 作为标的查询唯一真理来源。

## 历史落地记录（2026-08-27）

**Endpoint 与客户端**（原行内 Status update 已吸收）：

- `GET /admin-api/integration/securities-instrument/select` —— **GET + RequestBody**（不规范但合法）；Java 侧 `SecuritiesInstrumentController.java:100` `@GetMapping("/select")` + `:104` `@RequestBody`，`/admin-api` 前缀由 `WebProperties.adminApi` 框架级注入。
- Python 落点分两层：Protocol/HTTP 实现在 `app/tools/ticker_client.py`（GET-with-body：`await client.request("GET", url, json=payload)`）；子图调用点在 ~~`app/subgraphs/ticker/tools.py`~~（completeness / rank 工具）与 `resolver.py`。原文的 `ticker_tools.py` 文件名已不存在。
- ⚠️ 无契约测试断言 method=GET + body 非空（现有测试全靠 AsyncMock），回归时可能被悄悄改回 POST——护栏待补（见后果）。

**后端业务规则清单**（对照 `aigc/api` 现码更新；正是本 ADR"与后端规则升级自动对齐"收益的实证——2026-07-06 后端 commit `4088b4a5` 改了数字，HTTP 方案零改动跟上）：

- 多关键词并行查询（核心 3 / 最大 10 线程，30s 超时）✅ 不变
- `isFull=true` 精确 vs `isFull=false` `INSTR` 模糊分流 ✅ 不变
- 多关键词命中加权（每多命中 1 个 -30 relevanceScore）✅ 不变
- "退市"标的过滤 ✅ 不变
- 配额：~~`max(5, 60/N)`~~ → **`max(5, 100/N)` + 低命中关键词释放额度轮询再分配**（`SEARCH_SCORE_RESULT_LIMIT=100` / `MIN_KEYWORD_QUOTA=5`）
- 结果上限：~~30 条~~ → **100 条**，按 relevanceScore 升序（**分数越小越相关**，0=精确匹配）

**MySQL 直连的处置（超出原计划）**：原决策保留直连给 mock_api 闭环 demo；`mock_api/` 已于 2026-05-13（commit `4ac9f0b`）整体删除，直连代码零残留。现状的测试形态 = AsyncMock 单测 + `scripts/probe_*_e2e.py` 真后端探针。遗留清理项：

- 死配置：`app/config.py` 的 `ticker_mysql_*`（5 项）与 `securities_instrument_url/key`（零引用）+ `.env.example` 对应段
- rot 脚本：~~`scripts/demo_closed_loop.py`~~（已删除）曾 patch 已删符号，早已不可运行
- `.env.example` 的 `OTC_API_BASE_URL` 示例含 `/admin-api` 会与 client 拼接出双前缀（真实 `.env` 与客户模板写法正确）

**Shadow 比对维度**：原 TODO 已完成——`scripts/shadow_compare.py` 归一化 `tickers` + `ticker_hitl_candidates` 做字段级 diff，有测试覆盖。

## 备选方案

- **保留 MySQL 直连，Python 重写打分逻辑**：双实现易漂移，打分规则非平凡，重写出 bug 概率高。
- **恢复 HTTP（已选）**：单一真理来源，与后端规则升级自动对齐（已被 2026-07-06 事件验证）。
- **保留双路径 feature flag**：运维复杂度增加，无收益。

## 后果（2026-08-27 历史口径）

- 生产必须有到 `yudao-module-integration` 的网络可达性（`.env` 的 `OTC_API_BASE_URL`）。
- [ADR 0009](./0009-mysql-version-and-tdsql-compatibility.md) 的"标的池 MySQL 兼容性"风险解除——由后端代理。
- 性能：1 次 HTTP 额外 ~10-30ms，整体 P95 由 LLM 决定，可接受。
- "迁移完整度审计"机制持续有效：任何把后端逻辑搬进 LangGraph 的"性能优化"必须先在 ADR 评估丢失的业务规则。
- ✅ 2026-09-22 已清理：`app/config.py` 死配置 `ticker_mysql_*`（5 项）与 `securities_instrument_url/key`，及 `.env.example` / `.env.customer.template` / `infra/nodes-run.env.example` 对应段（`tests/test_database_config.py` 守护不复活）。GET-with-body 契约测试随 LangGraph 侧调用方退役而不再需要。
