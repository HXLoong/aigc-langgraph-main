# 主图流程

代码真源：[app/graph/main.py](../../app/graph/main.py)。图按当前编译拓扑核对；产品子图内部流程单独成文。

一次合法 HTTP 调用拥有独立模型额度；规则选择期权、互换、平仓或跨产品 PromptSpec，只有 `parse_instruction` 请求模型。`prepare_parse_context` 的后端只读重试发生在模型之前；模型失败不重试，直接 cascade。图片与含图片输入在入口拒绝；Excel 全量读入后一次解析。快速询价与存量分支沿既有外部工具执行。`entry_route` 输出 `entry_branch`；快速入口由 `fast_query="1"` 明确选择，并确定性给出 `option/new_inquiry`，与 `at_bot` 独立，不调用普通联合解析器。

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	ingest(ingest<br/>入口薄层，重置本轮字段)
	prepare_input(prepare_input<br/>附件边界：图片拒绝，Excel 读入)
	entry_route(entry_route<br/>入口分流：快速询价 / 存量指令 / 普通)
	quick_inquiry(quick_inquiry<br/>快速询价：GOATS 解析后提交询价)
	existing_command_query(existing_command_query<br/>存量指令查询，恒回静默哨兵)
	pre_route(pre_route<br/>前置提取：对手列表 / 引用候选标的)
	intent_route(intent_route<br/>规则产品提示，不调模型)
	parse_instruction(parse_instruction<br/>唯一联合解析：本轮模型请求点)
	prepare_parse_context(prepare_parse_context<br/>模型前只读上下文)
	swap(swap<br/>互换子图)
	option(option<br/>期权子图)
	option_close(option_close<br/>期权平仓子图)
	fallback(fallback<br/>cascade 统一兜底)
	render(render<br/>回复渲染)
	persist_intent(persist_intent<br/>消息意图写回 Java)
	persist(persist<br/>本轮 trace 落库)
	remember_confirmed_params(remember_confirmed_params<br/>记忆本轮已确认参数)
	record_history(record_history<br/>写对话历史)
	__end__([<p>__end__</p>]):::last
	__start__ --> ingest;
	entry_route -.-> existing_command_query;
	entry_route -.-> pre_route;
	entry_route -.-> quick_inquiry;
	existing_command_query --> render;
	fallback --> persist_intent;
	ingest -.-> prepare_input;
	ingest -.-> render;
	intent_route --> prepare_parse_context;
	option --> persist_intent;
	option_close --> persist_intent;
	parse_instruction -.-> fallback;
	parse_instruction -.-> option;
	parse_instruction -.-> option_close;
	parse_instruction -.-> swap;
	persist_intent --> render;
	pre_route --> intent_route;
	prepare_input -.-> entry_route;
	prepare_input -.-> persist_intent;
	prepare_input -.-> render;
	prepare_parse_context --> parse_instruction;
	quick_inquiry --> render;
	record_history --> persist;
	remember_confirmed_params --> record_history;
	render --> remember_confirmed_params;
	swap --> persist_intent;
	persist --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```

## 独立流程文档

- [期权子图](./option-graph-flow.md)
- [互换子图](./swap-graph-flow.md)
- [期权平仓子图](./close-graph-flow.md)
- [普通期权询价内部图](./option-inquiry-flow.md)
- [互换下单准备内部图](./swap-place-flow.md)
- [平仓下单内部图](./close-place-flow.md)
- [节点调试执行图](./node-execution-flow.md)


写入 `state.error` 的错误停止后续业务提交；参数字符串 JSON 容错按 ADR 0027 D3 处理。错误信息、节点与真实回执留在审计输出。LLM 请求预算适用于整次调用，不因进入子图重置。
