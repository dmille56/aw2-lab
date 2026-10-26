"""ROM-independent checks for slot-based unit identity bookkeeping."""

import pytest

from aw2_lab.unit_identity import (
    UnitIdentity,
    UnitIdentityMetadata,
    UnitIdentityTracker,
    UnitObservation,
)


def unit(reference: int, unit_type: int = 1, x: int = 0, y: int = 0) -> UnitObservation:
    return UnitObservation(reference=reference, unit_type=unit_type, x=x, y=y)


def test_movement_preserves_identity() -> None:
    tracker = UnitIdentityTracker()
    first = tracker.reconcile([unit(1, x=1, y=4)])[1]
    moved = tracker.reconcile([unit(1, x=8, y=6)])[1]

    assert moved == first


def test_observed_empty_slot_then_same_type_purchase_gets_new_identity() -> None:
    tracker = UnitIdentityTracker()
    original = tracker.reconcile([unit(1, unit_type=7)])[1]
    assert tracker.reconcile([]) == {}
    replacement = tracker.reconcile([unit(1, unit_type=7)])[1]

    assert replacement.reference == original.reference
    assert replacement.identity_id != original.identity_id
    assert replacement.generation == original.generation + 1


def test_type_change_in_occupied_slot_starts_new_lifetime() -> None:
    tracker = UnitIdentityTracker()
    original = tracker.reconcile([unit(65, unit_type=1)])[65]
    replacement = tracker.reconcile([unit(65, unit_type=2)])[65]

    assert replacement.identity_id != original.identity_id
    assert replacement.generation == 2


def test_checkpoint_round_trip_preserves_ids_and_tombstones() -> None:
    tracker = UnitIdentityTracker()
    active = tracker.reconcile([unit(1), unit(65, unit_type=2)])
    tracker.reconcile([unit(1, x=3)])
    checkpoint = UnitIdentityMetadata.from_dict(tracker.checkpoint_metadata().to_dict())
    restored = UnitIdentityTracker.from_checkpoint(checkpoint)

    after_restore = restored.reconcile([unit(1, x=4), unit(65, unit_type=2)])
    assert after_restore[1] == active[1]
    assert after_restore[65] != active[65]

    replacement = restored.reconcile([unit(1), unit(65, unit_type=2), unit(2)])[2]
    assert replacement.identity_id > active[65].identity_id


def test_type_change_without_observed_gap_is_detectable_but_same_type_gap_is_not() -> None:
    tracker = UnitIdentityTracker()
    first = tracker.reconcile([unit(1, unit_type=1)])[1]
    changed_type = tracker.reconcile([unit(1, unit_type=2)])[1]
    same_type_again = tracker.reconcile([unit(1, unit_type=2)])[1]

    assert changed_type.identity_id != first.identity_id
    assert same_type_again == changed_type


@pytest.mark.parametrize("reference", [0, 51, 64, 115, 255])
def test_observation_rejects_non_allocator_slots(reference: int) -> None:
    with pytest.raises(ValueError, match="reference"):
        unit(reference)


def test_reconcile_rejects_duplicate_references_without_changing_history() -> None:
    tracker = UnitIdentityTracker()
    tracker.reconcile([unit(1), unit(65)])
    tracker.reconcile([unit(1)])
    before = tracker.checkpoint_metadata()

    with pytest.raises(ValueError, match="Duplicate active unit reference"):
        tracker.reconcile([unit(1, unit_type=2), unit(2), unit(2, unit_type=2)])

    assert tracker.checkpoint_metadata() == before
    control = UnitIdentityTracker.from_checkpoint(before)
    following_snapshot = [unit(1), unit(2), unit(65)]
    assert tracker.reconcile(following_snapshot) == control.reconcile(following_snapshot)


def test_identity_metadata_rejects_corrupt_or_unsupported_data() -> None:
    with pytest.raises(ValueError, match="Unsupported unit-identity schema"):
        UnitIdentityMetadata(2, 1, ())

    with pytest.raises(ValueError, match="must be an integer"):
        UnitIdentityMetadata.from_dict({"schema_version": 1, "next_identity_id": True, "slots": []})


@pytest.mark.parametrize(
    ("field", "message"),
    [("reference", "Duplicate slot reference"), ("identity_id", "Duplicate identity ID")],
)
def test_checkpoint_metadata_rejects_duplicate_references_or_ids(field: str, message: str) -> None:
    tracker = UnitIdentityTracker()
    tracker.reconcile([unit(1), unit(65)])
    payload = tracker.checkpoint_metadata().to_dict()
    slots = payload["slots"]
    assert isinstance(slots, list)
    slots[1][field] = slots[0][field]

    with pytest.raises(ValueError, match=message):
        UnitIdentityMetadata.from_dict(payload)


@pytest.mark.parametrize("generation", [0, -1, True, 1.5, "1", None])
def test_checkpoint_metadata_rejects_invalid_generations(generation: object) -> None:
    tracker = UnitIdentityTracker()
    tracker.reconcile([unit(1)])
    payload = tracker.checkpoint_metadata().to_dict()
    slots = payload["slots"]
    assert isinstance(slots, list)
    slots[0]["generation"] = generation

    with pytest.raises(ValueError, match="positive|must be an integer"):
        UnitIdentityMetadata.from_dict(payload)


@pytest.mark.parametrize("next_identity_id", [1, 2])
def test_checkpoint_metadata_rejects_next_id_collisions(next_identity_id: int) -> None:
    tracker = UnitIdentityTracker()
    tracker.reconcile([unit(1), unit(65)])
    tracker.reconcile([unit(1)])
    payload = tracker.checkpoint_metadata().to_dict()
    payload["next_identity_id"] = next_identity_id

    with pytest.raises(ValueError, match="must exceed every allocated identity"):
        UnitIdentityMetadata.from_dict(payload)


def test_reconciliation_allocates_different_ids_to_different_slots() -> None:
    identities = UnitIdentityTracker().reconcile([unit(1), unit(2)])

    assert identities[1].identity_id != identities[2].identity_id
    assert isinstance(identities[1], UnitIdentity)
