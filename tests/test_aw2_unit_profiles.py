"""Conservative baseline MoveAttack preflight checks."""

from __future__ import annotations

import pytest

from aw2_lab.aw2_unit_profiles import preflight_move_attack


def test_preflight_allows_a_tank_attack_along_the_requested_route() -> None:
    preflight_move_attack(
        unit_type=5,
        ammo=9,
        path=((1, 0),),
        start=(0, 0),
        target=(1, 1),
    )


@pytest.mark.parametrize(
    ("unit_type", "ammo", "path", "target", "message"),
    [
        (7, 0, (), (1, 0), "no weapons"),
        (6, 0, (), (0, 2), "no ammunition"),
        (6, 9, ((1, 0),), (3, 0), "cannot move and attack"),
        (5, 9, (), (0, 4), "attack range"),
        (5, 9, ((1, 0),) * 9, (1, 0), "movement allowance"),
    ],
)
def test_preflight_rejects_certainly_impossible_actions(
    unit_type: int,
    ammo: int,
    path: tuple[tuple[int, int], ...],
    target: tuple[int, int],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        preflight_move_attack(
            unit_type=unit_type,
            ammo=ammo,
            path=path,
            start=(0, 0),
            target=target,
        )


def test_unprofiled_unit_defers_legality_to_aw2() -> None:
    preflight_move_attack(
        unit_type=255,
        ammo=0,
        path=((1, 0),) * 100,
        start=(0, 0),
        target=(99, 99),
    )
