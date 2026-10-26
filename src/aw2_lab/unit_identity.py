"""Checkpointable host-side identities for reusable AW2 unit-table slots."""

# Malformed checkpoint fields consistently raise ValueError, including invalid types.
# ruff: noqa: TRY004

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

IDENTITY_SCHEMA_VERSION = 1
ARMY_BLOCK_SIZE = 64
ARMY_COUNT = 4
ACTIVE_SLOTS_PER_ARMY = 50


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_reference(reference: int) -> bool:
    return (
        _is_int(reference)
        and 0 < reference < ARMY_BLOCK_SIZE * ARMY_COUNT
        and 1 <= reference % ARMY_BLOCK_SIZE <= ACTIVE_SLOTS_PER_ARMY
    )


@dataclass(frozen=True, slots=True)
class UnitObservation:
    """Verified fields from one active unit record at a snapshot boundary."""

    reference: int
    unit_type: int
    x: int
    y: int

    def __post_init__(self) -> None:
        if not _valid_reference(self.reference):
            raise ValueError(f"Unit reference is outside the usable table slots: {self.reference}")
        if not _is_int(self.unit_type) or not 1 <= self.unit_type <= 0xFF:
            raise ValueError("Unit type must be a nonzero byte")
        if (
            not _is_int(self.x)
            or not _is_int(self.y)
            or not 0 <= self.x <= 0xFF
            or not 0 <= self.y <= 0xFF
        ):
            raise ValueError("Unit coordinates must be bytes")


@dataclass(frozen=True, slots=True)
class UnitIdentity:
    """Identity of one unit lifetime, distinct from its reusable table slot."""

    identity_id: int
    reference: int
    generation: int


@dataclass(frozen=True, slots=True)
class UnitSlotMetadata:
    """Latest observed occupant of a slot, retained as a tombstone when inactive."""

    reference: int
    unit_type: int
    identity_id: int
    generation: int
    active: bool


@dataclass(frozen=True, slots=True)
class UnitIdentityMetadata:
    """JSON-compatible identity state to store alongside an emulator checkpoint."""

    schema_version: int
    next_identity_id: int
    slots: tuple[UnitSlotMetadata, ...]

    def __post_init__(self) -> None:
        if not _is_int(self.schema_version):
            raise ValueError("Unit-identity schema version must be an integer")
        if self.schema_version != IDENTITY_SCHEMA_VERSION:
            raise ValueError(f"Unsupported unit-identity schema: {self.schema_version}")
        if not _is_int(self.next_identity_id) or self.next_identity_id < 1:
            raise ValueError("Next identity ID must be positive")
        references: set[int] = set()
        identities: set[int] = set()
        for slot in self.slots:
            if not _valid_reference(slot.reference):
                raise ValueError(f"Invalid slot reference in metadata: {slot.reference}")
            if slot.reference in references:
                raise ValueError(f"Duplicate slot reference in metadata: {slot.reference}")
            if not _is_int(slot.unit_type) or not 1 <= slot.unit_type <= 0xFF:
                raise ValueError("Metadata unit type must be a nonzero byte")
            if (
                not _is_int(slot.identity_id)
                or not _is_int(slot.generation)
                or slot.identity_id < 1
                or slot.generation < 1
            ):
                raise ValueError("Identity IDs and generations must be positive")
            if not isinstance(slot.active, bool):
                raise ValueError("Metadata active state must be a boolean")
            if slot.identity_id in identities:
                raise ValueError(f"Duplicate identity ID in metadata: {slot.identity_id}")
            references.add(slot.reference)
            identities.add(slot.identity_id)
        if identities and self.next_identity_id <= max(identities):
            raise ValueError("Next identity ID must exceed every allocated identity")

    def to_dict(self) -> dict[str, object]:
        """Return primitive data suitable for a checkpoint JSON document."""
        return {
            "schema_version": self.schema_version,
            "next_identity_id": self.next_identity_id,
            "slots": [
                {
                    "reference": slot.reference,
                    "unit_type": slot.unit_type,
                    "identity_id": slot.identity_id,
                    "generation": slot.generation,
                    "active": slot.active,
                }
                for slot in self.slots
            ],
        }

    @classmethod
    def from_dict(cls, value: object) -> UnitIdentityMetadata:
        """Parse and validate identity metadata loaded from a checkpoint."""
        if not isinstance(value, Mapping):
            raise ValueError("Unit-identity metadata must be an object")
        schema_version = _required_int(value, "schema_version")
        next_identity_id = _required_int(value, "next_identity_id")
        raw_slots = value.get("slots")
        if not isinstance(raw_slots, list):
            raise ValueError("Unit-identity metadata slots must be a list")
        slots: list[UnitSlotMetadata] = []
        for index, raw_slot in enumerate(raw_slots):
            if not isinstance(raw_slot, Mapping):
                raise ValueError(f"Unit-identity slot {index} must be an object")
            active = raw_slot.get("active")
            if not isinstance(active, bool):
                raise ValueError(f"Unit-identity slot {index} active must be a boolean")
            slots.append(
                UnitSlotMetadata(
                    reference=_required_int(raw_slot, "reference"),
                    unit_type=_required_int(raw_slot, "unit_type"),
                    identity_id=_required_int(raw_slot, "identity_id"),
                    generation=_required_int(raw_slot, "generation"),
                    active=active,
                )
            )
        return cls(schema_version, next_identity_id, tuple(slots))


def _required_int(value: Mapping[str, object], name: str) -> int:
    result = value.get(name)
    if isinstance(result, bool) or not isinstance(result, int):
        raise ValueError(f"Unit-identity metadata {name} must be an integer")
    return result


class UnitIdentityTracker:
    """Assign persistent IDs while treating unit-table references as reusable slots.

    Call :meth:`reconcile` only with a complete set of active units from a validated
    battle snapshot. An observed empty slot followed by a unit is a new lifetime.
    A type change in an occupied slot also starts a new lifetime. Movement and other
    mutable fields do not affect identity.
    """

    def __init__(self, metadata: UnitIdentityMetadata | None = None) -> None:
        self._next_identity_id = 1
        self._slots: dict[int, UnitSlotMetadata] = {}
        if metadata is not None:
            self._next_identity_id = metadata.next_identity_id
            self._slots = {slot.reference: slot for slot in metadata.slots}

    def reconcile(self, observations: Iterable[UnitObservation]) -> dict[int, UnitIdentity]:
        """Reconcile one complete snapshot and return identities for active units."""
        by_reference: dict[int, UnitObservation] = {}
        for observation in observations:
            if observation.reference in by_reference:
                raise ValueError(f"Duplicate active unit reference: {observation.reference}")
            by_reference[observation.reference] = observation

        active_identities: dict[int, UnitIdentity] = {}
        for reference, observation in sorted(by_reference.items()):
            previous = self._slots.get(reference)
            if (
                previous is not None
                and previous.active
                and previous.unit_type == observation.unit_type
            ):
                slot = previous
            else:
                generation = previous.generation + 1 if previous is not None else 1
                slot = UnitSlotMetadata(
                    reference=reference,
                    unit_type=observation.unit_type,
                    identity_id=self._next_identity_id,
                    generation=generation,
                    active=True,
                )
                self._next_identity_id += 1
            self._slots[reference] = slot
            active_identities[reference] = UnitIdentity(
                slot.identity_id, reference, slot.generation
            )

        for reference, previous in tuple(self._slots.items()):
            if previous.active and reference not in by_reference:
                self._slots[reference] = UnitSlotMetadata(
                    reference=previous.reference,
                    unit_type=previous.unit_type,
                    identity_id=previous.identity_id,
                    generation=previous.generation,
                    active=False,
                )
        return active_identities

    def checkpoint_metadata(self) -> UnitIdentityMetadata:
        """Capture active entries and inactive tombstones for checkpoint restore."""
        return UnitIdentityMetadata(
            schema_version=IDENTITY_SCHEMA_VERSION,
            next_identity_id=self._next_identity_id,
            slots=tuple(self._slots[reference] for reference in sorted(self._slots)),
        )

    @classmethod
    def from_checkpoint(cls, metadata: UnitIdentityMetadata) -> UnitIdentityTracker:
        """Restore identity history associated with a restored emulator checkpoint."""
        return cls(metadata)
