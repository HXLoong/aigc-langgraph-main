# ADR 0023 · 提示词即代码：按 LangGraph 高代码范式管理提示词（PromptSpec）

- 状态：**已采纳**（2026-09-15；2026-09-17 第二 / 三批迁移完成共 28 个 LLM 节点，同日 D 批去 LLM 化再移除 option 4 + close 4 个——现役注册 20 个，迁移路径见 D5）
- 日期：2026-09-15
- 起源：ADR 0022 落地后，用户要求"提示词管理需要考虑 LangGraph 高代码实现、使用 AgentState 等内容，按 LangGraph 高代码范式重新评估"；评估过程与证据见 [docs/prompt-maintainability-assessment.md 第十节](../prompt-maintainability-assessment.md)
- 修订：[ADR 0022](./0022-prompt-governance-after-code-migration.md) D5（`.md` 契约从"system 段 + 手拼 user"收敛为 PromptSpec 声明）、[ADR 0001 D5](./0001-rewrite-app-with-harness-first.md)（改写决定登记）；2026-09-17：第二 / 三批迁移完成（ADR 0022 ticker 未决项同步关闭）
- 作者：图灵科技 + Tony

## 上下文

ADR 0022 解决的是提示词**资产**的治理（真源、三态、灰度漂移、上游告警）。但它仍把提示词当作"文本文件 + 一个 `load_prompt()` 调用"来管理，与 LangGraph 高代码范式脱节，评估时核实到四类结构性问题：

1. **AgentState 与提示词之间没有契约**。每个 LLM 节点各自手拼 user 消息：代码迁移完成时 `app/subgraphs` 下有 19 份 `_build_user_message`、9 份逐字相同的 `_format_history`、3 份 `_format_*_list`。一个节点读了 AgentState 的哪些字段只能靠读函数体；改 `AgentState` 字段名不会让任何东西变红。
2. **输出契约有两份真源**。所有节点都走 `with_structured_output(PydanticModel)`（function calling 适配，ADR 0020），但 24 个输出模型的字段语义全部写成 `#:` 注释，`Field(description=)` 为零——function calling schema 下发给模型的只有字段名和类型，于是提示词正文被迫维护整块 JSON 骨架 / 字段表（option 7 个 extract 各一份）来补语义。两份真源必然漂移（评估发现 `hasFastExecutionIntent` 在 `.md` 里有规则、在 schema 里被丢弃）。
3. **规则文本反向长进 Python**。`swap/place_order.py` 的 user 拼装函数硬编码了"核心护栏 6"与"hasFastExecutionIntent 最终判定"两段业务规则（C-25）；`close/intent.py` 在代码里后置追加 `_JSON_OUTPUT_INSTRUCTION`（C-18）。两者都违反"提示词不硬编码在代码里"，且不在任何 eval 门 / manifest changelog 的视野内。
4. **占位符渲染是各节点私有的 `str.replace`**。`holding_query` / `ticker/tools` / `multimodal` 各自维护常量与替换逻辑，manifest `injects` 只能靠人工登记与代码保持一致，lint 无法核对"登记的注入代码是否真的做了"。

LangGraph 高代码范式的要点恰好对应这四点：**State 是显式类型化的输入契约、Pydantic 是显式类型化的输出契约、节点是纯函数、可观测靠 trace 而非文本**。提示词管理应该同样被声明为代码对象，而不是文本 + 约定。

## 决策

### D1 · 每个 LLM 节点声明一个 `PromptSpec`（`app/prompts/spec.py`）

```python
SPEC = register(PromptSpec(
    category="option_close",
    name="holding_query",
    output_model=HoldingQueryParams,                       # 输出契约唯一真源
    inputs=("raw_text", "option_counterparties"),          # 读取的 AgentState 字段
    user_builder=_build_user_message,                      # AgentState → user 消息（只拼变量）
    injects={"{{#1772773805306.optionListStr#}}":          # system 占位符 → 渲染器
             lambda s: blocks.json_list(s.get("option_counterparties"))},
    gray=False,                                            # True → 走 _versions.yaml 灰度
))

messages, prompt_name = SPEC.build_messages(state)
result = await llm.with_structured_output(SPEC.output_model).ainvoke(messages)
```

不变量（构造期 / 测试期强制）：

- `inputs ⊆ get_type_hints(AgentState)`：构造时校验，改 State 字段名立刻在 import 阶段报错
- `render_system` 对 `injects` 中登记但 `.md` 里不存在的占位符抛错：manifest / spec / `.md` 三者不可能悄悄不一致
- 注册表 `all_specs()` 与 `_manifest.yaml` 交叉核对（`tests/test_prompt_spec.py`）：`output_model` / `injects` 必须相等；`scripts/prompt_inventory.py --check` 把 `PromptSpec(category=, name=)` 视为与 `load_prompt` 等价的加载点（2026-09-16：manifest 与 `prompt_inventory` 已随 ADR 0022 废弃移除，交叉核对以注册表测试为准）

### D2 · 输出契约只有一份：Pydantic `Field(description=)`

- 输出模型每个字段必须有 `description`（`tests/test_prompt_spec.py::test_output_model_fields_have_description` 守护已注册的 spec），语义经 function calling schema 下发
- 提示词正文**不再**维护 JSON 骨架 / 字段表 / "必须输出如下 JSON 结构"；保留的是业务规则（何时填、如何换算）。本次删除 option 7 个 extract 的 JSON 骨架与 close intent 的代码内追加指令
- 字段级取值规则（枚举、格式）优先写进 `description`，跨字段规则留在 `.md` system 段

### D3 · 共享积木替代各节点复制（`app/prompts/blocks.py`）

`format_history` / `shortnames` / `json_list` / `kv_block` 等纯函数只定义一次；节点私有的 `_format_history` 全部删除（9 → 0）。新积木进 `blocks.py` 并带单测，不允许在子图内再复制一份。

### D4 · 规则文本只能住在 `.md`，代码只供变量

- user 消息中如有规则文本（而不只是变量拼接），必须写进 `.md` 的 `[user]` 段并用 `{{var}}` 占位，节点用 `Prompt.render_user(**vars)` 渲染（先例：`swap/place_order.md`）。`[user]` 段由此从"Dify 参照"恢复为运行时契约——但仅对声明了它的节点
- 禁止在代码里后置追加 system 文本（含"格式指令"）；测试 `test_system_has_no_code_appended_format_instruction` 守护

### D5 · 迁移路径（不一次性全迁）

| 批次 | 节点 | 说明 |
|---|---|---|
| 试点（本 ADR 已落地） | option intent + 7 extract、option_close intent / holding_query、swap intent / place_order | 12 个，覆盖三种形态：纯变量 user、带注入、带灰度与 `[user]` 模板 |
| 第二批 | close 5 个（place_close / cancel_close / confirm_close / confirm_cancel / query_status）、swap select_counterparty / select_ticker | user 拼装同构，机械迁移；同时给 `close/models.py` 剩余模型补 description。**已完成（2026-09-17），含 swap/fresh_counterparty** |
| 第三批 | swap multimodal（image / excel / ocr，含 v2 灰度位）、ticker 4 个（tools.py helper 形态）、router unknown_intent | multimodal 输入含图片 / 文件，`user_builder` 需扩展为多模态消息；ticker 先完成 ADR 0022 未决项"转 structured output"再迁。**已完成（2026-09-17）**：multimodal 3 个（image_ocr 为 system 渲染 + 运行期 user 拼接）、ticker 4 个输出契约见 ~~`app/subgraphs/ticker/models.py`~~、router unknown_intent |

**2026-09-17 D 批（去 LLM 化，非 PromptSpec 迁移）**：close 4 个 CO- 节点（cancel_close / confirm_close / confirm_cancel / query_status → `close/order_id.py`）与 option 4 个 Q- 节点（extract_cancel / extract_cancel_place / extract_confirm_cancel / extract_query → `option/order_id.py`）已转确定性提取，8 个对应提示词文件同批删除；注册表 28 → 20。

每批的门：对应子图测试 GREEN + eval PASS ≥ 迁移前（迁移本身不改 LLM 输入文本，eval 应零变化；原 `prompt_inventory --strict` 门槛已随 ADR 0022 废弃移除，2026-09-16）。

## 备选方案

- **只做 ADR 0022，不引入 PromptSpec**：资产治理到位但契约仍靠约定；每次改 AgentState / 输出模型都要人工翻 `.md`，客户反馈的"冗余"里有一半（JSON 骨架 / 字段表）根本删不掉
- **LangChain `ChatPromptTemplate` + `MessagesPlaceholder`**：能表达 user 模板，但不校验 AgentState 字段、不与 Pydantic 输出模型绑定、不与 manifest 交叉核对；且把 Dify `{{#node.var#}}` 语法再翻译一层。PromptSpec 内部仍用 `load_prompt` / `render_user`，不排斥后续在 `build_messages` 内换成 ChatPromptTemplate
- **把提示词整段写成 Python 字符串**（"完全代码化"）：违反核心原则 1，也让业务方失去可读的 `.md` diff

## 后果

- 正面：一个节点读哪些 State、输出什么、注入什么，在一个对象上可见并被测试守护；`_format_history` 类复制归零；JSON 骨架可删（option 7 文件 system 合计减少约 6K 字符）；改 AgentState 字段名 import 即红
- 负面：新增 LLM 节点多写一个 `PromptSpec`（约 8 行）；输出模型必须补 description（本次 69 个字段）；灰度节点的 `prompt_name` 由 `build_messages` 返回，节点须继续写入 trace
- 未决：`description` 的字符预算（function calling schema 也计 tokens，曾挂账给 ~~`prompt_inventory`~~，该工具已随 ADR 0022 废弃移除、需另找承载）；`inputs` 目前只声明不强制（节点仍可读未声明字段），是否在测试里用受限 State 代理强制。第二 / 三批迁移已于 2026-09-17 完成（真后端 eval 门待跑）

## 关联

- [ADR 0022](./0022-prompt-governance-after-code-migration.md) · 资产治理（真源 / 三态 / 上游告警）→ 本 ADR 补契约层
- [ADR 0003](./0003-prompt-versioning-by-file-coexistence.md) · `_versions.yaml` 灰度 → `PromptSpec.gray`
- [ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) · structured output 走 function calling → D2 的前提
- `docs/prompt-maintainability-assessment.md` 第十节 · 评估证据与量化
- `.claude/rules/prompt-management.md`、`app/prompts/CLAUDE.md` · 操作口径
