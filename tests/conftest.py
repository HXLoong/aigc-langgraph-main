"""全局 pytest 配置 + autouse fixtures。

性能优化原则：
- 默认让单元测试走 mock 路径，不调真后端 / 真 LLM
- 个别测试需要真路径时通过 fixture override
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _ticker_resolver_default_whitelist(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认让 ticker resolver 走 whitelist 模式（不调真后端 securities-instrument/select）。

    动机：M3 切换 react 模式后业务子图 e2e 测试触发真后端调用，
    导致跑全套从 30s → 287s。

    Override：test_resolver_react.py 自己有 autouse fixture 覆盖回 react。
    """
    from app.subgraphs.ticker import resolver as resolver_mod

    monkeypatch.setattr(resolver_mod, "DEFAULT_MODE", "whitelist")
