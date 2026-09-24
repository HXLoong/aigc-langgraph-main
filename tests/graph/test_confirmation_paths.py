from importlib import import_module
from unittest.mock import AsyncMock

import pytest

H = "H-20260920-1234567890"
Q = "Q-20260920-1234567890"
CO = "CO-20260920-ABCDEF12"
PATHS = [
    ("swap.confirm", "swap_confirm", "call_swap_backend", "confirm_order", "确认下单", H),
    ("swap.confirm", "swap_confirm", "call_swap_backend", "confirm_cancel_order", "确认撤单", H),
    ("swap.confirm", "swap_confirm", "call_swap_backend", "confirm_modify_order", "确认修改", H),
    (
        "option.extract_confirm_place",
        "option_extract_confirm_place",
        "call_option_backend",
        "confirm_order",
        "确认订单",
        Q,
    ),
    (
        "option.extract_confirm_cancel",
        "option_extract_confirm_cancel",
        "call_option_backend",
        "confirm_cancel_order",
        "撤单确认",
        Q,
    ),
    (
        "close.confirm_close",
        "close_confirm_close",
        "call_close_backend",
        "close_order_confirm",
        "确定平仓",
        CO,
    ),
    (
        "close.confirm_cancel",
        "close_confirm_cancel",
        "call_close_backend",
        "close_order_cancel_confirm",
        "确认取消",
        CO,
    ),
]


@pytest.mark.parametrize("module_name,node_name,backend_name,intent,action,oid", PATHS)
@pytest.mark.parametrize(
    "bad",
    [
        "确认",
        "好的",
        "可以",
        "没问题",
        "-",
        "不{action}",
        "{action}吗",
        "如果可以就{action}",
        "missing_quote",
    ],
)
async def test_all_confirmation_paths_reject_unsafe_commands(
    monkeypatch,
    module_name,
    node_name,
    backend_name,
    intent,
    action,
    oid,
    bad,
):
    module = import_module("app.subgraphs." + module_name)
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "真实回执"})
    monkeypatch.setattr(module, backend_name, backend)
    result = await getattr(module, node_name)(
        {
            "raw_text": action if bad == "missing_quote" else bad.format(action=action),
            "quote_content": "" if bad == "missing_quote" else f"序号1：{oid}",
            "intent": intent,
            "last_confirmed_params": {"order_ids": [oid]},
        }
    )
    backend.assert_not_awaited()
    assert result.get("reply_text") and not result.get("error")


@pytest.mark.parametrize("module_name,node_name,backend_name,intent,action,oid", PATHS)
async def test_all_confirmation_paths_accept_alias_and_single_quoted_order(
    monkeypatch,
    module_name,
    node_name,
    backend_name,
    intent,
    action,
    oid,
):
    module = import_module("app.subgraphs." + module_name)
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "真实回执"})
    monkeypatch.setattr(module, backend_name, backend)
    result = await getattr(module, node_name)(
        {
            "raw_text": action,
            "quote_content": f"单号：{oid}",
            "intent": intent,
        }
    )
    assert result.get("api_result") == "真实回执", result
    assert backend.await_count == 1


@pytest.mark.parametrize(
    "command",
    [
        "序号1、序号1，确认下单",
        "序号3，确认下单",
        "H-20260920-9999999999，确认下单",
        f"序号2，{H}，确认下单",
    ],
)
async def test_swap_confirmation_scope_cannot_expand_or_conflict(monkeypatch, command):
    module = import_module("app.subgraphs.swap.confirm")
    backend = AsyncMock()
    monkeypatch.setattr(module, "call_swap_backend", backend)
    result = await module.swap_confirm(
        {
            "intent": "confirm_order",
            "raw_text": command,
            "quote_content": f"序号1：{H}\n序号2：H-20260920-2222222222",
        }
    )
    backend.assert_not_awaited()
    assert result.get("reply_text")


@pytest.mark.parametrize(
    "module_name,intent,raw",
    [
        ("option", "confirm_order", "确定下单"),
        ("option", "confirm_cancel_order", "确认取消"),
        ("swap", "confirm_modify_order", "修改确认"),
        ("swap", "confirm_cancel_order", "撤单确认"),
        ("close", "close_order_confirm", "序号1，确认平仓"),
        ("close", "close_order_request", "确认平仓，200万，限价10"),
        ("close", "close_order_request", "确认平仓，TWAP30分钟"),
        ("close", "close_order_cancel_confirm", "确定撤单"),
        ("option", "unknown_intent", "-"),
        ("swap", "unknown_intent", "如果可以就确认修改"),
    ],
)
async def test_confirmation_routing_is_deterministic(monkeypatch, module_name, intent, raw):
    module = import_module(f"app.subgraphs.{module_name}.intent")
    from unittest.mock import Mock

    for factory in ("get_qwen_thinking", "get_qwen_structured"):
        if hasattr(module, factory):
            monkeypatch.setattr(
                module, factory, Mock(side_effect=AssertionError("must not use LLM"))
            )
    node = getattr(module, f"{'close' if module_name == 'close' else module_name}_intent")
    result = await node({"raw_text": raw})
    assert result.get("intent") == intent, result


def test_quote_footer_examples_do_not_change_scope():
    from app.domain.confirmation import parse_confirmation

    quote = f"序号1：{H}\n如只确认部分订单，请引用回复【序号2、序号4，确认下单】。"
    assert parse_confirmation("序号1，确认下单", quote).order_ids == (H,)


def test_multiple_mappings_on_one_line():
    from app.domain.confirmation import parse_confirmation

    quote = f"序号1：{H}；序号2：H-20260920-2222222222"
    result = parse_confirmation("序号2，确认下单", quote)
    assert result.order_ids == ("H-20260920-2222222222",)


async def test_option_subset_confirmation_preserves_shared_parameters(monkeypatch):
    module = import_module("app.subgraphs.option.extract_confirm_place")
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "真实回执"})
    monkeypatch.setattr(module, "call_option_backend", backend)
    second = "Q-20260920-2222222222"
    result = await module.option_extract_confirm_place(
        {
            "raw_text": "确认下单，序号2，限价10",
            "quote_content": f"序号1：{Q}\n序号2：{second}",
        }
    )
    assert not result.get("error")
    assert backend.await_count == 1, result
    assert [o["orderId"] for o in backend.await_args.kwargs["order_list"]] == [second]
    assert backend.await_args.kwargs["order_list"][0]["limitPrice"] == 10


@pytest.mark.parametrize(
    "raw",
    [
        "确认下单，涨到100万再执行",
        "确认下单，限价10，然后撤单",
        "确认下单确认下单",
        "确认下单，限价10，交易对手A然后撤单",
    ],
)
async def test_option_parameter_confirmation_cannot_hide_another_action(monkeypatch, raw):
    module = import_module("app.subgraphs.option.extract_confirm_place")
    backend = AsyncMock()
    monkeypatch.setattr(module, "call_option_backend", backend)
    result = await module.option_extract_confirm_place({"raw_text": raw, "quote_content": Q})
    backend.assert_not_awaited()
    assert result.get("reply_text")


@pytest.mark.parametrize("marker", ["序号+1", "序号01", "序号一"])
def test_swap_single_order_does_not_repair_invalid_quote_sequence(marker):
    from app.domain.confirmation import parse_confirmation

    result = parse_confirmation("序号1，确认下单", f"{marker}：{H}")
    assert result.error and not result.order_ids


@pytest.mark.parametrize("module_name,node_name,backend_name,intent,action,oid", PATHS)
async def test_existing_field_lock_cannot_redirect_confirmation(
    monkeypatch, module_name, node_name, backend_name, intent, action, oid,
):
    from app.extraction.fields import FieldRecord
    module = import_module("app.subgraphs." + module_name)
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "真实回执"})
    monkeypatch.setattr(module, backend_name, backend)
    scope = {
        "swap.confirm": "swap/confirm.orderList.0.orderId",
        "option.extract_confirm_place": "option/confirm_place.orderList.0.orderId",
        "option.extract_confirm_cancel": "option/confirm_cancel.orderList.0.orderId",
        "close.confirm_close": "close/confirm.confirmOrderNoList.0",
        "close.confirm_cancel": "close/confirm_cancel.confirmCancelOrderNoList.0",
    }[module_name]
    foreign = oid.rsplit("-", 1)[0] + "-9999999999"
    result = await getattr(module, node_name)({
        "raw_text": action, "quote_content": oid, "intent": intent,
        "field_records": {scope: FieldRecord(value=foreign, source="user", locked=True)},
    })
    backend.assert_not_awaited()
    assert result.get("reply_text") or result.get("error")
