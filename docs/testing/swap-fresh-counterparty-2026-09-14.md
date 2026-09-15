# 全新互换下单交易对手识别接入记录

实现日期：2026-09-14。对齐本仓 `dify/yaml/场外交易-test.yml` 中识别节点
`1786439000001` 和聚合节点 `1780652971845` 的全新下单交易对手逻辑。

## 接入范围

文本下单提取后，无有效引用时经过 `swap_recognize_fresh_counterparty` 再提交。
引用消息仍走 `swap_select_counterparty → swap_select_ticker`；图片、Excel 仍直接提交。
引用是否有效沿用原图判定，包括字面量 `null` 的大小写及两侧空格处理。

- 新增 `app/prompts/swap/fresh_counterparty.md`，system/user 模板逐字复制 Dify；
  通过 `load_prompt()` 加载，运行时替换原始 Dify 变量占位符。
- 复用 `get_qwen_complex()`；不调整模型配置。模型只接收 `raw_text` 和
  后端候选的 `[{sort, shortName}]` JSON，不接收订单提取结果、账户 ID 或 longName。
- `SwapFreshCounterpartyOutput` 的 `hasSignal`、`matches` 以及每个 match 的
  `shortName`、`evidence` 全部必填，禁止额外字段；不合法的结构化响应进入 `safe_node` 错误兜底。
- 将 Dify 的 `unique_fresh_counterparty()`、`apply_fresh_counterparty()` 移植到
  `aggregate.py`，增加原因返回值供 trace 使用。输入已经过结构化校验，不再需要 Dify
  聚合入口对 JSON 字符串的兼容解码。
- 删除 `swap_place_order` 中的 `_complete_counterparties()` 及其调用、旧 trace。
  未修改其他下单 prompt、标的规则、确认协议、对外 API 或 State 字段。

## 聚合规则及旧规则差异

名称、证据及已有订单名称按 Dify 聚合代码执行两侧空白清理。
所有召回项必须通过校验；任一候选外名称或无效证据会拒绝整个召回结果。
去重后仅有一个名称，且全部已有非空订单对手均与其一致时，才向整批订单写入完整名称。

| 场景 | 原尾部补全 | 本次 Dify 对齐行为 |
|---|---|---|
| 单笔订单、连续简称、持仓归属或首部名称 | 不补全 | 模型召回且代码校验通过后补全 |
| 纯数字名称，原文有“对手/账号”标签 | 可以补全 | Dify prompt 要求跳过纯数字候选；模型无信号时保持原值 |
| 同名但不同账户 ID，或重复候选缺少 ID | 视为账户歧义，不补全 | 仅按完整 `shortName` 去重；名称唯一时可补全 |
| 现有订单中任一对手与召回名称冲突 | 可保留冲突值同时补其他空值 | 整批保持原值，包括其他空值 |
| 多笔订单分别指定不同对手 | 保留已有名称 | 多名称召回或已有值冲突时，整批保持原值 |
| 同一简称命中多个完整候选 | 无专用简称召回 | 模型必须返回全部候选；代码判定歧义并保持原值 |
| 多个嵌套/重叠完整名称 | 旧匹配器可偏向最长完整命中 | 由 Dify prompt 召回候选，代码仅对返回名称判唯一性 |

纯数字排除、简称是否有辨识度及其是否属于证券/数量等语义判断归模型负责。
代码保留 Dify 的校验边界：不会另加数字过滤或要求 evidence 必须是 shortName 的子串，
也不会清空提取节点已经产出的数字名称。代码只校验 evidence 非空且逐字符存在于原文。

## Trace

节点成功或跳过时，`llm_output` 记录：

- `recall`：原始结构化召回结果；跳过请求时为 `null`。
- `adopted`：是否采用唯一名称，即使订单已全是该名称也为 `true`。
- `reason`：`applied`、`no_orders`、`no_candidates`、`no_signal`、`no_matches`、
  `name_outside_candidates`、`invalid_evidence`、`ambiguous_names` 或
  `existing_counterparty_conflict`。
- `shortname`：唯一校验结果；没有唯一结果时为 `null`。
- `affected_orders`：实际发生名称变化的订单下标，从 0 开始。

模型请求/结构化解析异常由既有 `safe_node` 记录 `error.node/type/message` 和错误 trace，
图转入 `swap_unknown`，不会调用提交接口。由此可区分模型无召回、代码拒绝与模型请求失败。

## 测试与验收边界

按 TDD 分段实现：先验证新节点缺失的 RED，再实现核心召回/聚合；
空输入跳过、图接线/失败阻断、移除旧补全分别验证 RED 后修到 GREEN。

节点测试验证完整名称/简称、单笔/多笔、重复账户、整批冲突、非法证据、必填约束、
无信号与空输入，以及原始 state 和其他订单字段保持不变。
图测试只模拟 LLM、下载和后端 HTTP，真实运行编译图、聚合、DTO 转换和提交代码。

“平仓价值精选全部持仓”验证完整对手名称及平仓比例送达提交接口。
`dev_case_7` 从当前业务验收文件读取原始 `send_text`，模拟两笔提取结果，验证
两笔均补全“聚鸣价值精选”，数量 30000/50000、首笔 24.6 限价及次笔 POV/9% 等字段保持不变。
业务验收文件及其中的 `response_contains` 原始 expected 未修改。

这些测试验证模拟模型输出后的行为及 Dify 资产对齐，不代表真实模型召回率或真实后端业务验收结果。

## 检查结果

| 检查 | 结果 |
|---|---|
| `pytest tests/subgraphs/swap/ -q --tb=line` | 448 passed |
| `pytest tests/ -q --tb=line` | 缺少 `tests/fixtures/golden_ticker_2026-05.jsonl`，在收集阶段中断 |
| `pytest tests/ -q --tb=line --continue-on-collection-errors` | 1721 passed、1 skipped、3 failed、1 collection error |
| `ruff check app/ tests/` | 通过 |
| `mypy app/` | 135 项既有错误；与 HEAD 独立快照按文件及错误内容比较，无新增、无减少 |
| `check_alert_threshold_consistency.py` | 通过 |
| `check_fixture_consistency.py` | 5 个旧路径 fixture 缺失 |
| `check_adr_refs.py` | 3 个 ADR 引用了缺失的 `tests/fixtures/golden.jsonl` |
| `git diff --check` | 通过 |

全量失败项：`TestRealRepo::test_current_adrs_clean`、`test_load_real_golden_jsonl`、
`TestGoldenRuleCoverage::test_rule_layer_precision`；收集错误位于
`tests/subgraphs/ticker/test_golden_ticker_fixture.py`。
这些检查仍引用 `tests/fixtures/` 旧路径，而当前仓库将相关数据放在 `tests/fixtures/old_typing/`。
本次未更改这些历史 fixture 路径或验收 expected。
上述 3 个失败和 1 个收集错误已在 HEAD 独立快照中再次复现，均由同样的旧路径缺失导致。

静态检查基线取自 `c680aeb` 的独立临时快照，包含 `app/`、`harness/` 及项目配置，
使用同一虚拟环境执行。新增节点、模型与移植函数未新增 mypy 错误；
新节点注册使用 `RunnableLambda` 适配现有异步装饰器与 LangGraph 类型签名。
