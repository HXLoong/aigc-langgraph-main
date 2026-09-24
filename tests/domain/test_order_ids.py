"""app/domain/order_ids.py：订单号形态单一来源，且各使用点共享同一对象。"""
from __future__ import annotations

from app.domain import order_ids as ids


def test_canonical_shapes() -> None:
    assert ids.SWAP_ORDER_ID_RE.fullmatch("H-20260917-0000000001")
    assert not ids.SWAP_ORDER_ID_RE.fullmatch("H-20260917-001")
    assert ids.OPTION_ORDER_ID_RE.fullmatch("Q-20260917-AB12")
    assert ids.CLOSE_ORDER_ID_RE.fullmatch("co-20260917-abcd1234")
    assert ids.CONTRACT_CODE_RE.fullmatch("OPTG-SZZSCF20260009")


def test_bounded_option_id_is_not_cut_from_longer_token() -> None:
    assert not ids.OPTION_ORDER_ID_RE.search("XQ-20260917-AB12")
    assert not ids.OPTION_ORDER_ID_RE.search("Q-20260917-AB12-9")


def test_any_order_id_covers_three_products() -> None:
    text = "H-20260917-0000000001 Q-20260917-AB12 CO-20260917-ABCD1234"
    assert [m[0] for m in ids.ANY_ORDER_ID_RE.finditer(text)] == text.split()


def test_route_shapes_stay_narrower_than_canonical() -> None:
    """路由规则只认历史窄形态：Q- 需 10 位数字，CO- 需 8 位十六进制。"""
    import re

    assert re.search(ids.ROUTE_OPTION_OPEN_ORDER, "Q-20260917-0000000001")
    assert not re.search(ids.ROUTE_OPTION_OPEN_ORDER, "Q-20260917-AB12")
    assert re.search(ids.ROUTE_OPTION_CLOSE_ORDER, "CO-20260917-ABCD1234")
    assert not re.search(ids.ROUTE_OPTION_CLOSE_ORDER, "CO-20260917-abcd")


def test_modules_share_domain_patterns() -> None:
    from app.domain import confirmation
    from app.nodes import pre_route, remember_confirmed, route_rules
    from app.subgraphs.close import order_id as close_ids
    from app.subgraphs.option import order_scope
    from app.subgraphs.swap import order_id as swap_ids

    assert swap_ids.ORDER_ID_RE is ids.SWAP_ORDER_ID_RE
    assert pre_route._ORDER_ID_RE is ids.SWAP_ORDER_ID_RE
    assert order_scope.ORDER_ID_RE is ids.OPTION_ORDER_ID_RE
    assert close_ids.ORDER_ID_RE is ids.CLOSE_ORDER_ID_RE
    assert confirmation._IDS is ids.ANY_ORDER_ID_RE
    assert route_rules.SWAP_ORDER_PATTERN == ids.ROUTE_SWAP_ORDER
    assert remember_confirmed.ORDER_ID_RE_BY_PRODUCT is ids.ORDER_ID_RE_BY_PRODUCT


def test_main_graph_nodes_do_not_import_subgraphs() -> None:
    """主图收尾节点不反向依赖子图内部模块。"""
    import ast
    from pathlib import Path

    for path in (Path(__file__).resolve().parents[2] / "app" / "nodes").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        assert not [m for m in modules if m.startswith("app.subgraphs")], path
