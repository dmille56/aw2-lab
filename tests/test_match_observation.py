"""ROM-independent tests for command-boundary identity and revision tracking."""

from dataclasses import replace
from struct import pack_into
from uuid import uuid4

import pytest
from test_state_validation import memory as memory  # noqa: PLC0414 -- re-export pytest fixture
from test_state_validation import snapshot

from aw2_lab.match_observation import (
    ActionReadiness,
    IdentityStatus,
    MatchObservationMetadata,
    MatchObservationTracker,
    RevisionCause,
    ScreenshotReference,
)
from aw2_lab.state_decoder import decode_snapshot
from aw2_lab.state_model import ObservedValue, ValueStatus


def decode(memory, frame: int = 123):
    return decode_snapshot(replace(snapshot(memory), frame=frame))


def test_match_observations_attach_identity_revision_and_read_without_mutation(memory) -> None:
    tracker = MatchObservationTracker(uuid4())
    first = tracker.commit_boundary(decode(memory))
    first_ids = {unit.reference: unit.identity_id for unit in first.unit_identities}

    _, ewram, _ = memory
    ewram[0x22692] = 1  # The first unit moved; its slot and type are unchanged.
    moved = tracker.commit_boundary(decode(memory, 124))
    moved_ids = {unit.reference: unit.identity_id for unit in moved.unit_identities}

    assert moved.match_id == first.match_id
    assert moved.revision == first.revision + 1
    assert moved_ids == first_ids
    assert moved.action_readiness is ActionReadiness.READY
    assert tracker.read() is moved
    assert tracker.revision == moved.revision
    assert ScreenshotReference.for_observation(moved) == ScreenshotReference(
        moved.match_id, moved.revision, moved.game_state.frame
    )


def test_destroyed_and_reused_slot_gets_new_public_identity(memory) -> None:
    tracker = MatchObservationTracker(uuid4())
    original = tracker.commit_boundary(decode(memory))
    original_id = next(item.identity_id for item in original.unit_identities if item.reference == 1)

    _, ewram, _ = memory
    ewram[0x22690] = 0
    absent = tracker.commit_boundary(decode(memory, 124))
    assert 1 not in {item.reference for item in absent.unit_identities}

    ewram[0x22690] = 1
    replacement = tracker.commit_boundary(decode(memory, 125))
    replacement_id = next(
        item.identity_id for item in replacement.unit_identities if item.reference == 1
    )
    assert replacement_id != original_id


def test_checkpoint_restores_identity_and_advances_past_durable_revision(memory) -> None:
    tracker = MatchObservationTracker(uuid4())
    committed = tracker.commit_boundary(decode(memory))
    identity_ids = {item.reference: item.identity_id for item in committed.unit_identities}
    metadata = MatchObservationMetadata.from_dict(tracker.checkpoint_metadata().to_dict())
    restored = MatchObservationTracker.from_checkpoint(metadata, durable_revision_floor=8)

    assert restored.revision == 9
    with pytest.raises(ValueError, match="cause=RESTORE"):
        restored.commit_boundary(decode(memory))

    after_restore = restored.commit_boundary(decode(memory), cause=RevisionCause.RESTORE)
    assert after_restore.revision == 9
    assert {
        item.reference: item.identity_id for item in after_restore.unit_identities
    } == identity_ids
    after_command = restored.commit_boundary(decode(memory, 124))
    assert after_command.revision == 10


def test_debug_mutation_and_rollback_invalidate_revisions_even_at_same_frame(memory) -> None:
    tracker = MatchObservationTracker(uuid4())
    first = tracker.commit_boundary(decode(memory))
    debug = tracker.commit_boundary(decode(memory), cause=RevisionCause.DEBUG_MUTATION)
    rollback = tracker.commit_boundary(decode(memory), cause=RevisionCause.ROLLBACK)

    assert (first.revision, debug.revision, rollback.revision) == (1, 2, 3)


def test_unavailable_boundary_invalidates_identity_continuity(memory) -> None:
    tracker = MatchObservationTracker(uuid4())
    tracker.commit_boundary(decode(memory))
    state = decode(memory, 124)
    blocked = replace(
        state,
        battle=ObservedValue(ValueStatus.UNKNOWN, None, ("fixture unavailable",)),
    )

    with pytest.raises(ValueError, match="validated live battle data"):
        tracker.commit_boundary(blocked)
    assert not tracker.continuity_valid
    with pytest.raises(RuntimeError, match="continuity is unknown"):
        tracker.commit_boundary(decode(memory, 125))


def test_terminal_result_commits_without_publishing_retained_unit_state(memory) -> None:
    tracker = MatchObservationTracker(uuid4())
    tracker.commit_boundary(decode(memory))
    _, ewram, _ = memory
    pack_into("<I", ewram, 0xD610, 0x0849D56C)
    result = decode(memory, 124)

    terminal = tracker.commit_terminal_boundary(result)

    assert terminal.revision == 2
    assert terminal.game_state is result
    assert terminal.identity_status is IdentityStatus.UNAVAILABLE
    assert terminal.unit_identities == ()
    assert terminal.action_readiness is ActionReadiness.UNKNOWN
    assert tracker.read() is terminal
