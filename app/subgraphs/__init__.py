"""业务子图。

按 ADR 0001 D6 + grill-with-docs 2026-05-10：
- ticker · ReAct Agent 子图（被 swap/option/option_close 共享调用）
- swap · 10 节点
- option · 6 节点（1 intent + 5 extract，不含 close）
- option_close · 7 节点
"""
