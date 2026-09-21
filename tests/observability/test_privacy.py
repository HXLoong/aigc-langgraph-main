"""Telemetry masking is opt-in and only hides the configured fields."""
from __future__ import annotations

import io
import json
import logging
from copy import deepcopy

import pytest

from app.config import Settings
from app.extraction.fields import FieldRecord
from app.observability import privacy


def _settings(**overrides):
    return Settings(
        _env_file=None,
        mysql_uri="mysql+aiomysql://test:test@localhost/test",
        qwen_api_base="http://localhost:9999/v1",
        qwen_api_key="test-key",
        otc_api_base_url="http://localhost:48080",
        otc_api_secret="test-secret",
        **overrides,
    )


def _configure(monkeypatch, *, enabled=False, fields=""):
    settings = _settings(telemetry_masking_enabled=enabled, telemetry_masking_fields=fields)
    monkeypatch.setattr(privacy, "get_settings", lambda: settings, raising=False)
    return settings


def test_masking_settings_default_to_disabled(monkeypatch):
    monkeypatch.delenv("TELEMETRY_MASKING_ENABLED", raising=False)
    monkeypatch.delenv("TELEMETRY_MASKING_FIELDS", raising=False)
    settings = _settings()
    assert getattr(settings, "telemetry_masking_enabled", None) is False


def test_masking_settings_load_from_environment(monkeypatch):
    monkeypatch.setenv("TELEMETRY_MASKING_ENABLED", "true")
    monkeypatch.setenv("TELEMETRY_MASKING_FIELDS", "raw_text, user_id")
    settings = _settings()
    assert getattr(settings, "telemetry_masking_enabled", None) is True
    assert getattr(settings, "telemetry_masking_fields", None) == "raw_text, user_id"


def test_disabled_masking_preserves_input_output_and_prompt(monkeypatch):
    _configure(monkeypatch, fields="raw_text,content,value,exception")
    original = {
        "raw_text": "测试指令 13800138000 demo@example.com",
        "messages": [("system", "系统提示"), ("user", "用户输入")],
        "reply_text": "测试回复",
        "exception": "ValueError: diagnostic detail",
        "field_records": {"amount": FieldRecord(
            value="100万", source="user", evidence="100万", confidence=.9,
        )},
    }
    before = deepcopy(original)
    assert privacy.mask_sensitive(original) == before
    assert original == before


def test_enabled_masking_only_hides_selected_nested_fields(monkeypatch):
    _configure(monkeypatch, enabled=True, fields=" USER_id, api-key, ,privateField,USER_id ")
    original = {
        "raw_text": "测试指令 13800138000 demo@example.com",
        "input": [{"userId": "test-user", "API_KEY": "test-key", "privateField": "hidden"}],
        "messages": [{"role": "user", "content": "测试原文"}],
        "reply_text": "测试回执", "value": "100万",
    }
    before = deepcopy(original)
    result = privacy.mask_sensitive(original)
    assert result["input"] == [{
        "userId": "[redacted]", "API_KEY": "[redacted]", "privateField": "[redacted]",
    }]
    for field in ("raw_text", "messages", "reply_text", "value"):
        assert result[field] == original[field]
    assert original == before


def test_empty_field_list_does_not_mask_anything(monkeypatch):
    _configure(monkeypatch, enabled=True, fields=" , , ")
    original = {"raw_text": "原文", "token": "test-token", "content": "Bearer test-token"}
    assert privacy.mask_sensitive(original) == original


def test_configured_parent_field_hides_the_whole_value(monkeypatch):
    _configure(monkeypatch, enabled=True, fields="sources")
    original = {"sources": {"raw": "原文", "attachment:r1": "附件内容"}, "raw_text": "保留"}
    assert privacy.mask_sensitive(original) == {"sources": "[redacted]", "raw_text": "保留"}


@pytest.mark.parametrize("fields,hidden", [("content", True), ("user_id", False)])
def test_prompt_content_is_only_hidden_when_selected(monkeypatch, fields, hidden):
    _configure(monkeypatch, enabled=True, fields=fields)
    result = privacy.mask_sensitive([("system", "系统提示"), ("user", "用户原文")])
    assert result == [
        ["system", "[redacted]" if hidden else "系统提示"],
        ["user", "[redacted]" if hidden else "用户原文"],
    ]


def test_field_record_values_remain_visible_unless_selected(monkeypatch):
    _configure(monkeypatch, enabled=True, fields="evidence")
    record = FieldRecord(value="100万", source="user", evidence="100万", confidence=.9)
    result = privacy.mask_sensitive({"field_records": {"order.amount": record}})
    assert result["field_records"]["order.amount"]["value"] == "100万"
    assert result["field_records"]["order.amount"]["evidence"] == "[redacted]"
    assert record.evidence == "100万"


def test_flattened_field_paths_match_configured_leaf_names(monkeypatch):
    _configure(monkeypatch, enabled=True, fields="place_order_shortname")
    result = privacy.mask_sensitive({"field_records": {
        "swap/place_order.orderList.0.placeOrderShortname": {"value": "测试对手"},
        "option/orderList.0.accountId": "visible-account",
    }})
    assert result["field_records"]["swap/place_order.orderList.0.placeOrderShortname"] == "[redacted]"
    assert result["field_records"]["option/orderList.0.accountId"] == "visible-account"


@pytest.mark.parametrize("enabled", [False, True])
def test_structured_logging_uses_the_same_switch_and_field_list(monkeypatch, enabled):
    from app.observability import logs

    _configure(monkeypatch, enabled=enabled, fields="user_id")
    stream = io.StringIO()
    root = logging.getLogger()
    old_handlers, old_level = root.handlers[:], root.level
    try:
        logs.configure_logging(fmt="json", stream=stream)
        with logs.bound_request_context(user_id="test-user", raw_text="测试指令"):
            logging.getLogger("privacy-test").warning("诊断信息 demo@example.com")
        record = json.loads(stream.getvalue().strip())
    finally:
        root.handlers[:] = old_handlers
        root.setLevel(old_level)
    assert record["user_id"] == ("[redacted]" if enabled else "test-user")
    assert record["raw_text"] == "测试指令"
    assert record["event"] == "诊断信息 demo@example.com"
