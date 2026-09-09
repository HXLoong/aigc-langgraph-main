"""LangGraph 主图共享的 AgentState（ADR 0001 D6）。

设计原则：
- 按业务对象聚合，不按节点输出扁平铺
- reducer 字段（trace / history_messages）用 Annotated[..., add] 累加
- 业务参数字段 M1 阶段用 dict[str, Any] 占位，M2 阶段替换为具体 Pydantic 模型
"""
from __future__ import annotations

from operator import add
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    sourceKeywords: list[str] = Field(
        default_factory=list,
        description="本次输入中解析为该 GOATS 标的的原始候选词",
    )
    from_goats: bool = Field(
        default=False,
        description="必须 True 才允许出现在 LangGraph 输出中（CLAUDE.md 硬约束）",
    )


#: trace 内单个字符串值的长度上限(架构体检 2026-08 改进 C)。
#: trace 是 add-reducer 累积字段,每个 checkpoint 携带全部历史 trace——
#: llm_output 若存完整 LLM 输出(如 OCR 全文),长会话 checkpoint 线性膨胀。
TRACE_TEXT_LIMIT = 500

_TRUNC_MARK = "…[已截断]"


def _truncate_trace_value(value: Any) -> Any:
    """递归截断超长字符串;结构、数字、短值原样保留。"""
    if isinstance(value, str) and len(value) > TRACE_TEXT_LIMIT:
        return value[:TRACE_TEXT_LIMIT] + _TRUNC_MARK
    if isinstance(value, dict):
        return {k: _truncate_trace_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_truncate_trace_value(v) for v in value]
    return value


class TraceEntry(BaseModel):
    """每节点决策痕迹（供 harness 失败定位 + ADR 0014 D7 失败报告）。

    llm_output / llm_input_excerpt 在写入时统一截断(TRACE_TEXT_LIMIT),
    防止累积 trace 撑大 checkpoint;完整 LLM I/O 由 LangFuse 侧保留。
    """

    model_config = ConfigDict(extra="allow")
    node: str
    decision: str | None = None
    elapsed_ms: int | None = None
    llm_input_excerpt: str | None = None
    llm_output: dict[str, Any] | None = None

    @field_validator("llm_output", "llm_input_excerpt", mode="before")
    @classmethod
    def _truncate_long_text(cls, v: Any) -> Any:
        return _truncate_trace_value(v)


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

    # -------- 入口·DSL v2 新增（主干工作流 start 节点 2026-08 版）--------
    fast_query: str | None  # fast_query：快速询价标记（参与型看涨/雪球前置分支）
    at_bot: bool | None  # at_bot：是否 @ 机器人
    existing_command: str | None  # existing_command：存量兼容-交易查询指令
    bot_name: str | None  # bot_name：机器人名称（替代旧 bot_name_list 获取）
    operator_user_id: str | None  # operator_user_id：操作者（替代旧 userId 语义）

    # -------- 对手方与引用候选（路由前置提取，DSL v2「交易对手、候选标的提取」）--------
    # 入口原始 JSON 串（Java 侧 option/trs 预查结果，ingest 透传，pre_route 解析）
    option_counterparties_raw: str | None
    swap_counterparties_raw: str | None
    # 后端预查对手精简列表：[{ctptyId, shortName, longName, sort}]
    option_counterparties: list[dict[str, Any]]
    swap_counterparties: list[dict[str, Any]]
    # 引用消息解析出的候选标的块：[{orderId, orderSeq, candidates: [{seq, code, name}]}]
    quote_ticker_candidates: list[dict[str, Any]]

    # -------- 输入文件（DSL v2:全图片→互换-图片链,全 Excel→互换-Excel 链）--------
    input_files: list[dict[str, Any]] | None  # [{type, extension, mime_type, url/base64...}]
    swap_input_mode: str | None  # text | image | excel（intent_route 写入,swap 子图分流）

    # -------- 历史 --------
    history_messages: Annotated[list[Message], add]

    # -------- 业务路由 --------
    #: 单次 graph 调用的关联 ID（ADR 0004/#156：node_trace ↔ LangFuse 关联键）
    trace_id: str
    product_type: ProductType
    intent: str  # 小写下划线 type 字符串，对齐 Java SwapIntentionType / stockOptionIntentionType

    # -------- 业务对象（#160/ADR 0001 D6：运行时为 dict，写入必须经
    # app/graph/business_params.py 的 validated_* 校验——形状的唯一权威）--------
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
