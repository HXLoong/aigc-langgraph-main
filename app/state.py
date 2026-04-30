"""LangGraph State 定义。

核心设计原则：
1. 字段按来源分组：输入 / 上下文 / 路由 / 标的 / 订单 / 输出
2. 使用 Annotated + reducer 指明并行分支如何合并
3. 每个 trace 记录一个节点的决策，便于故障定位
"""
from __future__ import annotations

from operator import add
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, Field

# ============================================================
# 枚举
# ============================================================
ProductType = Literal["option", "swap", "option_close", "unknown"]

SwapIntent = Literal[
    "place_order_request",      # 请求下单
    "confirm_order",             # 确认下单
    "cancel_order_request",      # 请求撤单
    "confirm_cancel_order",      # 确认撤单
    "confirm_modify_order",      # 确认改单
    "query_order_status",        # 查询订单状态
]

OptionIntent = Literal[
    "new_inquiry",               # 新询价
    "place_order",               # 下单
    "modify_order",              # 改单
    "cancel_order",              # 撤单
    "confirm",                   # 确认
    "existing_command",          # 存量指令
]

CloseIntent = Literal[
    "close_order_query",         # 持仓查询
    "close_order_request",       # 请求平仓
    "close_order_confirm",       # 确认平仓
    "close_order_cancel",        # 撤单
    "close_order_confirm_cancel",  # 确认撤单
]


# ============================================================
# 输入（不可变）
# ============================================================
class WechatInput(TypedDict, total=False):
    """来自企微消息回调的原始输入。"""
    conversation_id: str
    message_id: str
    room_id: str
    user_id: str
    guid: str
    raw_content: str
    quote_content: str | None
    quote_appinfo: str | None
    attachments: list[dict]       # 图片/Excel URL 列表


# ============================================================
# 标的候选
# ============================================================
class TickerCandidate(BaseModel):
    """标的候选，最终结果必须 from_goats=True。"""
    keyword: str = Field(..., description="原始关键字")
    wind_code: str | None = None
    ins_sht_desc: str | None = None  # 标的简称
    ins_lng_desc: str | None = None  # 标的长名
    ins_family: str | None = None    # EQUITY/FUTURE/FUND/...
    currency: str | None = None
    exchange: str | None = None
    is_complete: bool = False
    from_goats: bool = False          # 经 goats 库验证（强制要求）


# ============================================================
# Trace 记录
# ============================================================
class TraceEntry(TypedDict, total=False):
    node: str
    status: Literal["success", "error", "skip"]
    decision: str
    input_preview: str
    output_preview: str
    duration_ms: int
    error: str


# ============================================================
# Agent 主状态
# ============================================================
class AgentState(TypedDict, total=False):
    """LangGraph 主状态。

    字段分组：
    - 输入 / 上下文 / 路由 / 标的 / 订单参数 / 输出 / Trace
    """
    # === 输入（不可变） ===
    wechat_input: WechatInput
    bot_name_list: list[str]

    # === 上下文 ===
    history_messages: Annotated[list[dict], add]    # 本会话历史
    conversation_orders: list[dict]                   # 本会话的已下单记录
    counterparty_list: list[dict]                     # 交易对手列表

    # === 路由决策 ===
    product_type: ProductType
    modality: str
    operate: str
    intent: str | None
    fast_query: bool
    existing_command: bool
    at_bot: bool

    # === 标的识别（互换专用） ===
    raw_tickers: list[str]                    # LLM 分词结果
    ticker_candidates: list[TickerCandidate]  # goats 返回的候选
    resolved_tickers: list[TickerCandidate]   # 排序过滤后的最终结果

    # === 订单参数（统一结构） ===
    order_list: list[dict]
    order_ids: list[str]        # cancel / confirm 场景

    # === 输出 ===
    api_code: int | None
    api_result: str | None
    error: str | None
    reply_text: str | None

    # === Trace（每个节点追加一条） ===
    trace: Annotated[list[TraceEntry], add]


# ============================================================
# 工具函数：创建初始 State
# ============================================================
def make_initial_state(wechat_input: WechatInput) -> AgentState:
    """从企微输入构造初始 State。"""
    return AgentState(
        wechat_input=wechat_input,
        bot_name_list=[],
        history_messages=[],
        conversation_orders=[],
        counterparty_list=[],
        product_type="unknown",
        modality="text",
        operate="",
        intent=None,
        fast_query=False,
        existing_command=False,
        at_bot=False,
        raw_tickers=[],
        ticker_candidates=[],
        resolved_tickers=[],
        order_list=[],
        order_ids=[],
        api_code=None,
        api_result=None,
        error=None,
        reply_text=None,
        trace=[],
    )


def preview(data: Any, limit: int = 200) -> str:
    """生成用于 trace 的预览字符串，避免 trace 字段过大。"""
    s = str(data)
    return s[:limit] + ("..." if len(s) > limit else "")
