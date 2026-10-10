"""模拟 Java 后端 `/admin-api/*` 接口集合（对齐真实 DTO 契约）。

本包按业务领域拆分路由：
- `swap.py`        · `/admin-api/swap-order/*`
- `financial.py`   · `/admin-api/financial-orders/*`
- `ticker.py`      · `/admin-api/integration/securities-instrument/*` + `/admin-api/counterparty/*`
- `misc.py`        · `bot/name/list` + `set-intent` + 兜底

所有路由统一返回 `{code, data, msg}` 格式（Java `CommonResult`）。
"""
from __future__ import annotations

from fastapi import APIRouter

from mock_api.backend.financial import router as financial_router
from mock_api.backend.misc import router as misc_router
from mock_api.backend.swap import router as swap_router
from mock_api.backend.ticker import router as ticker_router

router = APIRouter()
router.include_router(swap_router)
router.include_router(financial_router)
router.include_router(ticker_router)
router.include_router(misc_router)

__all__ = ["router"]
