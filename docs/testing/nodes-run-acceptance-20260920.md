# 节点执行接口本地验收记录（2026-09-20）

## 范围与环境

- 接口：`POST http://127.0.0.1:8010/v1/nodes/run`。
- 65 个目录项全部按名称独立调用：main 14、option 16、swap 13、option_close 15、ticker 7。
- 文本 LLM：现有配置的真实 `deepseek-v4-pro`；没有替换模型返回值。
- Option、Swap、Ticker、Message、GOATS agent HTTP：现有 `mock_api`，监听本机 `18099`，`DRY_RUN_BACKEND=false`。Windows 拒绝绑定默认 `8099`，因而仅本次验收改端口。
- MySQL：本机 `3530`，版本 8.0.36，业务库 `otc_agent_business`、checkpoint 库 `otc_agent_checkpoint`。应用开启 MySQL checkpoint；单节点图仍不使用 checkpoint。
- `ENVIRONMENT=staging`，`persist_intent` 注入真实 MessageClientHttpx 工厂并向本地 mock 发出请求。LLM 网络请求在允许联网的本地验收进程执行。
- 未覆盖 `.env`，未改业务节点、现有提示词、fixture 或 `scripts/ai_test_langgraph/`。mock 端点已覆盖本次需要，无需新增业务 mock 分支。

本记录属于接口和调用链验收，不是客户真实后端业务验收。

## 实际 HTTP 结果

| 命名空间 | 正常返回 200 | 明确错误 500 | 说明 |
| --- | --- | --- | --- |
| main | 14 | 0 | 公共节点与三个业务子图入口均已调用 |
| option | 16 | 0 | 包含询价复合子图和 7 个内部阶段 |
| swap | 12 | 1 | 图片节点的视觉模型配置不被当前网关支持；其余节点包括 Excel 均通过 |
| option_close | 15 | 0 | 包含平仓复合子图和 7 个内部阶段 |
| ticker | 7 | 0 | 三路真实 LLM、GOATS 单条解析、合并和汇总均通过 |
| 合计 | 64 | 1 | 65 个节点均给出约定格式的输出或明确错误 |

代表性结果：

- `option/option_intent` 返回 `intent=new_inquiry`。
- `main/option` 执行询价链，返回 `api_code=0`，trace 包含询价内部阶段。
- `main/swap` 执行提取、对手识别和提交，返回 `api_code=0`。
- `main/option_close` 执行持仓查询，返回 `intent=close_order_query`、`api_code=0`。
- `option_close/place_close_extract`、`option/inquiry_extract` 返回私有阶段结果，未被 AgentState 过滤。
- `ticker/resolve_org_item` 输入 index=0，只返回对应 `winners`；mock 权威标的代码为 `0700.HK`，未自动执行 assemble。
- `ticker/infer_codes` 返回腾讯控股候选 `00700.HK`；`judge_type` 返回 `EQUITY`。
- `swap/swap_excel_order` 完成真实本地文件下载、Excel 解析和真实 LLM 抽取，返回 `place_params`，未自动提交。

图片节点返回保留完整节点 output 的 HTTP 500，`error.type=BadRequestError`。上游 API 返回 400：当前支持 `deepseek-flash`、`deepseek-v4-pro`，但视觉工厂请求的是 `qwen-vl-max-latest`。未改模型配置或伪造 OCR 结果；成功路径已通过自动化的模型边界 mock 测试。要完成真实图片成功验收，需要配置支持视觉模型的现有网关和相应 `QWEN_MODEL_VL`。

## 持久化证据

显式 HTTP 调用 `main/persist` 后，按验收专用 `trace_id=node-api-acceptance-20260920` 查询 `node_trace`，查到 `node_name=acceptance` 的记录。三次本地探测分别写入一行，符合该节点原有非幂等插入行为。

独立自动化 MySQL 验收也通过：接口执行后查询唯一 trace_id，核对 `node_name=local_acceptance`、`step_index=0`、`duration_ms=7`，随后仅删除该测试自己的记录。另有测试验证数据库写入失败时仍返回原有正常节点输出。

`persist_intent` 的测试通过真实 MessageClientHttpx 与 ASGI HTTP mock 核对收到的请求，覆盖不注入工厂时的跳过分支、缺上下文的 422，以及应用生命周期中两种接口共用客户端工厂。

## 自动化与仓库基线

新增接口/执行器测试 47 项通过；本地 MySQL 测试 1 项通过（默认收集、默认跳过，使用 `RUN_NODE_MYSQL_TEST=1` 开启）。覆盖注册项/策略一致、输出保真、严格校验、上下文、单节点隔离、并发、重试耗尽、写节点单次调用、HTTP mock、复合子图、图片与 Excel。

`ruff check app/ tests/` 通过。新增模块及接线文件的 `mypy --follow-imports=silent` 检查通过。全量 `mypy app/` 为 105 个错误、37 个文件；对分支起点的干净导出执行同一命令，得到同样 105 个错误；归一化逐项比较没有新增或消失的诊断。

全量 pytest 的最终计数见本节末尾。失败项已在未修改的分支起点或工作区环境中确认：

1. `test_convert_csv_to_excel::test_default_input_is_relative_to_repository`：现有 CSV 第 23 列表头为空。
2. `test_harness::test_default_discovery_includes_unified_b_dialect`：多轮用例数量实际 261，测试写死 260。
3. `test_harness::test_option_case_is_multiturn`：现有 case-025 为 3 轮，测试期待 4 轮。
4. `test_harness::test_index_and_filter`：option 用例实际 14，测试写死 13。
5. `test_agents_md_sync::test_real_repo_in_sync`：同步脚本递归扫描工作区中已有的 `.harness-runs`、`.pytest-tmp`、`.tmp` 临时导出目录。对仅含受版本控制文件的干净导出运行 `python -X utf8 scripts/sync_agents_md.py --check` 通过；本次未改同步规则或生成产物。

前四项在未修改的分支起点干净导出中复现（同组选定测试 65 通过、4 失败）；同步检查在干净导出中通过。未为使检查变绿而修改业务数据或放宽既有断言。

最终全量结果：`5 failed, 2239 passed, 16 skipped`，用时 227.59 秒。16 个跳过项包含本次默认关闭的本地 MySQL 验收；该项另行启用后通过。最终专项目录测试结果为 `47 passed, 1 skipped`。
