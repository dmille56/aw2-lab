"""Verified static transport capacities and cargo classes for AW2 unit types."""

from __future__ import annotations

from aw2_lab.aw2_unit_profiles import UNIT_PROFILES, MovementType
from aw2_lab.state_model import UnitState

TRANSPORT_CAPACITY = {7: 1, 20: 1, 23: 2}
_FOOT_CARRIERS = frozenset({1, 2})
_GROUND_MOVEMENT = frozenset(
    {MovementType.FOOT, MovementType.MECH, MovementType.TREADS, MovementType.WHEELS}
)


def is_transport(unit_type: int) -> bool:
    return unit_type in TRANSPORT_CAPACITY


def compatible_cargo_types(transport_type: int) -> frozenset[int]:
    """Return cargo classes supported by APC, T-Copter, and Lander."""
    if transport_type == 7:  # APC: one Infantry or Mech.
        return _FOOT_CARRIERS
    if transport_type == 20:  # T-Copter: one Infantry or Mech.
        return _FOOT_CARRIERS
    if transport_type == 23:  # Lander: any two ground units.
        return frozenset(
            unit_type
            for unit_type, profile in UNIT_PROFILES.items()
            if profile.movement_type in _GROUND_MOVEMENT
        )
    return frozenset()


def free_capacity(transport: UnitState) -> int:
    """Return open cargo slots, clamped when an observation is malformed."""
    capacity = TRANSPORT_CAPACITY.get(transport.unit_type, 0)
    return max(0, capacity - len(transport.cargo_references))


def can_carry(transport_type: int, cargo_type: int) -> bool:
    return cargo_type in compatible_cargo_types(transport_type)
