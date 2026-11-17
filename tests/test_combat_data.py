"""Factual combat-chart coverage, plus explicit opt-in cartridge audit."""

import os
from pathlib import Path

import pytest

from aw2_lab.aw2_combat_data import BASE_DAMAGE, CO_COMBAT, combat_bonuses
from aw2_lab.aw2_rules_data import UNIT_DATA
from aw2_lab.combat_rules_audit import audit_combat_rules


def test_chart_matches_existing_weapon_compatibility_and_co_coverage() -> None:
    assert set(BASE_DAMAGE) == set(UNIT_DATA)
    for unit, weapons in BASE_DAMAGE.items():
        assert set(weapons["primary"]) == set(UNIT_DATA[unit][9])
        assert set(weapons["secondary"]) == set(UNIT_DATA[unit][10])
    assert len(CO_COMBAT) == 19 * 3
    assert BASE_DAMAGE[1]["secondary"][1] == 55
    assert BASE_DAMAGE[5]["primary"][1] == 35
    assert BASE_DAMAGE[5]["secondary"][1] == 75
    assert combat_bonuses(2, 0, 5) == (20, 0)
    assert combat_bonuses(2, 0, 1) == (0, 0)


@pytest.mark.skipif(
    os.environ.get("AW2_RUN_COMBAT_ACCEPTANCE") != "1" or not os.environ.get("AW2_ROM_PATH"),
    reason="requires explicit opt-in and supported local ROM",
)
def test_cartridge_combat_facts() -> None:
    assert audit_combat_rules(Path(os.environ["AW2_ROM_PATH"])) > 1500
