"""互换子图消费主图联合解析结果，完成候选选择和请求准备，再清洗并提交 Java。

文本与 Excel 共用同一确定性业务路径；图片由主图拒绝。证券识别归 Java。"""
from app.subgraphs.swap.graph import build_swap_graph

__all__ = ["build_swap_graph"]
