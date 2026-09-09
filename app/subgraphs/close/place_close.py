"""close.place_close 节点 · 平仓下单参数提取 + 全部平仓确认（P0 核心）。

对齐新 Dify DSL 的 5 步链路（spec `close_order_request` 分支）：

    平仓参数提取-引用消息解析[code]
        → 获取订单信息[http]（OptionClient.query_close_orders）
        → 格式化订单数据[code]（取 body.data 作为 orderList）
        → 请求下单和确认全部平仓参数提取[llm]
        → 平仓参数提取-合并输出[code]
        → （工程层保留）确定性后处理：POV/跟量默认值、序号→真持仓覆盖、客户端预校验
        → 期权平仓-参数聚合 + 前置清洗 + 真后端调用（`close/backend.py`）

CLAUDE.md P0：严禁本地拼确认卡掩盖后端真实响应——`reply_text` 不再由本节点
拼接文案，改为真后端 `financial-orders/operate` 返回的 `api_result` 由
render 节点透传（`app/nodes/render.py` 已优先读取 `state['api_result']`）。

LLM：thinking 模型 + with_structured_output（ADR 0010）。
prompt：app/prompts/option_close/place_close.md（对齐 Dify
`请求下单和确认全部平仓参数提取`，823 行新版）。

注：close.place_close **不依赖 ticker resolver**——平仓基于订单号
（CO- / OPT- / OPTG-），标的代码已在订单中确定。
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.graph.business_params import validated_close_params
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts import load_prompt
from app.subgraphs.close.aggregate import build_close_order_req_vo
from app.subgraphs.close.backend import call_close_backend
from app.subgraphs.close.merge import merge_close_orders
from app.subgraphs.close.models import CloseOrderItem, ClosePlaceParams
from app.subgraphs.close.reference_parser import ReferenceParseResult, parse_reference_message
from app.tools.exceptions import BackendUnreachableError
from app.tools.option_client import OptionClientHttpx


def _build_user_message(
    raw_content: str,
    quote_content: str,
    parsed: ReferenceParseResult,
    order_list: list[dict[str, Any]],
) -> str:
    """组装与 Dify `请求下单和确认全部平仓参数提取` user template 完全对齐的输入。"""

    def _j(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    single_candidate = parsed["singleHoldingCandidateOrderId"]
    return (
        f"User input: {raw_content}\n"
        f"Holding map (code parsing result): {_j(parsed['holdingMap'])}\n"
        f"Error order ID list: {_j(parsed['errorOrderIds'])}\n"
        f"Full-close confirmation order ID list: {_j(parsed['fullCloseIds'])}\n"
        f"Pure error order ID list: {_j(parsed['pureErrorOrderIds'])}\n"
        f"Pure error order count: {parsed['pureErrorOrderCount']}\n"
        f"Holding map candidate count: {parsed['holdingMapCandidateCount']}\n"
        f"Has single holding candidate: "
        f"{'true' if parsed['hasSingleHoldingCandidate'] else 'false'}\n"
        f"Single holding candidate order ID: {single_candidate if single_candidate else 'null'}\n"
        f"quote_content：{quote_content}\n"
        f"orderList：{_j(order_list)}"
    )


async def _fetch_order_data(
    order_ids: list[str],
    contract_codes: list[str],
    room_id: str | None = None,
    message_id: int | None = None,
) -> list[dict[str, Any]]:
    """获取订单信息[http] + 格式化订单数据[code]（走标准 OptionClient）。

    roomId/messageId 对齐 DSL v2「获取订单信息」payload。
    """
    try:
        result = await OptionClientHttpx().query_close_orders(
            order_ids=order_ids,
            contract_codes=contract_codes,
            room_id=room_id,
            message_id=message_id,
        )
        if result.code == 0 and isinstance(result.data, list):
            return result.data
    except BackendUnreachableError:
        # D2.3：网络不可达保守降级（不阻塞用户提交），下游用空 orderList 继续
        pass
    except Exception:  # noqa: BLE001
        # 业务异常 / 解析失败：降级处理
        pass
    return []


@safe_node
async def close_place_close(state: AgentState) -> dict[str, Any]:
    """close.place_close 节点。

    出参约定：
    - close_params: dict（`{"closeOrderList": [...]}`）
    - api_code / api_result: 真后端调用结果（render 节点透传为回复）
    - trace: 单条 TraceEntry，记录提取的订单数 + 类型分布
    """
    raw = state.get("raw_text", "") or ""
    quote = state.get("quote_content") or ""

    # 步骤 1：平仓参数提取-引用消息解析[code]
    parsed = parse_reference_message(quote, raw)

    # 步骤 2+3：获取订单信息[http] → 格式化订单数据[code]
    order_data = await _fetch_order_data(
        parsed["orderIds"],
        parsed["contractCodes"],
        room_id=state.get("room_id"),
        message_id=state.get("message_id"),
    )

    # 步骤 4：请求下单和确认全部平仓参数提取[llm]
    prompt = load_prompt("option_close", "place_close")
    llm = get_qwen_thinking().with_structured_output(ClosePlaceParams)
    user_message = _build_user_message(raw, quote, parsed, order_data)
    result: Any = await llm.ainvoke(
        [
            ("system", prompt.system),
            ("user", user_message),
        ]
    )

    # 步骤 5：平仓参数提取-合并输出[code]
    llm_orders_dump = [item.model_dump() for item in result.closeOrderList]
    merged = merge_close_orders(parsed["messageType"], parsed["successOrders"], llm_orders_dump)

    # 空列表 → 返回错误（避免无意义地调用真后端 + render 无回复）
    if not merged:
        return {
            "close_params": validated_close_params(closeOrderList=[]),
            "error": "未能识别平仓参数，请提供订单号或持仓序号。",
            "intent": "close_order_request",
            "trace": [
                TraceEntry(
                    node="close_place_close",
                    decision="empty_close_order_list",
                    llm_output=result.model_dump(),
                )
            ],
        }

    close_list = [CloseOrderItem.model_validate(o) for o in merged]

    # === 确定性后处理（工程层增强，不影响后端语义，仅补全/校验参数）===
    combined = f"{raw} {quote}"

    # "不用跟量"/"不跟量" → 市价单（用户明确不要跟量算法）
    _no_tracking = any(kw in combined for kw in ("不用跟量", "不跟量", "不要跟量"))
    _has_explicit_type = bool(
        re.search(r"限价|市价|pov\d*|twap", combined, re.IGNORECASE)
    )
    if "正常挂单" in combined and not _has_explicit_type:
        for leg in close_list:
            if leg.confirmFullClose:
                continue
            leg.closeOrderType = "市价单" if _no_tracking else "POV"

    # "最大跟量"/"拉满跟量" → POV 25%
    _pov_max_kw = ("最大跟量", "拉满跟量", "全跟量", "跟量拉满", "全部最大")
    if any(k in combined for k in _pov_max_kw):
        for leg in close_list:
            if leg.confirmFullClose:
                continue
            if not leg.closeOrderType:
                leg.closeOrderType = "POV"
            leg.closeOrderPovRatio = 25

    # "pov25"/"POV25" 等 → 提取数字作为 POV 比例
    _pov_match = re.search(r"pov\s*(\d{1,3})", combined, re.IGNORECASE)
    if _pov_match:
        _pov_val = int(_pov_match.group(1))
        if 1 <= _pov_val <= 100:
            for leg in close_list:
                if leg.confirmFullClose:
                    continue
                if not leg.closeOrderType:
                    leg.closeOrderType = "POV"
                leg.closeOrderPovRatio = _pov_val

    # === 序号 X / 第 X 笔 → 持仓位置映射（覆盖 LLM 凭空生成的 placeholder orderId）===
    # Round 3 eval 暴露：raw_text 用 "序号1平300万" 引用持仓时，LLM 可能没有可靠的
    # holdingMap 数据，输出 placeholder（"ORDER_ID_FROM_HOLDING_MAP_..."、
    # "<resolved_order_id...>"、"序号X的orderId"）。这里按 1-indexed seq 从已查到
    # 的 order_data 中按位置取真单号覆盖，确保发给真后端的 orderId 合法。
    _order_lookup: dict[str, dict[str, Any]] = {}
    for _o in order_data:
        for _k in ("orderId", "contractCode"):
            _v = _o.get(_k)
            if _v:
                _order_lookup[_v] = _o

    _seq_iter = re.finditer(r"序号\s*[:：]?\s*(\d+)|第\s*(\d+)\s*笔", combined)
    _seq_list = [int(m.group(1) or m.group(2)) for m in _seq_iter]

    def _is_valid_order_id(oid: str | None) -> bool:
        if not oid:
            return False
        return bool(re.fullmatch(r"CO-\d{8}-[A-Z0-9]{4,16}", oid.upper().strip()))

    def _is_placeholder_oid(oid: str | None) -> bool:
        return not _is_valid_order_id(oid)

    # 首次按单个合约平仓时，query-close-orders 不负责创建 orderId；用户原文中的
    # OPT-/OPTG- 合约编号是 operate 创建平仓申请所需的确定性身份。
    if len(parsed["contractCodes"]) == 1 and len(close_list) == 1:
        direct_leg = close_list[0]
        direct_leg.internalTradeId = parsed["contractCodes"][0]
        if not _is_valid_order_id(direct_leg.orderId):
            direct_leg.orderId = None

    for _i, _leg in enumerate(close_list):
        if not _is_placeholder_oid(_leg.orderId) or _i >= len(_seq_list):
            continue
        _seq = _seq_list[_i]
        _idx = _seq - 1
        _resolved = False
        if order_data and 0 <= _idx < len(order_data):
            _real = order_data[_idx]
            _real_oid = _real.get("orderId")
            _real_contract_code = _real.get("contractCode")
            if _real_oid:
                _leg.orderId = _real_oid
                _order_lookup[_real_oid] = _real
            else:
                _leg.orderId = None
            if _real_contract_code:
                _leg.internalTradeId = _real_contract_code
            _resolved = bool(_real_oid or _real_contract_code)
        if not _resolved:
            # 查询阶段可能尚无 orderId；只清除 LLM 订单号占位文字，保留首次平仓的合约编号。
            _leg.orderId = None

    # === 客户端预校验（fail-fast，不调用真后端；不属于"掩盖后端响应"——是拒绝提交）===
    close_order_list_dump = [item.model_dump() for item in close_list]
    if any(not item.orderId and not item.internalTradeId for item in close_list):
        return {
            "close_params": validated_close_params(closeOrderList=close_order_list_dump),
            "error": "未能识别平仓目标，请提供合约编号或持仓序号。",
            "intent": "close_order_request",
            "trace": [
                TraceEntry(
                    node="close_place_close",
                    decision="missing_close_order_identity",
                    llm_output=result.model_dump(),
                )
            ],
        }

    _validation_errors: list[str] = []
    for _leg in close_list:
        _amt = _leg.closeOrderNotionalDelta
        if _amt is not None:
            try:
                _amt_val = float(_amt)
                if _amt_val <= 0:
                    _validation_errors.append("平仓名义本金必须大于0")
                elif _amt_val < 1_000_000:
                    _validation_errors.append("平仓名义本金不能低于100万")
            except (ValueError, TypeError):
                pass

        if _leg.closeOrderType == "限价单" and _leg.closeOrderPrice is None:
            _validation_errors.append("限价单必须填写限定价格")

        if _leg.closeOrderType == "POV" and _leg.closeOrderPovRatio is not None:
            _pov = _leg.closeOrderPovRatio
            if not (1 <= _pov <= 100):
                _validation_errors.append(f"POV比例{_pov}%超出合法范围(1-100%)")

    if _validation_errors:
        _err_msg = "参数校验不通过：" + "；".join(set(_validation_errors))
        return {
            "close_params": validated_close_params(closeOrderList=close_order_list_dump),
            "reply_text": _err_msg,
            "intent": "close_order_request",
            "trace": [
                TraceEntry(
                    node="close_place_close",
                    decision=f"validation_failed: {_err_msg}",
                    llm_output=result.model_dump(),
                )
            ],
        }

    # === 期权平仓-参数聚合 + 前置清洗 + 真后端调用 ===
    # CLAUDE.md P0：严禁本地拼确认卡掩盖后端真实响应——reply_text 由 render 节点
    # 从 state['api_result']（真后端返回）透传，本节点不再拼接文案。
    req_vo = build_close_order_req_vo(close_order_list=close_order_list_dump)
    backend = await call_close_backend(
        state,
        intent="close_order_request",
        close_order_req_vo=req_vo,
    )

    # trace
    types = [item.closeOrderType for item in close_list if item.closeOrderType]
    full_closes = sum(1 for item in close_list if item.confirmFullClose)
    decision = f"orders={len(close_list)}, types={types}, full_close={full_closes}"

    return {
        "close_params": validated_close_params(closeOrderList=close_order_list_dump),
        **backend,
        "intent": "close_order_request",
        "trace": [
            TraceEntry(
                node="close_place_close",
                decision=decision,
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["close_place_close"]
