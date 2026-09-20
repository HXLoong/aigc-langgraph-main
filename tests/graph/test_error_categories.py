import pytest

from app.graph.state import ErrorInfo


@pytest.mark.parametrize("kind,code", [
    ("APITimeoutError", "E1"), ("EvidenceError", "E2"), ("ValidationError", "E2"),
    ("ValueError", "E3"), ("BackendUnreachableError", "E4"), ("WorkflowTimeout", "E5"),
])
def test_errors_have_a_stable_category(kind, code):
    error = ErrorInfo(node="node", type=kind, message="private detail")
    assert error.code == code


def test_wire_error_has_no_internal_detail():
    from app.api.routes import _state_to_outputs
    output = _state_to_outputs({"error": ErrorInfo(node="extract", type="ValidationError", message="secret-value")})
    assert output["error"]["code"] == "E2"
    assert "secret-value" not in str(output)
