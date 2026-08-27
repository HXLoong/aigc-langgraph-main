# ADR 0015 · 一级路由：规则前置 + LLM 兜底

- 状态：已采纳（2026-08-28 起按 Dify DSL v2 重构为两层：规则层移植 + unknown LLM 兜底,见文末「DSL v2 迁移落地」）
- 日期：2026-05-10
- 修订：2026-08-27 深度改写为现状口径（wayfinder map #138 / 核查 #142）
- 作者：图灵科技 + Tony

## 上下文

主图入口需要把客户原话路由到 `product_type` 一级类目。复盘 golden 与 Java 后端约定后确认：ProductType 真值集 4 个（`swap` / `option` / `option_close` / `unknown`）；订单号 prefix 是业务硬约定（"订单号 over 关键词"，g029 案例）；强信号 case 占比高（立项时 30 条 golden 约 14 条——M2 立项时口径，golden 现已 535 条）；口语化 case 必须 LLM。

## 决策与落地现状（`app/nodes/intent_route.py`，实际为四层）

### 第 1 层 · 订单号正则（命中即返回）

| 正则 | → product_type |
|---|---|
| `H-\d{8}-[A-Z0-9]+` | swap |
| `OPT-\d{8}-[A-Z0-9]+` | option |
| `CO-\d{8}-[A-Z0-9]+` 或 `OPTG-[A-Z0-9]+` | option_close |
| `Q-\d{8}-[A-Z0-9]+` | option_close（落地后新增，与前四条同为业务硬约定，本次补录）|

### 第 1.5 层 · quote_content 产品标记（落地后新增层，原文未记录）

`_QUOTE_MARKERS`：引用卡片内容含 `-----场外期权询价详情-----` / `-----场外期权持仓详情-----` / `平仓申请已生成` / `-----互换订单参数-----` 等标记时直接定产品。**优先级高于关键词**——修复 swap-001 类多轮 bug（上轮 swap 订单卡 + 本轮"确认下单"被 option 关键词劫持）。

### 第 2 层 · 关键词优先级表

**以 ~~`app/prompts/router/keywords.yaml`~~（DSL v2 迁移后已删除,规则并入 `app/nodes/route_rules.py`）为准**（原为业务方单文件维护，启动时加载一次，命中即 break）。语义契约：优先级顺序 **option_close > option > swap**；表已从立项时 3 行示例扩张到 option_close 11 词 + 4 正则 / option 22 词 / swap 24 词 + 5 正则，ADR 不再复制具体词表。

### 第 3 层 · LLM 兜底

仅规则全部未命中时调用：

- ~~`load_prompt("router", "product_type")`~~（DSL v2 迁移后改为 `load_prompt("router", "unknown_intent")`,391 行,原 product_type.md 已删除）
- 入参：`raw_text` **+ `quote_content`**（拼接到 user 段，原文只写 raw_text，本次补录）
- `with_structured_output(ProductTypeOutput)`，Literal 四值
- ⚠️ **工厂选择偏离**（裁决 [#158](https://github.com/GZTL-AI/aigc-langgraph/issues/158)）：原决策"模型选 standard（按 [ADR 0010](./0010-llm-model-selection-rules.md)）"，代码实际用 `get_qwen_thinking()`（`product_type.md` 头部仍标 standard）。[ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) 后同模型无运行时后果，但按工厂分化模型时会静默跟错。

### 第 4 层 · unknown 兜底

LLM 判 unknown 或异常 → `product_type="unknown"` → 主图走 fallback render（友好回复 + trace，不进子图）。`ProductType` Literal 与 `app/graph/main.py` 的 `option_close` / `unknown` 分支均已落地。

### trace 决策来源（E3.4 错例追溯用，现为 4 种取值）

`rule:order_no→X` / `rule:quote_marker→X` / `rule:keyword[kw:词]→X` 或 `rule:keyword[re:正则]→X`（带命中 token）/ `llm→X`。

## 备选方案（历史论证）

- **纯 LLM 分类**：强信号 case 浪费调用（+200-500ms）；硬约定进 prompt 有 5-10% 违反概率；抖动破坏幂等。
- **纯规则**：处理不了口语化/歧义 case，unknown 比例过高。
- **规则前置 + LLM 兜底（已选）**：强信号 <1ms 硬约定 100% 一致；LLM 只处理真歧义。

## 后果（现状口径）

- 约一半流量省一次 LLM 调用，成本延迟双优；trace 可统计"规则 vs LLM"来源反哺关键词覆盖率。
- 新增 product 需改正则/yaml/LLM prompt 三处；订单号 prefix 变更走 ADR + 灰度（正则集中在 `intent_route.py` 一处）。
- 层次演进（quote_marker 层、Q- 正则）说明规则层会随错例分析持续生长——新增规则须同步本 ADR 或在 trace decision 中可辨识。
- ~~待修正：`app/prompts/router/product_type.md` 头部 model 标注~~（该文件已随 DSL v2 迁移删除,待修正项失效）。

## Related

- [ADR 0001](./0001-rewrite-app-with-harness-first.md) D6 · 本 ADR 是 intent_route 节点的精确化
- [ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) · LLM 兜底的模型实体现为 deepseek-v4-pro
- [ADR 0007](./0007-subgraph-vs-intent-scope-rule.md) · 未来扩展 product 时遵循
- [ADR 0011](./0011-split-option-intent-and-extraction.md) · 注意其子图 intent 层的确定性规则**不属于**本 ADR 覆盖面（本 ADR 只管一级 product 路由）

## DSL v2 迁移落地（2026-08-28 修订）

Dify 主干工作流 2026-08 版重写了一级路由,本 ADR 的分层结构随之重构(`feature/dify-dsl-migration` 分支):

- **规则层**:原「订单号正则 + quote_marker + keywords.yaml」三层合并为 `app/nodes/route_rules.py`——
  Dify「脚本判断期权、互换、其他查询指令」code 节点的 1:1 移植(订单号正则/口语化平仓/互换系统引用/
  下单特征/平仓查询关键词/关键词计数,含文件分类:全图片→互换-图片,全 Excel→互换-Excel)。
  keywords.yaml 与 quote_marker 层退役(引用卡片内的订单号由规则层合并扫描 quote_content 覆盖)。
- **语义变化**:`Q-` 单号归 **option**(期权开仓/报价单号,修正旧版误归 option_close 的 g029 类问题)。
- **LLM 兜底**:提示词换为 `app/prompts/router/unknown_intent.md`(Dify「unknown意图兜底识别」,391 行),
  输出 Literal[互换-文本/期权-文本/期权平仓-文本/unknown]。
- **前置分流**:路由之前主图先分流 fast_query(快速询价)与 existing_command(存量兼容),
  并由 `pre_route` 解析对手列表/引用候选标的(见 `app/graph/main.py`)。
- trace decision 取值变为 `rule→<DSL 标签>` / `llm→<DSL 标签>` 两种。
