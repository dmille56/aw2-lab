"""Unit-ID regressions and gameplay decisions using the audited AW2 rules."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from aw2_lab.aw2_unit_profiles import (
    UNIT_PROFILES,
    MovementType,
    RuleContext,
    WeaponType,
    movement_cost,
    preflight_move_attack,
    route_cost,
    turn_start_fuel,
)
from aw2_lab.state_model import Weather
from aw2_lab.state_validation import UNIT_TYPES
from aw2_lab.unit_rules_audit import audit_rules


def test_catalog_covers_validated_unit_ids_with_correct_names() -> None:
    assert set(UNIT_PROFILES) == UNIT_TYPES
    assert UNIT_PROFILES[3].name == "Medium Tank"
    assert UNIT_PROFILES[6].name == "Recon"
    assert UNIT_PROFILES[10].name == "Artillery"
    assert UNIT_PROFILES[11].name == "Rockets"
    assert UNIT_PROFILES[15].name == "Missiles"
    assert UNIT_PROFILES[21].name == "Battleship"
    assert UNIT_PROFILES[23].name == "Lander"
    assert UNIT_PROFILES[24].name == "Submarine"
    assert UNIT_PROFILES[10].fuel_capacity == 50
    assert UNIT_PROFILES[15].movement == 4


def test_cruiser_secondary_can_attack_air_without_main_ammo() -> None:
    cruiser = UNIT_PROFILES[22]
    assert cruiser.available_weapons(16, 0) == (WeaponType.SECONDARY,)
    assert cruiser.available_weapons(24, 0) == ()
    assert cruiser.available_weapons(24, 1) == (WeaponType.PRIMARY,)
    assert cruiser.available_weapons(25, 1) == (WeaponType.PRIMARY,)
    assert cruiser.available_weapons(5, 9) == ()
    assert WeaponType.PRIMARY.ammo_cost == 1
    assert WeaponType.SECONDARY.ammo_cost == 0


def test_turn_start_fuel_includes_cargo_service_diving_and_eagle() -> None:
    assert turn_start_fuel(5) == 0
    assert turn_start_fuel(17) == 5
    assert turn_start_fuel(17, context=RuleContext(8)) == 3
    assert turn_start_fuel(19, context=RuleContext(8)) == 0
    assert turn_start_fuel(19, embarked=True) == 0
    assert turn_start_fuel(17, on_owned_service_property=True) == 0
    assert turn_start_fuel(24) == 1
    assert turn_start_fuel(24, submerged=True) == 5
    assert UNIT_PROFILES[24].destroyed_at_zero_fuel
    assert not UNIT_PROFILES[5].destroyed_at_zero_fuel
    with pytest.raises(ValueError, match="Only a Submarine"):
        turn_start_fuel(5, submerged=True)


@pytest.mark.parametrize("unit_type", [10, 11, 15, 21])
def test_indirect_units_can_attack_only_without_moving(unit_type: int) -> None:
    unit = UNIT_PROFILES[unit_type]
    target = (unit.minimum_range, 0)
    preflight_move_attack(unit_type=unit_type, ammo=9, path=(), start=(0, 0), target=target)
    with pytest.raises(ValueError, match="cannot move and attack"):
        preflight_move_attack(
            unit_type=unit_type, ammo=9, path=((1, 0),), start=(0, 0), target=target
        )


@pytest.mark.parametrize("unit_type", [1, 2, 3, 5, 6, 8, 14, 16, 17, 19, 22, 24])
def test_direct_units_allow_movement_before_firing(unit_type: int) -> None:
    preflight_move_attack(unit_type=unit_type, ammo=9, path=((0, 1),), start=(0, 0), target=(1, 1))


@pytest.mark.parametrize(
    ("unit_type", "ammo", "path", "target", "message"),
    [
        (7, 0, (), (1, 0), "no weapons"),
        (23, 0, (), (1, 0), "no weapons"),
        (10, 0, (), (0, 2), "no ammunition"),
        (14, 0, (), (0, 1), "no ammunition"),
        (5, 9, (), (0, 2), "attack range"),
        (5, 9, tuple((x, 0) for x in range(1, 10)), (10, 0), "movement allowance"),
    ],
)
def test_preflight_rejects_impossible_actions(
    unit_type: int,
    ammo: int,
    path: tuple[tuple[int, int], ...],
    target: tuple[int, int],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        preflight_move_attack(
            unit_type=unit_type, ammo=ammo, path=path, start=(0, 0), target=target
        )


def test_preflight_checks_weapons_and_impassable_route_before_movement() -> None:
    with pytest.raises(ValueError, match="compatible weapon"):
        preflight_move_attack(
            unit_type=5, ammo=9, path=(), start=(0, 0), target=(1, 0), target_unit_type=16
        )
    with pytest.raises(ValueError, match="impassable terrain"):
        preflight_move_attack(
            unit_type=5,
            ammo=9,
            path=((1, 0),),
            start=(0, 0),
            target=(2, 0),
            terrain_classes=(7,),
        )


def test_unknown_unit_defers_legality_to_aw2() -> None:
    preflight_move_attack(unit_type=255, ammo=0, path=(), start=(0, 0), target=(99, 99))


def test_baseline_terrain_weather_and_transport_traversal() -> None:
    assert route_cost(5, (1, 4)) == 3  # Tank: plain then wood.
    assert route_cost(5, (1, 4), Weather.RAIN) == 5
    assert route_cost(5, (1, 4), Weather.SNOW) == 4  # Guide incorrectly lists wood as 3.
    assert route_cost(1, (3,), Weather.SNOW) == 4
    assert route_cost(2, (3,), Weather.SNOW) == 2
    assert route_cost(23, (13, 7, 19)) == 4  # Lander: shoal, sea, reef.
    assert route_cost(21, (13,)) is None  # Battleship cannot enter a shoal.
    assert route_cost(16, (15,)) is None  # Pipes also block air units.
    assert route_cost(1, ()) == 0
    assert movement_cost(20, MovementType.FOOT) == 1  # Lab, not yet live-decoded.
    with pytest.raises(ValueError, match="Unknown terrain"):
        movement_cost(32, MovementType.FOOT)


def test_co_adjustments_and_weather_tables_are_separate_from_baselines() -> None:
    assert RuleContext(5, 2).unit_limits(10) == (5, 6)  # Grit passive + Super = +3 range.
    assert RuleContext(2).unit_limits(10) == (5, 2)  # Max indirect penalty.
    assert RuleContext(4).unit_limits(7) == (7, 0)  # Sami transports.
    assert RuleContext(2, 2).unit_limits(5) == (8, 1)
    assert route_cost(5, (1,), Weather.SNOW, context=RuleContext(3)) == 1  # Olaf.
    assert route_cost(1, (3,), Weather.RAIN, context=RuleContext(3)) == 4
    assert route_cost(5, (4,), Weather.RAIN, context=RuleContext(9)) == 2  # Drake.
    assert route_cost(5, (4,), context=RuleContext(12, 1)) == 1  # Lash power.
    assert route_cost(5, (3,), context=RuleContext(12, 1)) is None
    assert route_cost(1, (3,), context=RuleContext(4, 1)) == 2  # Sami keeps baseline costs.
    preflight_move_attack(unit_type=10, ammo=9, path=(), start=(0, 0), target=(6, 0))


@pytest.mark.parametrize("context", [(19, 0), (1, 3), (None, 1)])
def test_invalid_co_context_is_rejected(context: tuple[int | None, int]) -> None:
    with pytest.raises(ValueError):
        RuleContext(*context)


@pytest.mark.skipif(
    os.environ.get("AW2_RUN_RULES_ROM_TESTS") != "1",
    reason="set AW2_RUN_RULES_ROM_TESTS=1 and AW2_ROM_PATH for exhaustive ROM rules audit",
)
def test_catalog_matches_supported_rom() -> None:
    report = audit_rules(Path(os.environ["AW2_ROM_PATH"]))
    assert report["units"] == 19
    assert report["checks"] == 40147


@pytest.mark.parametrize(
    ("context", "weather", "fuel", "error"),
    [
        (RuleContext(), Weather.CLEAR, 6, None),
        (RuleContext(), Weather.SNOW, 6, "movement allowance"),
        (RuleContext(), Weather.CLEAR, 3, "remaining fuel"),
        (RuleContext(), Weather.CLEAR, None, None),
        (None, None, 6, None),
        (RuleContext(13, 2), Weather.SNOW, 8, None),  # Adder Super +2 movement.
    ],
)
def test_observed_weather_co_and_fuel_select_route_budget(context, weather, fuel, error) -> None:
    # Four plains cost 4 in clear weather, 8 in snow; baseline Tank move is 6.
    path = ((1, 0), (2, 0), (3, 0), (4, 0))

    def check() -> None:
        preflight_move_attack(
            unit_type=5,
            ammo=9,
            path=path,
            start=(0, 0),
            target=(5, 0),
            terrain_classes=(1, 1, 1, 1),
            context=context,
            weather=weather,
            fuel=fuel,
        )

    if error:
        with pytest.raises(ValueError, match=error):
            check()
    else:
        check()
