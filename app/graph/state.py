"""LangGraph 主图共享的 AgentState（ADR 0001 D6）。

设计原则：
- 按业务对象聚合，不按节点输出扁平铺
- reducer 字段（trace / history_messages）用 Annotated[..., add] 累加
- 业务参数字段 M1 阶段用 dict[str, Any] 占位，M2 阶段替换为具体 Pydantic 模型
"""
from __future__ import annotations

from operator import add
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field


# ============================================================
# 子模型
# ============================================================


class Message(BaseModel):
    """历史消息（来自上次 checkpoint 加载）。"""

    model_config = ConfigDict(extra="allow")
    role: Literal["user", "assistant", "system"]
    content: str
    ts: str | None = None


class TickerCandidate(BaseModel):
    """ticker 子图输出的候选标的（对齐 Java SecuritiesInstrumentOpenApiRespVO）。"""

    model_config = ConfigDict(extra="allow")
    windCode: str = Field(description="标的代码，如 600989.SH")
    insShtDesc: str | None = None
    insLngDesc: str | None = None
    relevanceScore: int | None = None
    transactionTypeLists: list[str] = Field(default_factory=list)
    from_goats: bool = Field(
        default=False,
        description="必须 True 才允许出现在 LangGraph 输出中（CLAUDE.md 硬约束）",
    )


class TraceEntry(BaseModel):
    """每节点决策痕迹（供 harness 失败定位 + ADR 0014 D7 失败报告）。"""

    model_config = ConfigDict(extra="allow")
    node: str
    decision: str | None = None
    elapsed_ms: int | None = None
    llm_input_excerpt: str | None = None
    llm_output: dict[str, Any] | None = None


class ErrorInfo(BaseModel):
    """节点异常被 @safe_node 捕获后写入此字段，不让图崩。"""

    model_config = ConfigDict(extra="allow")
    node: str
    type: str
    message: str
    traceback: str | None = None


# ============================================================
# 路由层枚举
# ============================================================

ProductType = Literal["swap", "option", "option_close", "unknown"]


# ============================================================
# AgentState
# ============================================================


class AgentState(TypedDict, total=False):
    """LangGraph 主图共享的 State Schema。

    字段分层：
    - 入口：解析 Dify Workflow Run inputs 后由 ingest 节点写入（9 个机器人上下文字段）
    - 历史：history_messages（reducer 累加）
    - 业务路由：product_type 一级 + intent 二级
    - 业务对象：聚合的参数字典（多节点共享同字段；M1 用 dict 占位，M2 替换为 Pydantic）
    - 工程层：trace（reducer 累加）+ error
    """

    # -------- 入口（contracts §2.1 §3.1 的 9 个机器人上下文字段）--------
    raw_text: str  # rawContent
    conversation_id: str  # conversationId
    message_id: int  # messageId
    user_id: str  # userId
    room_id: str  # roomId
    guid: str | None  # guid
    message_content: str  # messageContent（原始 + 引用）
    quote_content: str | None  # quoteContent
    quote_appinfo: str | None  # quoteAppinfo（已弃用但保留兼容）

    # -------- 历史 --------
    history_messages: Annotated[list[Message], add]

    # -------- 业务路由 --------
    product_type: ProductType
    intent: str  # 小写下划线 type 字符串，对齐 Java SwapIntentionType / stockOptionIntentionType

    # -------- 业务对象（M1 用 dict 占位，M2 替换为 Pydantic 模型）--------
    tickers: list[TickerCandidate]
    place_params: dict[str, Any] | None
    cancel_params: dict[str, Any] | None
    confirm: dict[str, Any] | None
    query_filter: dict[str, Any] | None
    close_params: dict[str, Any] | None

    # -------- ticker 消歧 --------
    # 多命中分差不足时收集到此处，render 节点生成消歧卡片（Issue #20）
    ticker_hitl_candidates: list[dict[str, Any]] | None

    # -------- 回复渲染 --------
    reply_text: str | None  # render 节点写入；API 层透传给企微

    # -------- 工程层 --------
    trace: Annotated[list[TraceEntry], add]
    error: ErrorInfo | None

    # -------- 输出 --------
    reply_text: str | None
    api_result: str | None
    api_code: int | None
