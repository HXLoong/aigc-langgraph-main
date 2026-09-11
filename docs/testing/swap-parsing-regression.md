# 互换解析回归记录（2026-09-11）

互换解析修复包含按标的身份绑定订单、补齐全新文本多单遗漏的尾部交易对手，以及在标的识别副本中遮蔽明确的订单值。未修改提示语模板、HTTP 接口、Java 或数据库。同批变更还包含 CSV 转 Excel 工具、测试集工作簿、互换生产用例的响应断言调整，以及提交前回归测试修正。

## 行为

- 提取后的订单无有效引用、无已有订单号且至少两笔时，只有本次输入唯一命中一个完整尾部 `shortName` 才补空值。已有非空值保留。多对手、同名不同账户、非文本输入均跳过；重叠名称按最长完整匹配处理，纯数字短名须有交易对手/对手/账号标签。
- `swap_place_order` 的 trace 中，`counterparty_completion` 逐单记录原值、结果值、`filled/preserved/skipped` 及原因。
- `resolve_ticker_full` / `tokenize` 的 `filter_order_context` 默认关闭，仅互换调用方启用。过滤发生在分词和数字提取前，按字符位置遮蔽数量、价格、比例及完整对手名称，保留明确代码、复合名称及用途不明的数字。原始消息和 LLM 订单参数保持不变。
- 标的仍经过 GOATS 校验和现有身份绑定。没有增加 LLM 调用，也没有根据后端文案改写回执。

## 验证

```powershell
$env:PYTHONIOENCODING = "utf-8"
$env:ENABLE_LANGFUSE = "false"
.venv/Scripts/python.exe -m pytest tests/ -v --tb=short
.venv/Scripts/python.exe -m ruff check app/ tests/ scripts/convert_csv_to_excel.py
.venv/Scripts/python.exe -m mypy app
```

提交前全量基线为 **20 failed / 1709 passed / 15 skipped**。最终回归按 CI 约定关闭 Langfuse，避免外部追踪导出影响本地验证；`tests/api` 按现有 pytest 配置排除。

修正后全量结果为 **1736 passed / 15 skipped**（129.69 秒），无失败和 pytest 警告。Ruff 检查 `app/`、`tests/` 与新增转换脚本通过，本次修改的 7 个 Python 文件均通过格式检查。用参数化场景补充覆盖后，可执行测试较基线增加 7 项。

Mypy 复查仍为 **134 errors / 36 files**，与解析修复阶段记录一致。此次 pytest 修正只修改测试和回归记录，没有修改 `app/`。

`test_parsing_http_boundary.py` 固定外部 LLM 输出和 HTTP 响应，运行真实提取节点、ticker 分词/推断结果解析/GOATS 查询、身份绑定、提交节点、请求 DTO、Httpx JSON 序列化和 render。两条报告输入都验证：

- NVDA.O / TSM.N 与 1453 / 3071 股一一对应；市价/均价、算法、POV 比例和对手保持正确。
- 数量、均价小数位、完整对手名称不进入 LLM 候选或 GOATS 候选查询。
- 数量待补充、无持仓错误、处理中回执原样透传；后端成功响应可回写订单号，但不会重建用户可见回执。

## 提交前回归修正

| 原失败组 | 数量 | 原因与修正 |
| --- | ---: | --- |
| 三组互换 render 卡片测试及 `tests/test_render.py` | 16 | 旧断言要求本地补字段、反算数量或缺结果时不回复，与 [Java 后端契约](../api-contracts/java-backend.md#3-互换操作swaporder) 冲突。保留原输入场景，验证回执逐字透传、缺少后端结果明确报错，以及原始 state 不被修改。 |
| JSONL/CSV/Excel 真实数据转换测试 | 2 | 平仓 fixture 已迁移为场景结构，旧的 16 行和 437 总行数断言过时。改为逐条核对源文件输入、用例 ID、步骤顺序、预期和响应断言；Excel 与 CSV 逐单元格比较，保留固定合成用例对格式和内容保真的覆盖。 |
| `test_probe_real_backend_e2e.py` CLI 测试 | 2 | Windows 子进程输出 UTF-8、父进程默认按 GBK 解码，导致读取线程抛 `UnicodeDecodeError`。显式统一子进程 `PYTHONIOENCODING` 与 `subprocess.run(encoding="utf-8")`。 |

本次全量基线和最终运行日志分别保存在执行环境的 `%TEMP%/aigc-pytest-initial.log` 与 `%TEMP%/aigc-pytest-final.log`，不提交到仓库。

## 外部待修与验收边界

Java 将无持仓表现为数量待补充的问题仍待后端处理；LangGraph 保留原始回执。报告 case 1 输入 3071 与生产预期 3100 的差异保留，不通过修改数量或预期使其通过。

以上验证证明解析、候选去噪、请求参数和回执传递符合本轮约定；没有把固定外部响应的回归测试视为真实持仓校验或真实交易成功。
