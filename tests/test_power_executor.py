"""Normal CO Power cost calculations use the active CO and verified use count."""

import pytest

from aw2_lab.power_executor import (
    normal_power_activation_threshold,
    normal_power_cost,
    super_power_activation_threshold,
    super_power_cost,
)


def test_normal_power_cost_uses_each_cos_star_count() -> None:
    stars = [0] * 19
    stars[1] = 3
    stars[2] = 4
    metadata = tuple(stars)

    assert normal_power_cost(metadata, 1, 0) == 32_400
    assert normal_power_cost(metadata, 2, 0) == 43_200


def test_normal_power_cost_applies_the_incremented_use_counter() -> None:
    stars = [0] * 19
    stars[1] = 3

    assert normal_power_cost(tuple(stars), 1, 4) == 54_000
    assert normal_power_activation_threshold(tuple(stars), 1, 9) == 75_600
    assert normal_power_cost(tuple(stars), 1, 9) == 54_000


def test_super_power_cost_uses_each_cos_total_super_stars() -> None:
    stars = [0] * 19
    stars[1] = 6
    stars[2] = 8
    assert super_power_cost(tuple(stars), 1, 0) == 64_800
    assert super_power_cost(tuple(stars), 2, 0) == 86_400


def test_super_power_cost_uses_incremented_shared_activation_counter() -> None:
    stars = [0] * 19
    stars[1] = 6
    assert super_power_cost(tuple(stars), 1, 4) == 108_000


def test_super_power_readiness_threshold_precedes_increment_and_spend() -> None:
    stars = [0] * 19
    stars[1] = 6

    assert super_power_activation_threshold(tuple(stars), 1, 0) == 54_000
    assert super_power_cost(tuple(stars), 1, 0) == 64_800


def test_normal_power_readiness_threshold_uses_current_counter() -> None:
    stars = [0] * 19
    stars[1] = 3

    assert normal_power_activation_threshold(tuple(stars), 1, 0) == 27_000
    assert normal_power_activation_threshold(tuple(stars), 1, 1) == 32_400
    assert normal_power_cost(tuple(stars), 1, 0) == 32_400


@pytest.mark.parametrize(
    ("co_id", "use_counter"),
    [(0, 0), (19, 0), (1, -1), (1, 10)],
)
def test_normal_power_cost_rejects_unverified_metadata(co_id, use_counter) -> None:
    stars = [0] * 19
    stars[1] = 3

    with pytest.raises(ValueError):
        normal_power_cost(tuple(stars), co_id, use_counter)


@pytest.mark.parametrize(
    ("co_id", "use_counter"),
    [(0, 0), (19, 0), (1, -1), (1, 10)],
)
def test_super_power_cost_rejects_unverified_metadata(co_id, use_counter) -> None:
    stars = [0] * 19
    stars[1] = 6

    with pytest.raises(ValueError):
        super_power_cost(tuple(stars), co_id, use_counter)
