"""业务子图：每个 product_type 一个原生嵌入主图的子图（ADR 0024 D3）。

- swap · 互换（文本 / 图片 / Excel 三链，见 swap/graph.py）
- option · 期权开仓（1 intent + 7 意图节点，不含平仓）
- close · 期权平仓（product_type=option_close，1 intent + 6 意图节点）

标的识别、分词与排序归 Java（ADR 0025），本地无 ticker 子图。
子图只通过 SubgraphOutput 写回父图（app/graph/state.py）。
"""
