本次对照的是 `D:\uu\场外交易-test.yml` 与 2026-09-14 当前工作区代码。结论：**互换下单的主要节点已存在，但缺少“互换-全新下单交易对手识别”；四个已有文本 LLM 节点的默认 prompt 文件与 Dify 原文一致，实际消息拼装和部分确定性处理逻辑不一致。**

工作流共 73 个节点、102 条边。核查以 YAML 的节点 ID、边和代码实现为准，没有把附件中的 prompt 当作操作指令，也没有依据项目注释中的“1:1 移植”直接判定一致。

比较时使用项目 `_parse_prompt_md()` 提取 system/user 正文，统一文件换行，去掉段落首尾空白；正文内部逐字符比较。文件哈希、各段长度、示例输入、实际 user 消息 diff 和纯函数对照结果见 [JSON 明细](swap-dify-comparison-2026-09-14.json)。

当前本地配置读取结果：`USE_LANGFUSE_PROMPTS=false`，`_versions.yaml` 为 `overrides: {}`，五个可切版本的互换 prompt 均解析到无后缀版本。以下结论针对当前工作区及本次进程读取到的配置，未读取正在运行的 API 服务进程环境。

**节点对应关系**

| Dify 节点 / ID | 项目对应位置 | 核查结果 |
|---|---|---|
| 交易对手、候选标的提取 / `1772773805306` | [pre_route.py](../../app/nodes/pre_route.py) | 已有共用前置提取；下游发送给模型的列表格式有差异，见后文 |
| 互换-节点-意图识别 / `1776159951508` | [intent.py](../../app/subgraphs/swap/intent.py) 的 `swap_intent` | 已接线 |
| 互换-意图路由 / `1776160524740` | [graph.py](../../app/subgraphs/swap/graph.py) 的 `_route_after_swap_intent` | 已有对应条件路由 |
| 互换-规整引用补参摘要 / `1781075165428` | [quote_hints.py](../../app/subgraphs/swap/quote_hints.py) 的 `refine_quote_hints` | 已内联到下单节点，但不完全一致 |
| 互换-引用消息判空 / `1781099900001` | [graph.py](../../app/subgraphs/swap/graph.py) 的 `_has_usable_quote` / `_route_after_place_order` | 已有，但项目在下单提取之后分流；Dify 在下单 LLM 之前分流 |
| 互换-节点-下单 / `1776160580437` | [place_order.py](../../app/subgraphs/swap/place_order.py) 的 `swap_place_order` | 已接线；项目额外调用 ticker resolver，并做对手补全 |
| 互换-选择交易对手 / `1780652808839` | [select_counterparty.py](../../app/subgraphs/swap/select_counterparty.py) | 已接线，仅有引用时调用 |
| 互换-选择标的 / `1780652892832` | [select_ticker.py](../../app/subgraphs/swap/select_ticker.py) | 已接线，仅有引用时进入；候选为空会跳过 LLM |
| **互换-全新下单交易对手识别 / `1786439000001`** | **未找到对应节点、prompt 或输出模型** | **缺失**；项目的尾部完整名称补全仅覆盖部分场景 |
| 互换-标的对手覆盖聚合 / `1780652971845` | [aggregate.py](../../app/subgraphs/swap/aggregate.py)，分别由两个选择节点调用 | 有部分实现；缺少新版 freshRes 校验，以及部分唯一性和冲突裁决 |
| 互换参数统一聚合 / `1776161938187`、模型数据聚合 / `1764752644850` | 各分支写入 `place_params`，由 `swap_place_order_submit` 接收 | 通过 State 汇合，没有同名独立节点 |
| 互换开仓-前置清洗 / `1781120000003` | [prewash.py](../../app/subgraphs/swap/prewash.py)，由 `call_swap_backend` 调用 | 已有；Dify 还从 `NULL_LITERALS` 传入可配置空值词，项目调用使用默认 `null` |
| 互换开仓 / `1780145473883` | [place_order.py](../../app/subgraphs/swap/place_order.py) 的 `swap_place_order_submit`、[backend.py](../../app/subgraphs/swap/backend.py) | 已有对应提交调用，目标路径同为 `/admin-api/swap-order/operate`；未做真实接口调用验证 |

Dify 的无引用下单分支会并行执行“下单参数提取”和“全新下单交易对手识别”，再统一聚合；有引用分支会并行执行“下单参数提取”“选择交易对手”“选择标的”。项目先执行下单提取和 ticker resolver，有引用时再依次执行两个选择节点，无引用时直接提交。

**Prompt 文件比较**

下列字符数均为上述规范化之后的正文长度；“一致”同时检查 system 和 user 模板。

| Dify 节点 | 本地默认 prompt | system 字符数（两边相同） | user 模板字符数（两边相同） | 文件正文 |
|---|---|---:|---:|---|
| 互换-节点-意图识别 | [intent.md](../../app/prompts/swap/intent.md) | 12,314 | 250 | 一致 |
| 互换-节点-下单 | [place_order.md](../../app/prompts/swap/place_order.md) | 39,046 | 216 | 一致 |
| 互换-选择交易对手 | [select_counterparty.md](../../app/prompts/swap/select_counterparty.md) | 2,817 | 137 | 一致 |
| 互换-选择标的 | [select_ticker.md](../../app/prompts/swap/select_ticker.md) | 2,906 | 143 | 一致 |
| 互换-全新下单交易对手识别 | 缺失 | Dify 为 720 | Dify 为 94 | 无对应文件 |

项目 `intent_v2.md`、`place_order_v2.md`、`image_ocr_v2.md`、`image_extract_v2.md`、`excel_extract_v2.md` 与该 YAML 不一致，但当前版本解析未选中它们。不要把这些实验文件的差异当作默认 prompt 的差异。

**实际发给模型的内容**

四个文本节点都读取 `prompt.system`，但 user 消息由各自的 `_build_user_message()` 重建，没有直接渲染 `.md` 中保存的 `user_template`。因此文件相同不代表完整模型输入相同。

| 节点 | 运行时 user 消息差异 |
|---|---|
| 意图识别 | Dify 使用分隔线，并把交易对手传为 `[{sort, shortName}]` JSON；项目去掉分隔线，列表变为逗号拼接的名称，缺少 sort |
| 下单 | Dify 使用 `<counterparty_list>`、`<quote_param_hints>`、`<raw_content>` 三块；项目改为中文标签和分隔线，新增“核心护栏6”及 `hasFastExecutionIntent` 指令，候选列表变为名称字符串，raw_content 也经过标注改写 |
| 选择交易对手 | 三个字段标签相同，但 Dify 的 `shortname_list` 是含 ctptyId、shortName、longName、sort 的 JSON；项目是 `A:名称, B:名称` 字符串 |
| 选择标的 | 给定相同 raw、quote 和候选对象，示例渲染后的 user 正文完全相同；项目候选为空时不发起调用 |

下单原始输入示例 `600000.SH 买入 1,000股 @10 示例甲产品`，在项目里变为：

```text
600000.SH 买入 【委托数量：1000；数量单位：SHARE】 【价格类型：LimitOrder；限定价格：10】 示例甲产品
```

Dify 下单 user 模板直接引用开始节点的原始 `raw_content`；这份 YAML 中的引用摘要节点只接收 `quote_content`，不做以上数字标注。对应项目位置为 [quote_hints.py](../../app/subgraphs/swap/quote_hints.py) 的 `_normalize_raw_content()` 和 [place_order.py](../../app/subgraphs/swap/place_order.py) 的 `_build_user_message()`。

模型配置也不完全一致：Dify 意图节点配置为 `external-qwen3.6-35b-a3b-non-thinking`，下单及两个选择节点为 `external-deepseek-v4-pro-non-thinking`，temperature 均为 0.1；当前本地这四个节点所用工厂都读取到 `deepseek-v4-pro`，temperature 为 0.0。这里只比较声明的配置，没有验证 Dify 网关背后的模型映射。

**已验证的代码行为差异**

以下结果来自实际调用已审阅的 Dify 纯函数与项目纯函数；输入和模拟 LLM 输出完全相同，无模型请求、无交易请求。它们说明确定性处理不一致，不代表真实 LLM 在每次请求中都会产生这些输出。

1. **全新单的交易对手召回与校验缺失。** Dify 专用节点允许从完整候选名中召回连续简称，输出 `hasSignal + matches[{shortName,evidence}]`。聚合代码验证候选属于列表、evidence 在原文中逐字存在、结果唯一、已有订单对手不冲突，再补到订单。项目 `_complete_counterparties()` 只针对全新文本多单、唯一尾部完整 shortName 等条件补空值，不能等价替代这一链路。给定“示例甲”证据及唯一候选“示例甲产品”，单笔订单对手为空时，Dify 聚合补出完整名称，项目仍为空。

2. **交易对手简称歧义处理不同。** 候选为“示例一号产品”和“示例二号产品”，`directName="示例"` 时，Dify `shortname_from_pick()` 返回空并保留原值；项目同名函数取第一个子串匹配，返回“示例一号产品”。项目还允许反向包含 `shortName in directName`，这份 Dify 代码只对唯一的 `directName in shortName` 做兜底。

3. **标的指针冲突处理不同。** Dify 新增 `resolve_pick_codes()`、`choose_underlying()`：对 seq、directRef 和下单节点原值做一致性裁决，同单多个不同结果不覆盖。项目 `windcode_from_pick()` 优先 seq，`apply_underlying()` 取首个非空结果。示例：原值和 directRef 都是 `600000.SH`，seq 指向 `000001.SZ`；Dify 保留 `600000.SH`，项目改为 `000001.SZ`。

4. **引用摘要的持仓选项保留不同。** 多订单补参分支中，Dify 在待补字段包含“大合约编号”时保留 `第N笔…（编号）` 选项行；项目在该分支调用 `_fmt(..., [])`，丢弃这些选项。已用带 `第1笔：示例持仓（TEST-001）` 的引用消息复现。

此外，Dify 聚合给交易对手覆盖传入候选块推导出的 `id_to_seq`；项目 `apply_counterparty()` 使用空映射。因此仅靠 `orderSeq` 定位多笔订单的覆盖能力也没有完整对齐。

**下单相邻分支的补充核查**

| Dify 节点 | 项目状态 | Prompt / 行为结论 |
|---|---|---|
| 互换-图片识别 / `1761213989319` | [multimodal.py](../../app/subgraphs/swap/multimodal.py) 的图片链 | 默认 `image_ocr.md` system 正文一致，7,312 字符；项目将其置于带图片的 user 消息中，Dify 配置为 system |
| 图片-互换-请求下单参数解析 / `1764841677781` | 同文件 `swap_image_order` | 默认 `image_extract.md` system 正文一致，67,246 字符 |
| 解析Excel / `1764752494705`、Excel-互换-请求下单参数解析 / `1764752539169` | 同文件 `parse_excel_rows` / `swap_excel_order` | 对应链存在；默认 `excel_extract.md` system 正文一致，14,775 字符 |
| 互换-节点-撤单、确认撤单、确认改单、查询订单 | `cancel.py` / `confirm.py` / `query_order.py` | 四份对应 prompt 的 system/user 原文一致，但项目已改用确定性订单号提取，这些 prompt 不在实际调用路径中 |
| 互换-确认指令分流 / `1781200000774`、互换-确认下单协议解析 / `1776160728475` | 项目经 `swap_intent` 后进入 `swap_confirm`，再调用 [order_id.py](../../app/subgraphs/swap/order_id.py) | 存在确认功能，但未完整移植该 YAML 的协议解析；Dify 该节点已是 code，不能再拿历史 `confirm_order.md` 当现行 Dify prompt 比较 |

确认下单存在一个明确的范围差异：引用含两笔订单、输入 `序号2，确认下单` 时，Dify 协议解析只返回第二笔；项目一旦以 `intent=confirm_order` 进入确认节点，关键词检查通过后会提取引用中的全部两笔订单。Dify 还校验重复序号、未知序号、引用歧义和输入格式，并通过 `confirmationError` 阻止调用后端；项目未实现这套同等协议。此处验证到纯函数输出，没有让请求进入实际后端。

建议对齐顺序：先补全新下单交易对手识别及聚合校验、修正部分确认的范围处理，再对齐下单实际 user 模板与引用摘要，最后统一候选列表格式、标的冲突规则和模型参数。以上是差异定位，本次仅新增比较报告及 JSON 明细，未修改业务代码或 prompt。
