"""tools/ — 调 Java 后端业务 API 的客户端层（ADR 0001 D2 修订版）。

按真实 endpoint 边界拆 3 个 Protocol（不是按业务领域）：
- OptionClient: POST /admin-api/financial-orders/operate（16 个意图）
- SwapClient: POST /admin-api/swap-order/operate（7 个意图）
- TickerClient: 标的查询 / 推断 prompt / 交易对手列表

工程纪律：
- 字段名严格 1:1 匹配 Java DTO（保留 placeOrderWindCode 等 camelCase）
- 金额一律 Decimal；向 Goats 发送前 truncate(2)
- 调用方依赖 Protocol 不依赖具体实现
"""
from app.tools.models import (
    GoatsAlgoType,
    GoatsCurrency,
    GoatsOrderDirection,
    GoatsOrderStatus,
    GoatsPriceType,
    GoatsTransactionType,
    MachineContext,
)
from app.tools.option_client import (
    FinancialOrderOpenApiBaseSaveReqVO,
    FinancialOrderOpenApiSaveReqVO,
    OptionClient,
    OptionClientHttpx,
    OptionIntentionType,
)
from app.tools.swap_client import (
    SwapClient,
    SwapClientHttpx,
    SwapIntentionType,
    SwapOrderOpenApiBaseSaveReqVO,
    SwapOrderOpenApiSaveReqVO,
)
from app.tools.ticker_client import (
    KeywordItem,
    SecuritiesInstrumentReqVO,
    TickerClient,
    TickerClientHttpx,
)

__all__ = [
    # models
    "GoatsAlgoType",
    "GoatsCurrency",
    "GoatsOrderDirection",
    "GoatsOrderStatus",
    "GoatsPriceType",
    "GoatsTransactionType",
    "MachineContext",
    # option
    "FinancialOrderOpenApiBaseSaveReqVO",
    "FinancialOrderOpenApiSaveReqVO",
    "OptionClient",
    "OptionClientHttpx",
    "OptionIntentionType",
    # swap
    "SwapClient",
    "SwapClientHttpx",
    "SwapIntentionType",
    "SwapOrderOpenApiBaseSaveReqVO",
    "SwapOrderOpenApiSaveReqVO",
    # ticker
    "KeywordItem",
    "SecuritiesInstrumentReqVO",
    "TickerClient",
    "TickerClientHttpx",
]
