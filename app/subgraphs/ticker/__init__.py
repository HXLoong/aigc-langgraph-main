"""ticker 子图：标的识别 ReAct Agent。

ADR 0008 + ADR 0010 + ADR 0013 + grill-with-docs 2026-05-10 运行时约束：
- 4 工具：tokenize / completeness / rank / infer_code
- thinking 模型（ADR 0010）
- hard cap 8 步（recursion_limit=16）
- 0 命中 → from_goats=False → cascade 防御
- 多命中分差 ≥ 10 自动选最高，否则 HITL（ADR 0006）
- `from_goats=True` 是 CLAUDE.md 硬约束
"""
from app.subgraphs.ticker.graph import build_ticker_graph

__all__ = ["build_ticker_graph"]
