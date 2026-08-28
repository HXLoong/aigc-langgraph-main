"""ticker 子图：标的识别（Dify DSL v2 迁移 · 标的智能化推断和分词工具，12 节点）。

不再是独立的 LangGraph 子图节点——业务子图（swap / option / close）直接
`from app.subgraphs.ticker.resolver import resolve_ticker_full` 同步调用，
本包只是一个函数库（tools.py + resolver.py），没有对外暴露 `build_ticker_graph`。

管线（tools.py 顶部有完整说明）：
- 候选提取(tokenize，确定性) -> 格式化(空->短路)
- 并行 3 路 LLM：infer_code_batch(推断标的代码) / split_ticker_keywords(拆分)
  / judge_ticker_type(判断标的类型)
- merge_and_validate（确定性，交易所后缀正则校验完整标的）
- GOATS securities-instrument/select 查询 + rank_candidates(LLM 排序过滤)

硬约束（ADR 0008 + CLAUDE.md）：
- `from_goats=True` 才允许出现在输出里——凡进入 resolved 的标的都必须经过
  GOATS 存在性校验，这是本项目对 Dify 行为的有意增强
"""
from app.subgraphs.ticker.resolver import TickerResolution, resolve_ticker, resolve_ticker_full

__all__ = ["TickerResolution", "resolve_ticker", "resolve_ticker_full"]
