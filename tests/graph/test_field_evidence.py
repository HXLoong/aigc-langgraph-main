"""Field provenance and locks are enforced before canonical values reach a client."""
import importlib

import pytest
from pydantic import ValidationError


def fields():
    return importlib.import_module("app.extraction.fields")


def test_verbatim_candidate_is_checked_against_its_declared_source():
    module = fields()
    candidate = module.FieldCandidate(value="UBS", evidence="向UBS询价", confidence=.9, origin="raw")
    assert candidate.verify({"raw": "请向UBS询价"}) == "UBS"


@pytest.mark.parametrize("value,evidence", [("瑞银", "向UBS询价"), ("UBS", "与UBS成交")])
def test_candidate_cannot_rewrite_a_name_or_invent_evidence(value, evidence):
    candidate = fields().FieldCandidate(value=value, evidence=evidence, confidence=1, origin="raw")
    with pytest.raises(ValueError, match="evidence"):
        candidate.verify({"raw": "请向UBS询价"})


def test_quote_evidence_cannot_be_presented_as_current_user_text():
    module = fields()
    sources = {"raw": "选第二个", "quote": "UBS"}
    candidate = module.FieldCandidate(value="UBS", evidence="UBS", confidence=.9, origin="raw")
    with pytest.raises(ValueError, match="evidence"):
        candidate.verify(sources)
    assert candidate.model_copy(update={"origin": "quote"}).verify(sources) == "UBS"


def test_null_candidate_does_not_invent_a_default():
    candidate = fields().FieldCandidate(value=None, evidence="", confidence=0, origin="raw")
    assert candidate.verify({"raw": "下单"}) is None


def test_confidence_is_bounded_and_does_not_override_evidence():
    module = fields()
    with pytest.raises(ValidationError):
        module.FieldCandidate(value="x", evidence="x", confidence=1.1)


def test_a_number_cannot_be_cut_from_a_larger_numeric_token():
    candidate = fields().FieldCandidate(value="50", evidence="500股", confidence=1, origin="raw")
    with pytest.raises(ValueError, match="evidence"):
        candidate.verify({"raw": "买入500股"})


def test_locked_value_is_retained_and_conflict_is_observable():
    module = fields()
    original = module.FieldRecord(value=100, source="user", evidence="100股", locked=True)
    proposed = module.FieldRecord(value=200, source="inferred", evidence="")
    merged = module.merge_fields({"order-1.quantity": original}, {"order-1.quantity": proposed})
    assert merged["order-1.quantity"].value == 100
    assert merged["order-1.quantity"].rejected_updates == 1
    assert original.rejected_updates == 0


def test_locks_are_scoped_to_order_and_idempotent_updates_are_allowed():
    module = fields()
    original = module.FieldRecord(value=100, source="user", evidence="100股", locked=True)
    other = module.FieldRecord(value=200, source="user", evidence="200股")
    merged = module.merge_fields({"one.quantity": original}, {"one.quantity": original, "two.quantity": other})
    assert merged["one.quantity"].rejected_updates == 0
    assert merged["two.quantity"].value == 200


def test_checkpoint_preserves_field_provenance_and_locks():
    from app.checkpointer.factory import build_checkpoint_serde

    item = fields().FieldRecord(value="600000.SH", source="goats", evidence="backend result", locked=True)
    serde = build_checkpoint_serde()
    result = serde.loads_typed(serde.dumps_typed(item))
    assert result == item


def test_input_state_has_a_reducer_for_field_records():
    from typing import get_type_hints

    from app.graph.state import AgentState

    annotation = get_type_hints(AgentState, include_extras=True)["field_records"]
    assert annotation.__metadata__[0] is fields().merge_fields
