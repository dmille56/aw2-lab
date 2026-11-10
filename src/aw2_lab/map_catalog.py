"""Supported two-player Classic maps in the pinned US ROM's menu order.

Other categories and maps with three/four armies require separate acceptance.
Numeric IDs and dimensions come from the original ROM headers at 0x085C77A0.
"""

from dataclasses import dataclass
from typing import Literal

MapId = Literal[
    "bean_island",
    "crater_isle",
    "triangles",
    "ball_islands",
    "coral_lagoon",
    "puzzle_trio",
    "fist_peninsula",
    "deer_harbor",
    "alara_range",
    "lost_river",
    "volcano_isle",
    "turtle_atoll",
    "squash_island",
    "cube_keys",
    "mirror_islands",
    "shark_strait",
    "royal_channel",
]


@dataclass(frozen=True, slots=True)
class VersusMap:
    id: MapId
    name: str
    rom_id: int
    width: int
    height: int


CLASSIC_MAPS: tuple[VersusMap, ...] = (
    VersusMap("bean_island", "Bean Island", 1, 16, 15),
    VersusMap("crater_isle", "Crater Isle", 2, 16, 15),
    VersusMap("triangles", "Triangles", 3, 16, 15),
    VersusMap("ball_islands", "Ball Islands", 4, 42, 15),
    VersusMap("coral_lagoon", "Coral Lagoon", 5, 16, 15),
    VersusMap("puzzle_trio", "Puzzle Trio", 6, 32, 15),
    VersusMap("fist_peninsula", "Fist Peninsula", 7, 16, 15),
    VersusMap("deer_harbor", "Deer Harbor", 8, 32, 30),
    VersusMap("alara_range", "Alara Range", 9, 32, 15),
    VersusMap("lost_river", "Lost River", 10, 32, 15),
    VersusMap("volcano_isle", "Volcano Isle", 11, 16, 15),
    VersusMap("turtle_atoll", "Turtle Atoll", 12, 16, 30),
    VersusMap("squash_island", "Squash Island", 13, 48, 15),
    VersusMap("cube_keys", "Cube Keys", 14, 32, 30),
    VersusMap("mirror_islands", "Mirror Islands", 15, 32, 15),
    VersusMap("shark_strait", "Shark Strait", 16, 37, 30),
    VersusMap("royal_channel", "Royal Channel", 17, 39, 30),
)
MAPS_BY_ID: dict[str, VersusMap] = {entry.id: entry for entry in CLASSIC_MAPS}
MAP_IDS: tuple[MapId, ...] = tuple(entry.id for entry in CLASSIC_MAPS)
