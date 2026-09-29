"""Field provenance and locks are enforced before canonical values reach a client."""
import importlib


def fields():
    return importlib.import_module("app.extraction.fields")


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
