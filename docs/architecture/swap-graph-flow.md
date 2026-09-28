# 互换子图流程

代码真源：[app/subgraphs/swap/graph.py](../../app/subgraphs/swap/graph.py)。图按当前编译拓扑核对；产品子图内部流程单独成文。

`swap_intent` 读取联合结果；新单和补参共用 `place_order_request`。候选指针来自同一次模型，`swap_apply_picks` 确定性检查原文、订单和授权候选范围，再一次提交 Java。没有独立候选 LLM、对手 LLM 或图片节点。

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	swap_intent(swap_intent)
	swap_place_order(swap_place_order)
	swap_apply_picks(swap_apply_picks)
	swap_place_order_submit(swap_place_order_submit)
	swap_confirm(swap_confirm)
	swap_cancel(swap_cancel)
	swap_query_order(swap_query_order)
	swap_unknown(swap_unknown)
	swap_clean_request(swap_clean_request)
	swap_submit(swap_submit)
	swap_query_backend(swap_query_backend)
	__end__([<p>__end__</p>]):::last
	__start__ --> swap_intent;
	swap_apply_picks -.-> swap_place_order_submit;
	swap_apply_picks -.-> swap_unknown;
	swap_cancel -. &nbsp;done&nbsp; .-> __end__;
	swap_cancel -. &nbsp;clean&nbsp; .-> swap_clean_request;
	swap_clean_request -. &nbsp;done&nbsp; .-> __end__;
	swap_clean_request -. &nbsp;query&nbsp; .-> swap_query_backend;
	swap_clean_request -. &nbsp;submit&nbsp; .-> swap_submit;
	swap_confirm -. &nbsp;done&nbsp; .-> __end__;
	swap_confirm -. &nbsp;clean&nbsp; .-> swap_clean_request;
	swap_intent -.-> swap_cancel;
	swap_intent -.-> swap_confirm;
	swap_intent -.-> swap_place_order;
	swap_intent -.-> swap_query_order;
	swap_intent -.-> swap_unknown;
	swap_place_order -.-> swap_apply_picks;
	swap_place_order -.-> swap_unknown;
	swap_place_order_submit -. &nbsp;done&nbsp; .-> __end__;
	swap_place_order_submit -. &nbsp;clean&nbsp; .-> swap_clean_request;
	swap_query_order -. &nbsp;done&nbsp; .-> __end__;
	swap_query_order -. &nbsp;clean&nbsp; .-> swap_clean_request;
	swap_unknown -. &nbsp;done&nbsp; .-> __end__;
	swap_unknown -. &nbsp;clean&nbsp; .-> swap_clean_request;
	swap_query_backend --> __end__;
	swap_submit --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```

## 独立流程文档

- [下单准备内部图](./swap-place-flow.md)

返回[主图](./main-graph-flow.md)。

写入 `state.error` 的错误停止后续业务提交；参数字符串 JSON 容错按 ADR 0027 D3 处理。错误信息、节点与真实回执留在审计输出。LLM 请求预算适用于整次调用，不因进入子图重置。


## Java 请求清洗与提交

所有动作节点完成本次参数、身份与选择准备后，统一进入 `swap_clean_request`。原解析和字段账本保留，清洗生成独立请求副本；不兼容字段省略，0/false 保留，不补业务默认值。规则与 Dify 参数字符串 JSON 回退见 [ADR 0027](../adr/0027-field-evidence-contract.md)。

清洗成功后，写类及 JSON 回退请求进入 `swap_submit`，仅独立只读请求进入可有限重试的 `swap_query_backend`。参数准备和清洗节点不访问 Java、不调用模型。`backend_request` 记录实际 DTO 请求，`cleaning_records` 记录省略/转换，API 与 Harness 参数信封读取 `submitted_params` 投影。清洗后不会从原字段锁账本重新补回脏值。
