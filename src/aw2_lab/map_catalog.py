"""Two-player built-in Versus maps for the pinned US ROM.

Category positions include intervening three/four-player entries. Unlock maps
require the player's local cartridge save; startup never modifies unlock flags.
ROM headers: 0x085C77A0 + ID * 0x5C; player count +0x18, category +0x1A.
"""

from dataclasses import dataclass
from enum import StrEnum
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
    "little_island",
    "sun_canal",
    "beaker_river",
    "star_islands",
    "eon_springs",
    "portal_bridge",
    "sabre_range",
    "asphalt_maze",
    "cog_isle",
    "zero_wood",
    "switchback",
    "ruby_keys",
    "rainy_haven",
    "rail_strait",
    "tribe_islands",
    "vision_bridge",
    "piston_dam",
    "hat_harbor",
    "swan_cove",
    "go_islands",
    "hourglass_isle",
    "brace_range",
    "river_range",
    "moon_isle",
    "mint_plateau",
    "jewel_canal",
    "wrench_island",
    "rapid_ferry",
    "bundle_city",
    "scarab_road",
    "pointing_river",
    "liaison_wood",
    "big_daddy",
    "spann_island",
    "moji_island",
    "duo_falls",
    "sole_harbor",
    "pivot_isle",
    "lands_end",
    "kita_straight",
    "point_stormy",
    "ridge_island",
    "mials_hope",
    "bounty_river",
    "toil_ferry",
    "twin_isle",
    "dire_range",
    "egg_islands",
    "terra_maw",
    "pay_dirt",
    "long_road",
    "nest_egg",
    "the_trident",
    "banker_hills",
    "missile_plains",
]


class MapCategory(StrEnum):
    CLASSIC = "classic"
    VERSUS = "versus"
    PRE_DEPLOYED = "pre_deployed"
    WAR_ROOM = "war_room"

    @property
    def selector_id(self) -> int:
        return {
            MapCategory.CLASSIC: 2,
            MapCategory.VERSUS: 3,
            MapCategory.PRE_DEPLOYED: 4,
            MapCategory.WAR_ROOM: 7,
        }[self]


@dataclass(frozen=True, slots=True)
class VersusMap:
    id: MapId
    name: str
    rom_id: int
    width: int
    height: int
    category: MapCategory
    menu_index: int
    requires_unlock: bool = False


CLASSIC_MAPS: tuple[VersusMap, ...] = (
    VersusMap("bean_island", "Bean Island", 1, 16, 15, MapCategory.CLASSIC, 0),
    VersusMap("crater_isle", "Crater Isle", 2, 16, 15, MapCategory.CLASSIC, 1),
    VersusMap("triangles", "Triangles", 3, 16, 15, MapCategory.CLASSIC, 2),
    VersusMap("ball_islands", "Ball Islands", 4, 42, 15, MapCategory.CLASSIC, 3),
    VersusMap("coral_lagoon", "Coral Lagoon", 5, 16, 15, MapCategory.CLASSIC, 4),
    VersusMap("puzzle_trio", "Puzzle Trio", 6, 32, 15, MapCategory.CLASSIC, 5),
    VersusMap("fist_peninsula", "Fist Peninsula", 7, 16, 15, MapCategory.CLASSIC, 6),
    VersusMap("deer_harbor", "Deer Harbor", 8, 32, 30, MapCategory.CLASSIC, 7),
    VersusMap("alara_range", "Alara Range", 9, 32, 15, MapCategory.CLASSIC, 8),
    VersusMap("lost_river", "Lost River", 10, 32, 15, MapCategory.CLASSIC, 9),
    VersusMap("volcano_isle", "Volcano Isle", 11, 16, 15, MapCategory.CLASSIC, 10),
    VersusMap("turtle_atoll", "Turtle Atoll", 12, 16, 30, MapCategory.CLASSIC, 11),
    VersusMap("squash_island", "Squash Island", 13, 48, 15, MapCategory.CLASSIC, 12),
    VersusMap("cube_keys", "Cube Keys", 14, 32, 30, MapCategory.CLASSIC, 13),
    VersusMap("mirror_islands", "Mirror Islands", 15, 32, 15, MapCategory.CLASSIC, 14),
    VersusMap("shark_strait", "Shark Strait", 16, 37, 30, MapCategory.CLASSIC, 15),
    VersusMap("royal_channel", "Royal Channel", 17, 39, 30, MapCategory.CLASSIC, 16),
)
VERSUS_MAPS: tuple[VersusMap, ...] = (
    VersusMap("little_island", "Little Island", 18, 19, 10, MapCategory.VERSUS, 0),
    VersusMap("sun_canal", "Sun Canal", 19, 15, 13, MapCategory.VERSUS, 1),
    VersusMap("beaker_river", "Beaker River", 20, 19, 15, MapCategory.VERSUS, 2),
    VersusMap("star_islands", "Star Islands", 21, 31, 16, MapCategory.VERSUS, 3),
    VersusMap("eon_springs", "Eon Springs", 22, 19, 17, MapCategory.VERSUS, 4),
    VersusMap("portal_bridge", "Portal Bridge", 23, 19, 17, MapCategory.VERSUS, 5),
    VersusMap("sabre_range", "Sabre Range", 24, 15, 11, MapCategory.VERSUS, 6),
    VersusMap("asphalt_maze", "Asphalt Maze", 25, 15, 11, MapCategory.VERSUS, 7),
    VersusMap("cog_isle", "Cog Isle", 26, 15, 11, MapCategory.VERSUS, 8),
    VersusMap("zero_wood", "Zero Wood", 27, 15, 11, MapCategory.VERSUS, 9),
    VersusMap("switchback", "Switchback", 28, 21, 15, MapCategory.VERSUS, 10),
    VersusMap("ruby_keys", "Ruby Keys", 29, 29, 15, MapCategory.VERSUS, 11),
    VersusMap("rainy_haven", "Rainy Haven", 30, 15, 15, MapCategory.VERSUS, 12),
    VersusMap("rail_strait", "Rail Strait", 31, 18, 15, MapCategory.VERSUS, 13),
    VersusMap("tribe_islands", "Tribe Islands", 32, 19, 17, MapCategory.VERSUS, 14),
    VersusMap("vision_bridge", "Vision Bridge", 33, 31, 24, MapCategory.VERSUS, 15),
    VersusMap("piston_dam", "Piston Dam", 34, 26, 14, MapCategory.VERSUS, 16),
    VersusMap("hat_harbor", "Hat Harbor", 35, 21, 21, MapCategory.VERSUS, 17),
    VersusMap("swan_cove", "Swan Cove", 36, 24, 17, MapCategory.VERSUS, 18),
    VersusMap("go_islands", "Go Islands", 37, 24, 17, MapCategory.VERSUS, 19),
    VersusMap(
        "hourglass_isle", "Hourglass Isle", 38, 16, 24, MapCategory.VERSUS, 20, requires_unlock=True
    ),
)
PRE_DEPLOYED_MAPS: tuple[VersusMap, ...] = (
    VersusMap("brace_range", "Brace Range", 39, 15, 10, MapCategory.PRE_DEPLOYED, 0),
    VersusMap("river_range", "River Range", 40, 15, 10, MapCategory.PRE_DEPLOYED, 1),
    VersusMap("moon_isle", "Moon Isle", 41, 17, 11, MapCategory.PRE_DEPLOYED, 2),
    VersusMap("mint_plateau", "Mint Plateau", 42, 17, 11, MapCategory.PRE_DEPLOYED, 3),
    VersusMap("jewel_canal", "Jewel Canal", 43, 19, 12, MapCategory.PRE_DEPLOYED, 4),
    VersusMap("wrench_island", "Wrench Island", 44, 22, 13, MapCategory.PRE_DEPLOYED, 5),
    VersusMap("rapid_ferry", "Rapid Ferry", 45, 19, 12, MapCategory.PRE_DEPLOYED, 6),
    VersusMap("bundle_city", "Bundle City", 46, 16, 11, MapCategory.PRE_DEPLOYED, 7),
    VersusMap("scarab_road", "Scarab Road", 47, 15, 14, MapCategory.PRE_DEPLOYED, 8),
    VersusMap("pointing_river", "Pointing River", 48, 15, 10, MapCategory.PRE_DEPLOYED, 9),
    VersusMap("liaison_wood", "Liaison Wood", 49, 19, 14, MapCategory.PRE_DEPLOYED, 10),
    VersusMap(
        "big_daddy", "Big Daddy", 56, 19, 15, MapCategory.PRE_DEPLOYED, 17, requires_unlock=True
    ),
)
WAR_ROOM_MAPS: tuple[VersusMap, ...] = (
    VersusMap("spann_island", "Spann Island", 108, 15, 10, MapCategory.WAR_ROOM, 0),
    VersusMap("moji_island", "Moji Island", 109, 26, 22, MapCategory.WAR_ROOM, 1),
    VersusMap("duo_falls", "Duo Falls", 110, 33, 13, MapCategory.WAR_ROOM, 2),
    VersusMap("sole_harbor", "Sole Harbor", 111, 22, 15, MapCategory.WAR_ROOM, 3),
    VersusMap("pivot_isle", "Pivot Isle", 112, 21, 14, MapCategory.WAR_ROOM, 4),
    VersusMap("lands_end", "Land's End", 113, 32, 27, MapCategory.WAR_ROOM, 5),
    VersusMap("kita_straight", "Kita Straight", 114, 27, 35, MapCategory.WAR_ROOM, 6),
    VersusMap("point_stormy", "Point Stormy", 115, 25, 22, MapCategory.WAR_ROOM, 7),
    VersusMap("ridge_island", "Ridge Island", 116, 19, 16, MapCategory.WAR_ROOM, 8),
    VersusMap("mials_hope", "Mial's Hope", 117, 45, 28, MapCategory.WAR_ROOM, 9),
    VersusMap("bounty_river", "Bounty River", 118, 28, 22, MapCategory.WAR_ROOM, 10),
    VersusMap("toil_ferry", "Toil Ferry", 119, 26, 16, MapCategory.WAR_ROOM, 11),
    VersusMap("twin_isle", "Twin Isle", 120, 22, 16, MapCategory.WAR_ROOM, 12),
    VersusMap("dire_range", "Dire Range", 121, 37, 25, MapCategory.WAR_ROOM, 13),
    VersusMap("egg_islands", "Egg Islands", 122, 42, 28, MapCategory.WAR_ROOM, 14),
    VersusMap("terra_maw", "Terra Maw", 123, 32, 28, MapCategory.WAR_ROOM, 15),
    VersusMap("pay_dirt", "Pay Dirt", 128, 16, 12, MapCategory.WAR_ROOM, 20, requires_unlock=True),
    VersusMap(
        "long_road", "Long Road", 129, 15, 20, MapCategory.WAR_ROOM, 21, requires_unlock=True
    ),
    VersusMap("nest_egg", "Nest Egg", 130, 18, 11, MapCategory.WAR_ROOM, 22, requires_unlock=True),
    VersusMap(
        "the_trident", "The Trident", 131, 19, 19, MapCategory.WAR_ROOM, 23, requires_unlock=True
    ),
    VersusMap(
        "banker_hills", "Banker Hills", 132, 18, 13, MapCategory.WAR_ROOM, 24, requires_unlock=True
    ),
    VersusMap(
        "missile_plains",
        "Missile Plains",
        133,
        20,
        20,
        MapCategory.WAR_ROOM,
        25,
        requires_unlock=True,
    ),
)
ALL_MAPS = CLASSIC_MAPS + VERSUS_MAPS + PRE_DEPLOYED_MAPS + WAR_ROOM_MAPS
MAPS_BY_ID: dict[str, VersusMap] = {entry.id: entry for entry in ALL_MAPS}
MAP_IDS: tuple[MapId, ...] = tuple(entry.id for entry in ALL_MAPS)
