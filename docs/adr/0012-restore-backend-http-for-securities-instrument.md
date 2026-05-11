# 标的查询恢复走后端 HTTP API，弃用 MySQL 直连

> **Status update (2026-05-10)**：审计后修正 HTTP method——实际是 `GET /admin-api/integration/securities-instrument/select`（带 RequestBody，不规范但合法），不是 POST。客户端实现要用 GET-with-body：`await httpx.AsyncClient().request("GET", url, json=payload)`。
> Controller 定位：`SecuritiesInstrumentController.java:100` (`@GetMapping("/select")`)。
> 路径 `/admin-api` 前缀由 `WebProperties.adminApi` 框架级配置自动注入（`controller.admin.**` 包匹配）。

V1 闭环为脱离 VPN / 后端依赖（见 CHANGELOG 2026-05），把 `ticker_tools.py::search_securities_instrument` 从原 Dify 的 `GET /admin-api/integration/securities-instrument/select` 改成了 aiomysql 直连标的池表 `aigc-test.stock_exchange_sec_data`。这次"优化"丢失了后端 `InstrumentApiSearchHelper.searchAndScore` 中的非平凡业务逻辑：

- 多关键词并行查询（核心 3 / 最大 10 线程，30s 超时）
- `isFull=true` 精确匹配 vs. `isFull=false` `INSTR` LIKE 模糊查询的分流
- 多关键词加权配额（每关键词 `max(5, 60/N)`）
- 多关键词命中加权（每多命中 1 个 -30 relevanceScore）
- "退市"标的过滤
- 按 relevanceScore 升序，最多 30 条

直连 MySQL 后这些规则全部失效，LangGraph 标的识别会"找得到但找得不准"。我们决定 **恢复走后端 HTTP API**，把 `yudao-module-integration` 作为标的查询的唯一真理来源；MySQL 直连仅在开发/CI 闭环 demo（`mock_api/server.py` 已有 mock 实现）保留。

## Considered Options

- **保留 MySQL 直连，Python 重写打分逻辑**：双实现易飘逸，且打分规则非平凡（加权 + 配额 + 过滤交织），重写出 bug 概率高。
- **恢复 HTTP（已选）**：单一真理来源，与后端规则升级自动对齐，回滚到 Dify 时代等价的标的查询行为。
- **保留双路径**：用 feature flag 切换。增加运维复杂度，无明显收益。

## Consequences

- 生产环境必须有到 `yudao-module-integration` 的网络可达性，加重对后端服务的耦合。
- 闭环 demo 与 CI 测试继续依赖 `mock_api/server.py` 模拟该接口，不能因迁移破坏 30/30 PASS 基线。
- ADR-0009（TDSQL）的"标的池 MySQL 兼容性"风险解除——LangGraph 不再直接查 TDSQL 标的池，由后端代理。
- 需要补 shadow 比对维度：在 `scripts/shadow_compare.py` 加入"标的识别命中数 + 命中代码集合"的对比，否则下次类似回归仍然不被发现。
- 性能影响：单次标的搜索从 1 次 SQL 变 1 次 HTTP（额外网络往返 ~10-30ms），P95 延迟会上升，可接受（标的搜索本身是 ReAct 内部步骤，整体 P95 主要由 LLM 决定）。
- 推动建立"迁移完整度审计"机制：任何后续把后端逻辑搬进 LangGraph 的"性能优化"必须先在 ADR 中评估丢失的业务规则。
