"""LangGraph 主图共享的 AgentState（ADR 0001 D6）。

设计原则：
- 按业务对象聚合，不按节点输出扁平铺
- reducer 字段：trace 用 merge_by_id 按 id 合并；history_messages 用 merge_history（按 id 合并 + 最近 N 条窗口，ADR 0024 D3/D4）
- 业务参数字段 M1 阶段用 dict[str, Any] 占位，M2 阶段替换为具体 Pydantic 模型
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.extraction.fields import FieldRecord, merge_fields
from app.wire_model import WireModel

# ============================================================
# 按 id 合并的 reducer（ADR 0024 D3）
# ============================================================


def _new_id() -> str:
    return uuid.uuid4().hex


class _Identified(BaseModel):
    """带合并键的 state 列表元素。

    原生子图节点会把**完整输出 state** 交回父图；trace / history_messages 若用 operator.add，
    父图已有条目会被再加一遍。与 LangGraph `add_messages` 同款：每条带 id，reducer 按 id 去重。
    id 必须进入 checkpoint；相等比较只比较内容，HTTP trace 单独投影。
    """

    id: str = Field(default_factory=_new_id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BaseModel):
            return NotImplemented
        return type(self) is type(other) and self.model_dump(exclude={"id"}) == other.model_dump(exclude={"id"})

    __hash__ = None  # type: ignore[assignment]


def _merge_key(item: Any) -> Any:
    ident = getattr(item, "id", None)
    return ident if isinstance(ident, str) and ident else id(item)


def merge_by_id(left: list[Any] | None, right: list[Any] | None) -> list[Any]:
    """list reducer：追加 right 中 left 尚未包含（按 id，无 id 则按对象身份）的元素。"""
    merged = list(left or [])
    seen = {_merge_key(item) for item in merged}
    for item in right or []:
        key = _merge_key(item)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


#: history_messages 窗口默认值（settings.history_window_messages 不可用时的兜底）
DEFAULT_HISTORY_WINDOW = 40


def _history_window() -> int:
    try:
        from app.config import get_settings

        return int(get_settings().history_window_messages)
    except Exception:  # noqa: BLE001 - 配置不可用（测试 / 脚本）时用默认窗口
        return DEFAULT_HISTORY_WINDOW


def merge_history(left: list[Any] | None, right: list[Any] | None) -> list[Any]:
    """history_messages reducer：按 id 合并后只保留最近 N 条（ADR 0024 D4）。"""
    merged = merge_by_id(left, right)
    window = _history_window()
    return merged[-window:] if window > 0 and len(merged) > window else merged


# ============================================================
# 子模型
# ============================================================


class Message(_Identified):
    """历史消息（来自上次 checkpoint 加载）。"""

    model_config = ConfigDict(extra="allow")
    role: Literal["user", "assistant", "system"]
    content: str
    ts: str | None = None


class TickerCandidate(WireModel):
    """ticker 子图输出的候选标的（对齐 Java SecuritiesInstrumentOpenApiRespVO）。"""

    model_config = ConfigDict(extra="allow")
    wind_code: str = Field(alias="windCode", description="标的代码，如 600989.SH")
    ins_sht_desc: str | None = Field(default=None, alias="insShtDesc")
    ins_lng_desc: str | None = Field(default=None, alias="insLngDesc")
    relevance_score: int | None = Field(default=None, alias="relevanceScore")
    transaction_type_lists: list[str] = Field(alias="transactionTypeLists", default_factory=list)
    source_keywords: list[str] = Field(alias="sourceKeywords",
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


class TraceEntry(_Identified):
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
    code: Literal["E1", "E2", "E3", "E4", "E5"] = "E3"
    message: str
    traceback: str | None = None
    causes: list[ErrorInfo] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def classify(cls, value: Any) -> Any:
        if isinstance(value, dict) and "code" not in value:
            kind = value.get("type")
            code = "E3"
            if kind in {"APITimeoutError", "APIConnectionError", "RateLimitError", "InternalServerError", "TimeoutError"}:
                code = "E1"
            elif kind in {"EvidenceError", "ValidationError", "OutputParserException"}:
                code = "E2"
            elif kind in {"BackendUnreachableError", "EmptyBackendResultError", "SetIntentError", "ConnectError"}:
                code = "E4"
            elif kind == "WorkflowTimeout":
                code = "E5"
            return {**value, "code": code}
        return value


def merge_errors(left: ErrorInfo | None, right: ErrorInfo | None) -> ErrorInfo | None:
    """Merge simultaneous failures; explicit None is reserved for ingest's reset."""
    if right is None or left is None:
        return right
    failures = (left.causes or [left]) + (right.causes or [right])
    unique = {(e.node, e.type, e.message): e for e in failures}
    ordered = [unique[key] for key in sorted(unique)]
    return ordered[0].model_copy(update={"causes": ordered})


# ============================================================
# 路由层枚举
# ============================================================

ProductType = Literal["swap", "option", "option_close", "unknown"]

#: 本轮动作类别（ADR 0024 D2）：place 下单 / modify 改单 / cancel 撤单类 / inquiry 询价 / close 平仓
ExpectedAction = Literal["place", "modify", "cancel", "inquiry", "close"]


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
    bot_name: str | None  # 入口兼容字段；不注入 LLM 提示词
    operator_user_id: str | None  # operator_user_id：操作者（替代旧 userId 语义）
    retry_origin: str | None  # Java RabbitMQ 重投来源；只控制通知投影，不重试交易
    retry_attempt: str | None

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

    # -------- 历史 / ConversationMemory（跨轮持久化，ingest 不重置）--------
    history_messages: Annotated[list[Message], merge_history]
    #: 上一轮已确认业务对象（ADR 0024 D4）：{product_type, intent, expected_action, order_ids, message_id}
    #: 由主图 remember_confirmed_params 写入；确认链路裸确认时优先读它，显式引用 / 单号仍优先
    last_confirmed_params: dict[str, Any] | None
    #: 兼容平仓撤单链的最近会话订单；内容由上游提供，节点只读取最后一笔订单号
    conversation_orders: list[dict[str, Any]]
    last_activity_at: float  # 最近一轮开始时间；仅图内部写入，不能由请求覆盖
    session_status: Literal["active", "expired"]

    # -------- 业务路由 --------
    #: 单次 graph 调用的关联 ID（ADR 0004/#156：node_trace ↔ LangFuse 关联键）
    trace_id: str
    product_type: ProductType
    intent: str  # 本轮意图，ingest 清空；对齐 Java SwapIntentionType / stockOptionIntentionType

    # -------- 业务对象（#160/ADR 0001 D6：运行时为 dict，写入必须经
    # app/graph/business_params.py 的 validated_* 校验——形状的唯一权威）--------
    #: 本轮要对后端执行的动作类别（ADR 0024 D2 顶层化）：写类节点写入，render / 输出层读取；
    #: 查询类意图为 None。与 Java operate 的 type 无关——那条由 intent 驱动
    expected_action: ExpectedAction | None
    field_records: Annotated[dict[str, FieldRecord], merge_fields]
    tickers: list[TickerCandidate]  # 旧 checkpoint/HTTP 兼容；当前业务不在本地解析证券
    place_params: dict[str, Any] | None
    cancel_params: dict[str, Any] | None
    confirm: dict[str, Any] | None
    query_filter: dict[str, Any] | None
    close_params: dict[str, Any] | None

    # -------- swap 选择链指针通道（ADR 0024 重构 3：选对手 ‖ 选标的 并行）--------
    # 两个 LLM 节点只产出指针，确定性查表覆盖由 swap_apply_picks 汇合节点完成后清空
    swap_counterparty_picks: dict[str, Any] | None  # {hasSignal, picks: [{orderId, letter, directName}]}
    swap_ticker_picks: list[dict[str, Any]] | None  # [{orderId, seq, directRef}]

    # -------- ticker 消歧 --------
    # 多命中分差不足时收集到此处，render 节点生成消歧卡片（Issue #20）
    ticker_hitl_candidates: list[dict[str, Any]] | None  # 旧状态兼容，不参与本地回复

    # -------- 回复渲染 --------
    reply_text: str | None  # render 节点写入；API 层透传给企微

    # -------- 工程层 --------
    trace: Annotated[list[TraceEntry], merge_by_id]
    error: Annotated[ErrorInfo | None, merge_errors]

    # -------- 后端结果 --------
    #: 后端 operate 的 result.data 原样透传：dict / list / 字符串消息三态
    #: （swap/backend.py、close/backend.py），render 与提交节点按形态分支
    api_result: str | dict[str, Any] | list[Any] | None
    api_code: int | None


class SubgraphOutput(TypedDict, total=False):
    """业务子图（swap / option / option_close）对父图的合法写回面（ADR 0024 D2）。

    父图路由键（product_type / swap_input_mode）、入口字段与 history_messages 对子图只读：
    子图内部仍以 AgentState 运行，但 compile 时 `output_schema=SubgraphOutput` 让其它键
    的写入停在子图内，不再能改写父图。
    """

    intent: str
    expected_action: ExpectedAction | None
    field_records: Annotated[dict[str, FieldRecord], merge_fields]
    tickers: list[TickerCandidate]  # 旧 checkpoint/HTTP 兼容；当前业务不在本地解析证券
    place_params: dict[str, Any] | None
    cancel_params: dict[str, Any] | None
    confirm: dict[str, Any] | None
    query_filter: dict[str, Any] | None
    close_params: dict[str, Any] | None
    ticker_hitl_candidates: list[dict[str, Any]] | None  # 旧状态兼容，不参与本地回复
    reply_text: str | None
    api_result: str | dict[str, Any] | list[Any] | None
    api_code: int | None
    trace: Annotated[list[TraceEntry], merge_by_id]
    error: Annotated[ErrorInfo | None, merge_errors]
