"""节点注册表冒烟守护：注册表与主入口必须能在没有任何外部依赖时 import。

背景：2026-09-20 标的识别委托后端后 `app.subgraphs.ticker` 被删除，
但 `app/node_execution/registry.py` 仍直接 import 它，导致 `app.main`
无法导入而 CI 未触发无人发现。本文件把"注册表可导入、命名空间集合稳定、
每个注册项的 action 都是真实可调用对象"钉成契约。
"""
from __future__ import annotations

import importlib

from app.node_execution.registry import build_registry

EXPECTED_PRODUCTS = {"main", "swap", "option", "option_close"}


def test_app_main_is_importable() -> None:
    module = importlib.import_module("app.main")
    assert hasattr(module, "app")


def test_registry_products_are_stable_and_actions_callable() -> None:
    registrations = build_registry()
    assert {r.product for r in registrations} == EXPECTED_PRODUCTS
    for registration in registrations:
        assert callable(registration.action), (registration.product, registration.name)
        module = importlib.import_module(registration.action.__module__)
        assert module is not None, registration.action.__module__
