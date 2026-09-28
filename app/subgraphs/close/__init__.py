"""期权平仓子图（product_type=option_close）消费联合解析并检查本次目标。

内部平仓图只准备请求；父图统一清洗并执行持仓查询、平仓、确认、撤单或查单。"""
from app.subgraphs.close.graph import build_close_graph

__all__ = ["build_close_graph"]
