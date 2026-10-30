"""Baseline AW2 unit movement and attack profiles for conservative preflight."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UnitProfile:
    movement: int
    minimum_range: int
    maximum_range: int
    can_attack: bool = True


# Unit IDs follow the validated AW2 US revision-0 unit records. The figures
# are the base Versus unit chart; CO effects and terrain remain game-authoritative.
UNIT_PROFILES: dict[int, UnitProfile] = {
    1: UnitProfile(3, 1, 1),  # Infantry
    2: UnitProfile(2, 1, 1),  # Mech
    3: UnitProfile(8, 1, 1),  # Recon
    5: UnitProfile(6, 1, 1),  # Tank
    6: UnitProfile(5, 2, 3),  # Artillery
    7: UnitProfile(6, 1, 1, can_attack=False),  # APC
    8: UnitProfile(5, 3, 5),  # Rockets
    10: UnitProfile(4, 3, 5),  # Missiles
    11: UnitProfile(5, 1, 1),  # Medium Tank
    14: UnitProfile(6, 1, 1),  # Neotank
    15: UnitProfile(6, 1, 1),  # Anti-Air
    16: UnitProfile(9, 1, 1),  # Fighter
    17: UnitProfile(7, 1, 1),  # Bomber
    19: UnitProfile(6, 1, 1),  # Battle Copter
    20: UnitProfile(6, 1, 1, can_attack=False),  # T-Copter
    21: UnitProfile(6, 1, 1, can_attack=False),  # Lander
    22: UnitProfile(6, 1, 1),  # Cruiser
    23: UnitProfile(5, 1, 1),  # Submarine
    24: UnitProfile(5, 2, 6),  # Battleship
}

# These units have no unlimited secondary weapon, so zero main-weapon ammo
# makes an attack impossible. Other units may still fire a secondary weapon.
AMMO_REQUIRED_TO_ATTACK = frozenset({6, 8, 10, 16, 17, 23, 24})

# CO powers can raise a unit's movement or maximum range. The bound deliberately
# permits +2 so this check only rejects routes/targets beyond known AW2 bonuses.
MAX_COMMON_MOVEMENT_BONUS = 2
MAX_COMMON_RANGE_BONUS = 2


def preflight_move_attack(
    *,
    unit_type: int,
    ammo: int,
    path: tuple[tuple[int, int], ...],
    start: tuple[int, int],
    target: tuple[int, int],
) -> None:
    """Reject only attacks ruled out by the baseline profile and known CO bounds."""
    profile = UNIT_PROFILES.get(unit_type)
    if profile is None:
        return
    if not profile.can_attack:
        raise ValueError("Unit type has no weapons")
    if unit_type in AMMO_REQUIRED_TO_ATTACK and ammo <= 0:
        raise ValueError("Unit has no ammunition for its only weapons")

    if path and profile.minimum_range > 1:
        raise ValueError("Indirect units cannot move and attack in the same turn")

    if len(path) > profile.movement + MAX_COMMON_MOVEMENT_BONUS:
        raise ValueError("Requested route exceeds the unit's maximum movement allowance")

    candidate_positions = (start, *path)
    target_distances = tuple(
        abs(x - target[0]) + abs(y - target[1]) for x, y in candidate_positions
    )
    maximum_range = profile.maximum_range + MAX_COMMON_RANGE_BONUS
    if not any(profile.minimum_range <= distance <= maximum_range for distance in target_distances):
        raise ValueError("Target is outside the unit's possible attack range along the route")
