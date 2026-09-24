# app/ 结构体检与整理（2026-09-24）

对 `app/` 做了一轮结构体检：先画包级依赖图、查死代码和重复实现，再在不改业务行为的前提下整理结构。每一步都跑了全量 pytest、ruff、mypy 和各项一致性 lint。分层约定见 [architecture/README.md §分层](../architecture/README.md)。

## 1. 体检发现

| 类别 | 发现 |
|---|---|
| 依赖方向 | `nodes/remember_confirmed.py` 反向依赖三个子图的 `order_id.py`；`graph ↔ extraction`、`extraction ↔ prompts` 存在包级循环；`api/idempotency.py` 导入 persist 节点的私有函数 `_parse_mysql_uri` |
| 命名与归属 | `app/execution/` 只有 `confirmation.py`，名字容易和 `app/node_execution/` 混淆；期限换算、最大跟量这类纯业务规则放在证据框架 `extraction/` 里；幂等存储、对账这类 MySQL 读写放在 `api/` 里；node_trace 写库逻辑放在 persist 节点里 |
| 重复实现 | 中文数字 / 序号解析有 5 份；订单号正则散落在 7 处以上；三个子图的 null 字面量递归清洗逐字重复；`*_unknown` 兜底节点和意图后路由也各复制了三份；5 个 LLM 工厂函数的函数体几乎完全相同 |
| 死代码 | `graph/memory.py`、`cascade.with_cascade_guard`、`close/merge.py`、`swap/aggregate.apply_*`、swap 确认 / 撤单 / 查单参数模型、`parse_excel_rows`、若干零引用私有函数、7 个无引用的 Settings 字段 |
| 过时注释 | 指向已删除的 `dify/yaml/`、`spec/code_nodes/`；仍写着"入口字段由 ingest 写入"（实际由 `inputs_to_state` 写入）；子图节点数与节点名已过时；CLAUDE.md 原则编号对不上 |
| 缺陷 | `/ready` 的 MySQL 探针自行用 `urlparse` 解析连接串，没有解码 URL 编码的密码，也缺少会话字符集初始化。密码含特殊字符时，业务连接正常但探针失败，`/ready` 误报 503 |

## 2. 已完成的整理

| 提交主题 | 内容 |
|---|---|
| LLM 工厂与配置 | 5 个工厂共用 `_build_llm`；删除 `make_qwen_thinking` 和 7 个无引用的 Settings 字段（`extra=ignore`，旧 `.env` 仍可用） |
| 死代码 | 删除上表所列死代码；只覆盖死代码的测试一并删除，确认口令测试改为直接测 `is_confirmation` |
| 新建 `app/domain/` | 包含 `order_ids`（订单号形态单一来源）、`numerals`、`confirmation`（由 `app/execution/` 迁入）、`tenor`、`fast_execution`（由 `extraction/` 迁入）、`sanitize`。迁移前后所有模块级正则逐字比对，唯一变化是 `OPT[G]?` 改写为等价的 `OPTG?` |
| 消除包级循环 | 依赖方向固定为 prompts → extraction → wire_model；`extraction/identity` 只在类型检查时引用 `AgentState` |
| 新建 `app/storage/` 读写模块 | 迁入 `idempotency.py`、`reconciliation.py`，新增 `node_trace.py`；全项目的 MYSQL_URI 只在 `storage.mysql.connection_args` 一处解析；修复上述 `/ready` 探针缺陷（先写 RED 测试） |
| 子图骨架 | 新增 `subgraphs/common.py`（`make_unknown_node` / `intent_router` / `add_intent_dispatch`）；主图与三个子图的 xray 拓扑逐边比对一致 |
| backend 适配层 | 删除 `_context` / `_message_id` 这类纯转发包装；`BotContext` 的必填字段改为引用 `REQUIRED_FIELDS` |
| 分层守护 | `tests/test_architecture_layers.py` 以白名单和黑名单守护依赖方向（含函数内延迟导入） |

## 3. 有意未做的事项（需业务确认或另立任务）

1. **形态有差异的订单号正则**：路由规则的 Q- 要求 10 位数字、CO- 要求 8 位十六进制，比规范形态更窄；swap 的 `place_order` / `candidate_scope` / `selection_rules` 用的是更宽的 `H-` 形态。收敛会改变路由和解析结果，需要业务方先确认。这些形态目前已集中登记在 `app/domain/order_ids.py`（宽形态除外）。
2. **金额数量级表不一致**：swap、close、option 的 `_number` / scale 表对 `k` / `kw` / `e` 的支持不同。统一前需要确认各产品线允许哪些写法。
3. **`swap/selection_rules._number`**：遇到畸形输入会抛异常，通用解析则会返回数值，两者语义不同，因此没有并入 `domain.numerals`。
4. **超长函数**：`api/routes._execute_workflow`（约 200 行）、`domain/confirmation.parse_confirmation`（约 150 行）、`nodes/route_rules.classify_trade_type`（约 125 行）、`swap/normalize.normalize_candidates`（约 160 行）、`close/normalization.normalize_place_candidates`（约 140 行）。建议有针对性的回归用例时再逐个拆分。
5. **节点元数据分四处维护**：`node_execution/catalog.py`、`node_execution/registry.py::_EXECUTION_OPTIONS`、`observability/node_labels.py`、`harness/node_registry.py`。可考虑以 catalog 为单一来源生成其余三处。
6. **历史命名**：option 的 `extract_*` 节点已经全部是确定性代码，`TickerClient` 实际只查交易对手。改名会影响节点名、trace、Langfuse 数据集和 CLAUDE.md 的 Protocol 约定，需要单独评估。
7. **其它**：`observability/canary.py` 直接读环境变量而不经过 Settings；`swap/multimodal._fetch_bytes` 下载外部文件时没有走 `http_pool`；`api/routes` 在超时路径上直接调用 persist 节点。
