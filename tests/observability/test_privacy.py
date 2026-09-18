"""Telemetry must not export the customer's message or credentials."""
import importlib
import io
import logging


def test_nested_span_mask_preserves_diagnostics_without_private_messages():
    module = importlib.import_module("app.observability.privacy")
    original = {"input": {"raw_text": "客户账户原话", "user_id": "123456", "token": "secret"},
                "output": {"intent": "confirm_order", "api_code": 0},
                "messages": [{"role": "user", "content": "客户原话"}]}
    masked = module.mask_sensitive(original)
    assert "客户" not in str(masked) and "secret" not in str(masked) and "123456" not in str(masked)
    assert masked["output"]["api_code"] == 0
    assert masked["output"]["intent"] == "confirm_order"
    assert original["input"]["raw_text"] == "客户账户原话"


def test_configured_logging_redacts_sensitive_arguments():
    from app.observability.logs import configure_logging
    stream = io.StringIO()
    configure_logging(stream=stream)
    logging.getLogger("privacy-test").warning("Authorization: Bearer %s contact %s", "private-key", "13800138000")
    line = stream.getvalue()
    assert "private-key" not in line and "13800138000" not in line
    assert "privacy-test" in line
