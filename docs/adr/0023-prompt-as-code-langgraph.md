# ADR 0023 · 提示词即代码：每个 LLM 节点声明一个 PromptSpec

- 状态：已采纳
- 日期：2026-09-15
- 关系：输出契约由 [ADR 0027](./0027-field-evidence-contract.md) 进一步收敛为"原文候选"；取代早期的 manifest 清单治理方案（原 0022 号，已删除）
- 作者：图灵科技 + Tony

## 背景

迁移完成后，提示词仍被当作"文本文件 + 一次 `load_prompt()` 调用"管理，与 LangGraph 高代码范式脱节，存在四类结构性问题：

1. **State 与提示词之间没有契约**：每个节点手拼 user 消息，读了哪些 State 字段只能靠读代码；改字段名不会让任何测试失败。
2. **输出契约有两份真源**：输出模型字段没有描述，提示词正文被迫维护整块 JSON 骨架补语义，两边必然漂移。
3. **规则文本反向长进 Python**：部分业务规则硬编码在拼装函数里，脱离评测与 review 视野。
4. **占位符渲染各自为政**：各节点私有 `str.replace`，无法校验一致性。

## 决策

### D1 · 每个 LLM 节点声明一个 `PromptSpec`（`app/prompts/spec.py`）

```python
SPEC = register(PromptSpec(
    category="option_close", name="holding_query",
    output_model=HoldingQueryParams,        # 输出契约唯一真源
    inputs=("raw_text", "option_counterparties"),  # 读取的 AgentState 字段
    user_builder=_build_user_message,       # State → user 消息（只拼变量）
))
messages, prompt_name = SPEC.build_messages(state)
result = await llm.with_structured_output(SPEC.output_model).ainvoke(messages)
```

构造期强制：`inputs` 必须是 `AgentState` 字段（改字段名在 import 阶段即报错）；登记的占位符必须真实存在于 `.md`。

### D2 · 输出契约只有一份：Pydantic `Field(description=)`

输出模型每个字段必须写 `description`（测试守护），语义经 function calling schema 下发；提示词正文不再维护 JSON 骨架 / 字段表，只保留业务规则。

### D3 · 共享积木（`app/prompts/blocks.py`）

历史格式化、对手列表、JSON 列表等拼装只定义一次，禁止在子图内复制。

### D4 · 规则文本只住在 `.md`，代码只供变量

user 消息中若含规则文本，写进 `.md` 的 `[user]` 段并用 `{{var}}` 占位，由 `render_user()` 渲染；禁止在代码里后置追加 system 文本（测试守护）。

### D5 · 瘦身原则

- 分三档处理：零风险（结构化输出下失效的 JSON 格式要求、未注入的悬空变量、重复陈述）直接删；低风险（few-shot 去重、闭集词表改为语义类加少量例子）经评测与抽样比对后删；涉及业务事实（产品名、名称词典、真实账户）的逐条请业务方确认。
- 错例回填的规则转为 `tests/fixtures/` 数据集用例，提示词只留通用原则；订单号提取、单位换算等确定性工作下沉到代码。

## 现状

全部业务 LLM 节点已迁移为 PromptSpec，数量以主图加载后的注册表 `all_specs()` 为准（截至 2026-09-22 共 14 个）。只做订单号提取的节点已改为确定性代码，不再是 LLM 节点。迁移批次记录见 [实施记录归档](../archive/history/adr-implementation-log-2026-09.md)。

## 备选方案

- **只做文件级治理，不引入 PromptSpec**：契约仍靠约定，JSON 骨架类冗余删不掉。
- **LangChain `ChatPromptTemplate`**：不校验 State 字段、不与输出模型绑定。
- **提示词整段写成 Python 字符串**：违反"提示词不硬编码在代码里"，业务方失去可读的 `.md` diff。

## 后果

- 正面：一个节点读哪些 State、输出什么，在一个对象上可见并被测试守护；复制代码归零；提示词正文显著缩短。
- 负面：新增 LLM 节点多写约 8 行声明；输出模型必须补齐描述。
- 未决：`description` 本身也计入 token，需要字符预算承载；`inputs` 目前只声明不强制（节点仍可读未声明字段）。
