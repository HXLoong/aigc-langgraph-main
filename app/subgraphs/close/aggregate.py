"""close 子图 · 参数聚合 + 前置清洗（纯函数，进后端前调用）。

Dify 原节点：
- `期权平仓-参数聚合`（code）：把 6 个分支各自的 LLM/规则输出统一整形为
  `closeOrderReqVO` 对象（`contractQuery` + 5 个订单号列表 + closeOrderList）。
- `期权平仓-前置清洗`（code）：递归清洗 LLM 脏值——字符串字面量 "null"（大小写不敏感，
  可用环境变量 NULL_LITERALS 覆盖）替换为 None；列表中被清成 None 的元素丢弃。

两者都是纯函数，无 IO；由 `close/backend.py` 在调用真后端前串联执行。
"""
from __future__ import annotations

import os
from typing import Any

_DEFAULT_NULL_LITERALS = frozenset({"null"})


def _clean_str_list(values: list[Any] | None) -> list[str]:
    return [v for v in (values or []) if isinstance(v, str) and v.strip()]


def _clean_obj_list(values: list[Any] | None) -> list[dict[str, Any]]:
    return [v for v in (values or []) if isinstance(v, dict)]


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
    """期权平仓-参数聚合（1:1 移植）。

    close 子图 6 个意图分支中，每个分支只填自己相关的字段，其余留空/默认——
    与 Dify 用 variable-aggregator 汇合 6 条分支后再跑本节点行为等价（因为
    LangGraph 路由每轮只会走 1 个分支，其余分支的变量在 Dify 侧本就是空）。
    """
    return {
        "contractQuery": {
            "insFamilyList": _clean_str_list(ins_family_list),
            "contractTypeList": _clean_str_list(contract_type_list),
            "allowCloseOut": True if closeable_only is None else closeable_only,
            "internalTradeIdList": _clean_str_list(internal_trade_id_list),
            "keyCtptyIdList": list(key_ctpty_id_list or []),
            "underlyingInsIdList": _clean_str_list(underlying_ins_id_list),
            "underlyingInsNameList": _clean_str_list(underlying_ins_name_list),
        },
        "closeOrderList": _clean_obj_list(close_order_list),
        "confirmOrderNoList": _clean_str_list(confirm_order_no_list),
        "cancelOrderNoList": _clean_str_list(cancel_order_no_list),
        "confirmCancelOrderNoList": _clean_str_list(confirm_cancel_order_no_list),
        "queryOrderNoList": _clean_str_list(query_order_no_list),
    }


def _parse_null_literals(null_literals: str | None) -> frozenset[str]:
    try:
        raw = null_literals if null_literals is not None else os.environ.get("NULL_LITERALS", "")
        literals = {x.strip().lower() for x in (raw or "").split(",") if x.strip()}
        return frozenset(literals) or _DEFAULT_NULL_LITERALS
    except Exception:  # noqa: BLE001
        return _DEFAULT_NULL_LITERALS


def _sanitize(value: Any, literals: frozenset[str]) -> Any:
    if isinstance(value, str):
        return None if value.strip().lower() in literals else value
    if isinstance(value, list):
        return [c for c in (_sanitize(i, literals) for i in value) if c is not None]
    if isinstance(value, dict):
        return {k: _sanitize(v, literals) for k, v in value.items()}
    return value


def sanitize_close_order_req_vo(
    close_order_req_vo: dict[str, Any], null_literals: str | None = None
) -> dict[str, Any]:
    """期权平仓-前置清洗（1:1 移植）。递归清洗 null 字面量字符串 -> None。"""
    literals = _parse_null_literals(null_literals)
    cleaned = _sanitize(close_order_req_vo, literals)
    return cleaned if isinstance(cleaned, dict) else {}


__all__ = ["build_close_order_req_vo", "sanitize_close_order_req_vo"]
