"""全局 pytest 配置 + autouse fixtures。

性能优化原则：
- 默认让单元测试走 mock 路径，不调真后端 / 真 LLM
- 个别测试需要真路径时通过 fixture override
"""
from __future__ import annotations
