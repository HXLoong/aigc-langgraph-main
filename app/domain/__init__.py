"""纯业务规则层：无 IO、无 LangGraph 依赖，主图节点、子图与后端客户端共用。

- order_ids：三条产品线订单号 / 合约编号的正则单一来源
- numerals：序号与中文数字解析
- confirmation：七条最终确认路径共用的口令与引用范围校验
- tenor：期权期限换算
- fast_execution：最大跟量意图的公共规则
"""
