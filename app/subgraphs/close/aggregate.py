"""平仓参数的接口字段映射，不实现业务清洗或默认值。"""
from __future__ import annotations

from typing import Any


def build_close_order_req_vo(
    *,
    close_order_list: list[dict[str, Any]] | None = None,
    ins_family_list: list[str] | None = None,
    contract_type_list: list[str] | None = None,
    closeable_only: bool | None = None,
    confirm_order_no_list: list[str] | None = None,
    cancel_order_no_list: list[str] | None = None,
    confirm_cancel_order_no_list: list[str] | None = None,
    internal_trade_id_list: list[str] | None = None,
    query_order_no_list: list[str] | None = None,
    key_ctpty_id_list: list[int] | None = None,
    underlying_ins_id_list: list[str] | None = None,
    underlying_ins_name_list: list[str] | None = None,
) -> dict[str, Any]:
    """按 Java 字段名装配本次参数，未提供的字段不填默认值。"""
    # 1. 过滤条件只做字段映射，空列表和 false 若明确提供仍保留。
    filters = {
        "insFamilyList": ins_family_list,
        "contractTypeList": contract_type_list,
        "allowCloseOut": closeable_only,
        "internalTradeIdList": internal_trade_id_list,
        "keyCtptyIdList": key_ctpty_id_list,
        "underlyingInsIdList": underlying_ins_id_list,
        "underlyingInsNameList": underlying_ins_name_list,
    }
    query = {key: value for key, value in filters.items() if value is not None}
    # 2. 各动作只带自己使用的身份或订单列表，不构造其它动作的空参数。
    payload: dict[str, Any] = {
        "closeOrderList": close_order_list,
        "confirmOrderNoList": confirm_order_no_list,
        "cancelOrderNoList": cancel_order_no_list,
        "confirmCancelOrderNoList": confirm_cancel_order_no_list,
        "queryOrderNoList": query_order_no_list,
    }
    if query:
        payload["contractQuery"] = query
    return {key: value for key, value in payload.items() if value is not None}
