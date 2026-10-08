# 期权平仓子图流程

代码真源：[app/subgraphs/close/graph.py](../../app/subgraphs/close/graph.py)。图按当前编译拓扑核对；产品子图内部流程单独成文。

`close_intent` 读取联合结果，不调用模型。持仓查询和订单状态查询可独立重试；交易请求不重试。平仓、撤单、确认使用本次输入与用户引用，历史订单不能替代当前选择。

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	close_intent(close_intent<br/>读取联合结果，按意图分发)
	close_holding_query(close_holding_query<br/>持仓查询：只装配本次过滤条件)
	close_place_close(close_place_close<br/>平仓下单内部图入口)
	close_confirm_close(close_confirm_close<br/>确认平仓：口令与订单范围校验)
	close_cancel_close(close_cancel_close<br/>撤单申请：确定性单号提取)
	close_confirm_cancel(close_confirm_cancel<br/>确认撤单：口令与订单范围校验)
	close_query_status(close_query_status<br/>订单状态查询，确定性提取)
	close_unknown(close_unknown<br/>兜底：未知指令引导文案)
	close_clean_request(close_clean_request<br/>清洗出站副本，不补默认值)
	close_submit(close_submit<br/>提交写请求，不自动重试)
	close_query_backend(close_query_backend<br/>只读查询，有限重试)
	__end__([<p>__end__</p>]):::last
	__start__ --> close_intent;
	close_cancel_close -. &nbsp;done&nbsp; .-> __end__;
	close_cancel_close -. &nbsp;clean&nbsp; .-> close_clean_request;
	close_clean_request -. &nbsp;done&nbsp; .-> __end__;
	close_clean_request -. &nbsp;query&nbsp; .-> close_query_backend;
	close_clean_request -. &nbsp;submit&nbsp; .-> close_submit;
	close_confirm_cancel -. &nbsp;done&nbsp; .-> __end__;
	close_confirm_cancel -. &nbsp;clean&nbsp; .-> close_clean_request;
	close_confirm_close -. &nbsp;done&nbsp; .-> __end__;
	close_confirm_close -. &nbsp;clean&nbsp; .-> close_clean_request;
	close_holding_query -. &nbsp;done&nbsp; .-> __end__;
	close_holding_query -. &nbsp;clean&nbsp; .-> close_clean_request;
	close_intent -.-> close_cancel_close;
	close_intent -.-> close_confirm_cancel;
	close_intent -.-> close_confirm_close;
	close_intent -.-> close_holding_query;
	close_intent -.-> close_place_close;
	close_intent -.-> close_query_status;
	close_intent -.-> close_unknown;
	close_place_close -. &nbsp;done&nbsp; .-> __end__;
	close_place_close -. &nbsp;clean&nbsp; .-> close_clean_request;
	close_query_status -. &nbsp;done&nbsp; .-> __end__;
	close_query_status -. &nbsp;clean&nbsp; .-> close_clean_request;
	close_unknown -. &nbsp;done&nbsp; .-> __end__;
	close_unknown -. &nbsp;clean&nbsp; .-> close_clean_request;
	close_query_backend --> __end__;
	close_submit --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```

## 独立流程文档

- [平仓下单内部图](./close-place-flow.md)

返回[主图](./main-graph-flow.md)。

写入 `state.error` 的错误停止后续业务提交；参数字符串 JSON 容错按 ADR 0027 D3 处理。错误信息、节点与真实回执留在审计输出。LLM 请求预算适用于整次调用，不因进入子图重置。


## Java 请求清洗与提交

所有动作节点完成本次参数、身份与选择准备后，统一进入 `close_clean_request`。原解析和字段账本保留，清洗生成独立请求副本；不兼容字段省略，0/false 保留，不补业务默认值。规则与 Dify 参数字符串 JSON 回退见 [ADR 0027](../adr/0027-field-evidence-contract.md)。

清洗成功后，写类及 JSON 回退请求进入 `close_submit`，仅独立只读请求进入可有限重试的 `close_query_backend`。参数准备和清洗节点不访问 Java、不调用模型。`backend_request` 记录实际 DTO 请求，`cleaning_records` 记录省略/转换，API 与 Harness 参数信封读取 `submitted_params` 投影。清洗后不会从原字段锁账本重新补回脏值。
