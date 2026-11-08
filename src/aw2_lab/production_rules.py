"""Verified unit choices for supported AW2 production facilities."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProductionFacility:
    terrain_class: int
    name: str
    unit_types: tuple[int, ...]


PRODUCTION_FACILITIES = (
    ProductionFacility(14, "base", (1, 2, 6, 5, 3, 8, 7, 10, 11, 14, 15)),
    ProductionFacility(11, "seaport", (21, 22, 23, 24)),
    ProductionFacility(10, "airport", (16, 17, 19, 20)),
)
PRODUCTION_BY_TERRAIN = {item.terrain_class: item for item in PRODUCTION_FACILITIES}
PRODUCTION_UNIT_TYPES = tuple(
    dict.fromkeys(unit_type for item in PRODUCTION_FACILITIES for unit_type in item.unit_types)
)
