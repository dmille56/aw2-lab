from aw2_lab.state_model import UnitState
from aw2_lab.transport_rules import can_carry, compatible_cargo_types, free_capacity


def test_transport_cargo_compatibility_and_capacity() -> None:
    assert compatible_cargo_types(7) == frozenset({1, 2})
    assert compatible_cargo_types(20) == frozenset({1, 2})
    assert {1, 2, 3, 5, 6, 7, 8, 10, 11, 14, 15} <= compatible_cargo_types(23)
    assert not compatible_cargo_types(23) & {16, 17, 19, 20, 21, 22, 23, 24}
    assert can_carry(20, 1)
    assert can_carry(20, 2)

    apc = UnitState(
        reference=1,
        army_slot=1,
        unit_slot=1,
        unit_type=7,
        x=0,
        y=0,
        internal_health=100,
        ammo=0,
        fuel=70,
        used_this_turn=False,
        embarked=False,
        capture_points=0,
        cargo_references=(),
    )
    assert free_capacity(apc) == 1
    loaded_apc = UnitState(
        reference=1,
        army_slot=1,
        unit_slot=1,
        unit_type=7,
        x=0,
        y=0,
        internal_health=100,
        ammo=0,
        fuel=70,
        used_this_turn=False,
        embarked=False,
        capture_points=0,
        cargo_references=(2,),
    )
    assert free_capacity(loaded_apc) == 0


def test_transport_types_have_no_cargo_compatibility() -> None:
    assert compatible_cargo_types(1) == frozenset()
    assert compatible_cargo_types(99) == frozenset()
