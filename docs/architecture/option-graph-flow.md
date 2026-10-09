# 期权子图流程

代码真源：[app/subgraphs/option/graph.py](../../app/subgraphs/option/graph.py)。图按当前编译拓扑核对；产品子图内部流程单独成文。

`option_intent` 校验并读取主图联合结果，不调用模型。每轮只路由一个意图，可携带多笔订单。询价、补参、确认、撤单都使用 Java 现有 type；只读状态查询单独有限重试。确认只提交本次单号及显式增量，不重建引用卡片。

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	option_intent(option_intent<br/>读取联合结果，按意图分发)
	option_extract_inquiry(option_extract_inquiry<br/>普通询价内部图入口)
	option_extract_place(option_extract_place<br/>下单 / 补参：只提交稀疏参数)
	option_extract_confirm_place(option_extract_confirm_place<br/>确认下单：单号与显式增量)
	option_extract_cancel_place(option_extract_cancel_place<br/>取消下单：确定性单号提取)
	option_extract_cancel(option_extract_cancel<br/>撤单请求：确定性单号提取)
	option_extract_confirm_cancel(option_extract_confirm_cancel<br/>确认撤单：口令与引用校验)
	option_extract_query(option_extract_query<br/>订单状态查询，确定性提取)
	option_unknown(option_unknown<br/>兜底：未知指令引导文案)
	option_clean_request(option_clean_request<br/>清洗出站副本，不补默认值)
	option_submit(option_submit<br/>提交写请求，不自动重试)
	option_query_backend(option_query_backend<br/>只读查询，有限重试)
	__end__([<p>__end__</p>]):::last
	__start__ --> option_intent;
	option_clean_request -. &nbsp;done&nbsp; .-> __end__;
	option_clean_request -. &nbsp;query&nbsp; .-> option_query_backend;
	option_clean_request -. &nbsp;submit&nbsp; .-> option_submit;
	option_extract_cancel -. &nbsp;done&nbsp; .-> __end__;
	option_extract_cancel -. &nbsp;clean&nbsp; .-> option_clean_request;
	option_extract_cancel_place -. &nbsp;done&nbsp; .-> __end__;
	option_extract_cancel_place -. &nbsp;clean&nbsp; .-> option_clean_request;
	option_extract_confirm_cancel -. &nbsp;done&nbsp; .-> __end__;
	option_extract_confirm_cancel -. &nbsp;clean&nbsp; .-> option_clean_request;
	option_extract_confirm_place -. &nbsp;done&nbsp; .-> __end__;
	option_extract_confirm_place -. &nbsp;clean&nbsp; .-> option_clean_request;
	option_extract_inquiry -. &nbsp;done&nbsp; .-> __end__;
	option_extract_inquiry -. &nbsp;clean&nbsp; .-> option_clean_request;
	option_extract_place -. &nbsp;done&nbsp; .-> __end__;
	option_extract_place -. &nbsp;clean&nbsp; .-> option_clean_request;
	option_extract_query -. &nbsp;done&nbsp; .-> __end__;
	option_extract_query -. &nbsp;clean&nbsp; .-> option_clean_request;
	option_intent -.-> option_extract_cancel;
	option_intent -.-> option_extract_cancel_place;
	option_intent -.-> option_extract_confirm_cancel;
	option_intent -.-> option_extract_confirm_place;
	option_intent -.-> option_extract_inquiry;
	option_intent -.-> option_extract_place;
	option_intent -.-> option_extract_query;
	option_intent -.-> option_unknown;
	option_unknown -. &nbsp;done&nbsp; .-> __end__;
	option_unknown -. &nbsp;clean&nbsp; .-> option_clean_request;
	option_query_backend --> __end__;
	option_submit --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```

## 独立流程文档

- [普通询价内部图](./option-inquiry-flow.md)

返回[主图](./main-graph-flow.md)。

写入 `state.error` 的错误停止后续业务提交；参数字符串 JSON 容错按 ADR 0027 D3 处理。错误信息、节点与真实回执留在审计输出。LLM 请求预算适用于整次调用，不因进入子图重置。


## Java 请求清洗与提交

所有动作节点完成本次参数、身份与选择准备后，统一进入 `option_clean_request`。原解析和字段账本保留，清洗生成独立请求副本；不兼容字段省略，0/false 保留，不补业务默认值。规则与 Dify 参数字符串 JSON 回退见 [ADR 0027](../adr/0027-field-evidence-contract.md)。

清洗成功后，写类及 JSON 回退请求进入 `option_submit`，仅独立只读请求进入可有限重试的 `option_query_backend`。参数准备和清洗节点不访问 Java、不调用模型。`backend_request` 记录实际 DTO 请求，`cleaning_records` 记录省略/转换，API 与 Harness 参数信封读取 `submitted_params` 投影。清洗后不会从原字段锁账本重新补回脏值。
