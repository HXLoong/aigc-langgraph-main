"""close.place_close 节点 · 平仓下单参数提取（P0 核心）。

输入：raw_text + quote_content + 上游数据（holding map / error order ids /
order list / full-close confirmation list）
输出：state['close_params'] = ClosePlaceParams.model_dump()

骨架阶段范围（M2 Day 11）：
- LLM 提取 closeOrderList（9 字段 × N 订单）
- 上游数据（holding map / orderList 等）暂留空——后续 PR 接入：
  · holding map 来自 close.holding_query 的输出
  · orderList 来自 OptionClient.query_close_orders（M3 联调阶段）

注：close.place_close **不依赖 ticker resolver**——平仓基于订单号
（CO- / OPT- / OPTG-），标的代码已在订单中确定。

LLM：standard 模型 + with_structured_output（ADR 0010）。
prompt：app/prompts/option_close/place_close.md（1036 行，最大平仓 prompt）。
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_close_params
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts import load_prompt
from app.subgraphs.close.models import ClosePlaceParams
from app.tools.exceptions import BackendUnreachableError
from app.tools.option_client import OptionClientHttpx


def _build_user_message(state: AgentState) -> str:
    """组装 user message。

    骨架阶段：仅传 raw_text + quote_content。后续 PR 加上：
    - holding map: 从 state['holding_map'] 或上游 holding_query 输出读
    - error order id list / full-close confirmation list / orderList
      （来自 OptionClient.query_close_orders 响应）
    """
    raw_content = state.get("raw_text", "") or ""
    quote_content = state.get("quote_content") or ""
    return (
        f"用户发送消息：{raw_content}\n"
        f"用户引用消息：{quote_content}"
    )


@safe_node
async def close_place_close(state: AgentState) -> dict[str, Any]:
    """close.place_close 节点。

    出参约定：
    - close_params: dict（ClosePlaceParams.model_dump()）
    - trace: 单条 TraceEntry，记录提取的订单数 + 类型分布
    """
    prompt = load_prompt("option_close", "place_close")
    llm = get_qwen_thinking().with_structured_output(ClosePlaceParams)

    user_message = _build_user_message(state)
    result: Any = await llm.ainvoke(
        [
            ("system", prompt.system),
            ("user", user_message),
        ]
    )

    # === 确定性后处理 ===
    raw = state.get("raw_text", "") or ""
    quote = state.get("quote_content") or ""
    combined = f"{raw} {quote}"
    close_list = result.closeOrderList

    # 空列表 → 返回错误（避免 render 无回复）
    if not close_list:
        return {
            "close_params": validated_close_params(**result.model_dump()),
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

    # "不用跟量"/"不跟量" → 市价单（用户明确不要跟量算法）
    _no_tracking = any(kw in combined for kw in ("不用跟量", "不跟量", "不要跟量"))
    import re as _re_type
    _has_explicit_type = bool(_re_type.search(
        r"限价|市价|pov\d*|twap", combined, _re_type.IGNORECASE
    ))
    if "正常挂单" in combined and not _has_explicit_type:
        for leg in close_list:
            leg.closeOrderType = "市价单" if _no_tracking else "POV"

    # "最大跟量"/"拉满跟量" → POV 25%
    _pov_max_kw = ("最大跟量", "拉满跟量", "全跟量", "跟量拉满", "全部最大")
    if any(k in combined for k in _pov_max_kw):
        for leg in close_list:
            if not leg.closeOrderType:
                leg.closeOrderType = "POV"
            leg.closeOrderPovRatio = 25

    # "pov25"/"POV25" 等 → 提取数字作为 POV 比例
    import re as _re_pov
    _pov_match = _re_pov.search(r"pov\s*(\d{1,3})", combined, _re_pov.IGNORECASE)
    if _pov_match:
        _pov_val = int(_pov_match.group(1))
        if 1 <= _pov_val <= 100:
            for leg in close_list:
                if not leg.closeOrderType:
                    leg.closeOrderType = "POV"
                leg.closeOrderPovRatio = _pov_val

    # === 拉取真实持仓数据 + 覆盖 LLM 输出（走标准 OptionClient，享受 D2.3 不可达降级）===
    import re as _re
    _oids = _re.findall(r"CO-\d{8}-[A-Z0-9]{4,16}", combined)
    _ccs = _re.findall(r"OPTG?-[A-Z]{4,}\d{0,10}", combined)
    order_data: list[dict] = []
    try:
        _result = await OptionClientHttpx().query_close_orders(
            order_ids=_oids, contract_codes=_ccs
        )
        if _result.code == 0 and isinstance(_result.data, list):
            order_data = _result.data
    except BackendUnreachableError:
        # D2.3：网络不可达保守降级（保留本地确认卡），不阻塞用户
        pass
    except Exception:  # noqa: BLE001
        # 业务异常 / 解析失败：降级处理，不阻塞用户提交确认
        pass

    _order_lookup: dict[str, dict] = {}
    for _o in order_data:
        for _k in ("orderId", "contractCode"):
            _v = _o.get(_k)
            if _v:
                _order_lookup[_v] = _o

    for _leg in close_list:
        _matched = _order_lookup.get(_leg.orderId) or _order_lookup.get(_leg.internalTradeId)
        if _matched and _matched.get("orderId"):
            _leg.orderId = _matched["orderId"]
            _leg.internalTradeId = _matched["orderId"]

    # === 序号 X / 第 X 笔 → 持仓位置映射（覆盖 LLM 凭空生成的 placeholder orderId）===
    # Round 3 eval 暴露：raw_text 用 "序号1平300万" 引用持仓时，LLM 没有 holdingMap 数据，
    # 会输出 placeholder（"ORDER_ID_FROM_HOLDING_MAP_..."、"<resolved_order_id...>"、"序号X的orderId"）。
    # 这里按 1-indexed seq 从已查到的 order_data 中按位置取真单号覆盖。
    _seq_iter = _re.finditer(r"序号\s*[:：]?\s*(\d+)|第\s*(\d+)\s*笔", combined)
    _seq_list = [int(m.group(1) or m.group(2)) for m in _seq_iter]

    def _is_placeholder_oid(oid: str | None) -> bool:
        if not oid:
            return True
        s = oid.upper().strip()
        if _re.fullmatch(r"CO-\d{8}-[A-Z0-9]{4,16}", s):
            return False
        if _re.fullmatch(r"OPTG?-[A-Z]+\d{0,10}", s):
            return False
        return True

    for _i, _leg in enumerate(close_list):
        if not _is_placeholder_oid(_leg.orderId):
            continue
        _seq = _seq_list[_i] if _i < len(_seq_list) else (_i + 1)
        _idx = _seq - 1
        _resolved = False
        if order_data and 0 <= _idx < len(order_data):
            _real = order_data[_idx]
            _real_oid = _real.get("orderId")
            if _real_oid:
                _leg.orderId = _real_oid
                _leg.internalTradeId = _real_oid
                # 同步进 _order_lookup 以便后续渲染读取 contractCode/underlying
                _order_lookup[_real_oid] = _real
                _resolved = True
        if not _resolved:
            # 无可用持仓数据 → 清空 LLM 占位文字，避免渲染到回复里
            _leg.orderId = None
            _leg.internalTradeId = None

    # === 客户端预校验 ===
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
            "close_params": validated_close_params(**result.model_dump()),
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

    # === 生成确认卡 ===
    # CLAUDE.md P0: 严禁硬编码业务数据 fallback。无 holding 数据时 underlying/optionType
    # 字段留空（待后端补齐），不要塞默认股票（曾硬编码"000155.SZ 川能动力"）。
    _card_lines = ["以下平仓申请，请核对详情后确认：\n"]
    for _i, _leg in enumerate(close_list, 1):
        _oid = _leg.orderId or _leg.internalTradeId or ""
        _detail = _order_lookup.get(_oid, {})
        _contract = _detail.get("contractCode") or _leg.internalTradeId or ""
        _opt_type = _detail.get("optionType") or ""
        _ucode = _detail.get("underlyingCode") or ""
        _uname = _detail.get("underlyingName") or ""
        _price_type = _leg.closeOrderType or "市价单"
        _amt = _leg.closeOrderNotionalDelta
        _card_lines.append("-----场外期权平仓详情-----\n")
        _card_lines.append(f"序号：{_i}\n")
        _card_lines.append(f"合约编号：{_contract}\n")
        _card_lines.append(f"单号：{_oid}\n")
        if _opt_type:
            _card_lines.append(f"期权类型：{_opt_type}\n")
        if _ucode:
            _card_lines.append(f"标的代码：{_ucode}\n")
        if _uname:
            _card_lines.append(f"标的名称：{_uname}\n")
        _card_lines.append("交易方向：卖出\n")
        if _amt:
            try:
                _card_lines.append(f"平仓名义本金：{int(float(_amt)):,}\n")
            except (ValueError, TypeError):
                _card_lines.append(f"平仓名义本金：{_amt}\n")
        _card_lines.append(f"平仓价格方式：{_price_type}\n")
        if "POV" in str(_price_type).upper():
            _pov = _leg.closeOrderPovRatio
            if _pov is not None:
                _card_lines.append(f"POV比例：{_pov}%\n")
            else:
                _card_lines.append("POV比例：【待补充】\n")
    _card_lines.append("\n若要对以上订单执行平仓操作，请引用本消息回复【确认平仓】")
    _reply = "".join(_card_lines)

    # trace
    types = [item.closeOrderType for item in close_list if item.closeOrderType]
    full_closes = sum(1 for item in close_list if item.confirmFullClose)
    decision = f"orders={len(close_list)}, types={types}, full_close={full_closes}"

    return {
        "close_params": validated_close_params(**result.model_dump()),
        "reply_text": _reply,
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
