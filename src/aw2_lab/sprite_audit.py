"""Compare what mGBA draws on the battle map with the packed client sprite atlas.

The audit boots its own isolated mGBA instance into the requested Versus map, so the D-pad
presses the camera sweep needs never touch an emulator that is serving a live match. It
decodes the live battle map, pans the battle camera over every viewport, screenshots each
view, and compares each visible cell with the atlas region the client selects for that
cell. Cells that do not match are also compared with every other terrain artwork in the
pack, which separates "the client picked the wrong region" from "the emulator drew
something the atlas has no artwork for" (interface panels, units, or uncaptured property
art).

    aw2-lab sprite-audit --map pipe_maze --rom ~/Downloads/aw2/aw2.gba \
        --save-profile ~/Downloads/aw2/game-saves/aw2-everything-unlocked.sav \
        --pack ~/.local/share/aw2-lab/sprites

    # Auditing an emulator that is already serving a match is possible but unsafe for
    # that match: the sweep presses D-pad buttons, so the controller's committed frame no
    # longer matches the emulator and the next gameplay command needs recovery. The audit
    # snapshots the attached emulator first and fails the command if it cannot put that
    # exact frame back.
    aw2-lab sprite-audit --attach-live 45645 --map pipe_maze \
        --rom ~/Downloads/aw2/aw2.gba
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import signal
import socket
import zlib
from collections import Counter
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aw2_lab.bridge import BridgeError, LuaBridgeClient
from aw2_lab.cold_boot import ColdBootError, boot_fixed_versus_match
from aw2_lab.emulator import (
    EmulatorLauncher,
    EmulatorLaunchError,
    EmulatorMode,
    EmulatorSettings,
)
from aw2_lab.map_catalog import MAPS_BY_ID, VersusMap
from aw2_lab.match_contract import CoId
from aw2_lab.sprite_extraction import decode_lz77, encode_png
from aw2_lab.state_decoder import capture_game_state
from aw2_lab.state_model import BattleState, GameState, ValueStatus
from aw2_lab.state_validation import BATTLE_MAP_ID_ADDRESS
from aw2_lab.ui_state import CursorStatus

MAP_TABLE = 0x005C77A0
MAP_TABLE_STRIDE = 0x5C
TERRAIN_LOOKUP = 0x0C1BC4
TILE = 16
VIEW_WIDTH = 15
VIEW_HEIGHT = 10
CHANNELS = 4
# A tile is 256 pixels. On unobstructed ground the bridge screenshot and the composed
# atlas differ by at most one unit per channel, so 900 points is far above rounding and
# far below the difference between two different tiles of the same class.
MATCH_TOLERANCE = 900
ANIMATED_TERRAIN = "animated terrain; the atlas stores only frame 0"
UNIT_OCCLUSION = "a unit sprite or the status panel covers this cell"
HUD_OCCLUSION = "the HUD or cursor covers this cell in every sampled view"
WRONG_REGION = "atlas region wrong"
# Classes whose artwork is chosen by the owning army rather than by the map cell. The
# pack keeps one representative per class and army, so these cells are the ones where a
# mismatch means "the packed army art differs from what the emulator draws".
PROPERTY_CLASSES = {6, 8, 10, 11, 14, 17, 18}
DIRECTIONS = {"up": 64, "down": 128, "left": 32, "right": 16}
PRESS_FRAMES = 6
SETTLE_FRAMES = 12
# The audit's own emulator uses a port away from 43128 so it cannot collide with a match
# that is already serving players.
DEFAULT_AUDIT_BRIDGE_PORT = 43134
# COs the audit boots with. A fresh Versus save only knows Andy and Max, so larger
# rosters need --save-profile with the COs unlocked.
AUDIT_CO_IDS: tuple[CoId, ...] = ("andy", "max", "sami", "flak")
# Commanders the Teams screen offers on a blank cartridge. Selecting any other CO from a
# fresh save silently lands on a different commander, so the audit refuses those maps.
FRESH_SAVE_CO_IDS: tuple[CoId, ...] = ("andy", "max")
# A packed region must paint at least this many of a cell's 256 pixels before its changed
# pixels can be read as terrain animation rather than as an overlay drawn on top of it.
MIN_GROUND_COVERAGE = TILE * TILE * 3 // 4
# The largest catalog map is 45x30 cells, and the sweep needs roughly one screenshot per
# cell, so the default leaves room for any map plus the animation probes.
DEFAULT_MAX_SCREENSHOTS = 1500
SAMPLE_ROWS = (2, 5, 8, 13)
SAMPLE_COLUMNS = (3, 7, 11, 15)


class AuditError(RuntimeError):
    """An actionable audit failure: unreachable bridge, missing pack, or bad map."""


@dataclass(frozen=True, slots=True)
class GroundCell:
    """One map cell and the artwork the client is expected to select for it."""

    x: int
    y: int
    graphical_tile_id: int
    terrain_class: int
    owner_slot: int


@dataclass(slots=True)
class CellMeasurement:
    x: int
    y: int
    terrain_class: int
    graphical_tile_id: int
    difference: int
    views: int
    unit_on_cell: bool = False
    covered: int = TILE * TILE
    covered_by_terrain_overhang: bool = False
    owner_slot: int = 0
    has_own_artwork: bool = False
    view: tuple[int, int] = (0, 0)
    row: int = 0
    column: int = 0
    rendered: bytes = b""
    nearest_other_region: str | None = None
    nearest_other_difference: int | None = None
    occluded: bool = False
    nearest_other_collection: str | None = None

    @property
    def matched(self) -> bool:
        """A transparent atlas tile matches any pixels, so require actual artwork."""
        return (
            not self.occluded
            and not self.unit_on_cell
            and self.difference <= MATCH_TOLERANCE
            and self.covered > 0
        )

    @property
    def partial_artwork(self) -> bool:
        """The atlas covers part, but not most, of this cell's pixels."""
        return 0 < self.covered < TILE * TILE * 3 // 4


@dataclass(slots=True)
class AuditReport:
    map_id: str
    map_name: str
    width: int
    height: int
    pack: str
    day: int | None = None
    screenshots: int = 0
    views: list[tuple[int, int]] = field(default_factory=list)
    animated_regions: set[str] = field(default_factory=set)
    cells: dict[tuple[int, int], CellMeasurement] = field(default_factory=dict)
    never_in_view: list[tuple[int, int]] = field(default_factory=list)
    animation: dict[str, Any] | None = None
    tile_images: list[str] = field(default_factory=list)

    def verdict(self, cell: CellMeasurement) -> str:
        """Explain, in one line, why a cell did not match the atlas."""
        if cell.unit_on_cell:
            return UNIT_OCCLUSION
        if cell.occluded:
            return HUD_OCCLUSION
        if f"{cell.terrain_class}:{cell.graphical_tile_id}" in self.animated_regions:
            return ANIMATED_TERRAIN
        if (
            cell.nearest_other_difference is not None
            and cell.nearest_other_difference <= MATCH_TOLERANCE
        ):
            return WRONG_REGION
        if not cell.has_own_artwork:
            return "the pack selects no artwork region for this cell"
        if cell.covered == 0:
            return "the atlas region for this cell is transparent"
        if cell.has_own_artwork:
            if cell.terrain_class in PROPERTY_CLASSES:
                return (
                    f"army {cell.owner_slot} property art does not match the packed "
                    f"{cell.terrain_class}:{cell.owner_slot} region"
                )
            return (
                f"the packed {cell.terrain_class}:{cell.graphical_tile_id} region does not "
                "match what mGBA drew"
            )
        return "artwork missing from the atlas"

    def summary(self) -> dict[str, Any]:
        matched = [cell for cell in self.cells.values() if cell.matched]
        mismatched = [cell for cell in self.cells.values() if not cell.matched]
        by_class: dict[str, dict[str, int]] = {}
        for cell in self.cells.values():
            bucket = by_class.setdefault(
                str(cell.terrain_class), {"cells": 0, "matched": 0, "mismatched": 0}
            )
            bucket["cells"] += 1
            bucket["matched" if cell.matched else "mismatched"] += 1
        mismatches = sorted(mismatched, key=lambda item: -item.difference)
        classified = [(cell, self.verdict(cell)) for cell in mismatches]
        verdicts = Counter(verdict for _, verdict in classified)
        defects = [
            cell
            for cell, verdict in classified
            if verdict not in (ANIMATED_TERRAIN, UNIT_OCCLUSION, HUD_OCCLUSION)
        ]
        partial = [cell for cell in self.cells.values() if cell.partial_artwork]
        missing_artwork = [cell for cell in defects if not cell.has_own_artwork]
        return {
            "map_id": self.map_id,
            "map_name": self.map_name,
            "width": self.width,
            "height": self.height,
            "pack": self.pack,
            "day": self.day,
            "screenshots": self.screenshots,
            "views": sorted(list(view) for view in self.views),
            "cells_measured": len(self.cells),
            "cells_matched": len(matched),
            "cells_mismatched": len(mismatched),
            "cells_never_in_view": len(self.never_in_view),
            "largest_matched_difference": max((cell.difference for cell in matched), default=0),
            "mismatches": [
                {
                    "x": cell.x,
                    "y": cell.y,
                    "terrain_class": cell.terrain_class,
                    "graphical_tile_id": cell.graphical_tile_id,
                    "difference": cell.difference,
                    "unit_on_cell": cell.unit_on_cell,
                    "occluded": cell.occluded,
                    "covered_by_terrain_overhang": cell.covered_by_terrain_overhang,
                    "has_own_artwork": cell.has_own_artwork,
                    "owner_slot": cell.owner_slot,
                    "nearest_other_region": cell.nearest_other_region,
                    "nearest_other_difference": cell.nearest_other_difference,
                    "nearest_other_collection": cell.nearest_other_collection,
                    "verdict": verdict,
                    "views": cell.views,
                }
                for cell, verdict in classified
            ],
            "cells_wrong_region": verdicts[WRONG_REGION],
            "cells_no_nearby_artwork": len(defects) - verdicts[WRONG_REGION],
            "cells_animated": verdicts[ANIMATED_TERRAIN],
            "cells_occluded": sum(cell.occluded for cell in mismatches),
            "cells_missing_artwork": len(missing_artwork),
            "cells_covered_by_units": verdicts[UNIT_OCCLUSION],
            "cells_partial_artwork": len(partial),
            "by_terrain_class": {key: by_class[key] for key in sorted(by_class, key=int)},
            "verdicts": dict(sorted(verdicts.items())),
            "comparison_tiles": self.tile_images,
            "animation": self.animation,
        }


def decode_png(data: bytes) -> tuple[int, int, bytes]:
    """Return width, height, and RGBA bytes for an 8-bit non-interlaced PNG."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AuditError("Expected a PNG image")
    width = height = 0
    bit_depth = color_type = interlace = 0
    compressed = bytearray()
    palette: list[tuple[int, int, int]] = []
    position = 8
    while position + 8 <= len(data):
        size = int.from_bytes(data[position : position + 4], "big")
        kind = data[position + 4 : position + 8]
        content = data[position + 8 : position + 8 + size]
        if kind == b"IHDR":
            width, height, bit_depth, color_type, interlace = (
                int.from_bytes(content[:4], "big"),
                int.from_bytes(content[4:8], "big"),
                content[8],
                content[9],
                content[12],
            )
        elif kind == b"IDAT":
            compressed.extend(content)
        elif kind == b"PLTE":
            palette = [
                (content[index], content[index + 1], content[index + 2])
                for index in range(0, len(content), 3)
            ]
        elif kind == b"IEND":
            break
        position += 12 + size
    if bit_depth != 8 or interlace != 0 or color_type not in {0, 2, 3, 6}:
        raise AuditError(f"Unsupported PNG (bit depth {bit_depth}, color type {color_type})")
    channels = {0: 1, 2: 3, 3: 1, 6: 4}[color_type]
    stride = width * channels
    raw = zlib.decompress(bytes(compressed))
    pixels = bytearray(width * height * 4)
    previous = bytearray(stride)
    offset = 0
    for row in range(height):
        filter_type = raw[offset]
        offset += 1
        line = bytearray(raw[offset : offset + stride])
        offset += stride
        if filter_type == 1:
            for index in range(channels, stride):
                line[index] = (line[index] + line[index - channels]) & 255
        elif filter_type == 2:
            for index in range(stride):
                line[index] = (line[index] + previous[index]) & 255
        elif filter_type == 3:
            for index in range(stride):
                left = line[index - channels] if index >= channels else 0
                line[index] = (line[index] + (left + previous[index]) // 2) & 255
        elif filter_type == 4:
            for index in range(stride):
                left = line[index - channels] if index >= channels else 0
                up = previous[index]
                up_left = previous[index - channels] if index >= channels else 0
                candidate = left + up - up_left
                predictor = left
                if abs(candidate - up) < abs(candidate - predictor):
                    predictor = up
                if abs(candidate - up_left) < abs(candidate - predictor):
                    predictor = up_left
                line[index] = (line[index] + predictor) & 255
        elif filter_type != 0:
            raise AuditError(f"Unsupported PNG row filter {filter_type}")
        for column in range(width):
            source = column * channels
            if channels == 1:
                red, green, blue = palette[line[source]] if palette else (0, 0, 0)
                alpha = 255
            elif channels == 4:
                red, green, blue, alpha = (
                    line[source],
                    line[source + 1],
                    line[source + 2],
                    line[source + 3],
                )
            else:
                red, green, blue, alpha = line[source], line[source + 1], line[source + 2], 255
            destination = (row * width + column) * 4
            pixels[destination : destination + 4] = bytes((red, green, blue, alpha))
        previous = line
    return width, height, bytes(pixels)


class SpritePack:
    """The atlas and manifest written by ``aw2-lab extract-sprites``."""

    def __init__(self, directory: Path) -> None:
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file():
            raise AuditError(f"No sprite manifest at {manifest_path}")
        manifest: dict[str, Any] = json.loads(manifest_path.read_text())
        atlas = directory / manifest["atlas"]
        if not atlas.is_file():
            raise AuditError(f"Sprite atlas is missing: {atlas}")
        self.directory = directory
        self.manifest = manifest
        self.width, self.height, self.pixels = decode_png(atlas.read_bytes())
        self._tiles: dict[str, bytes] = {}
        self._artwork: list[tuple[str, str, bytes]] | None = None

    def region(self, kind: str, key: str) -> dict[str, int] | None:
        region = self.manifest.get(kind, {}).get(key)
        return region if isinstance(region, dict) else None

    def region_for(self, cell: GroundCell) -> dict[str, int] | None:
        """Mirror the client's terrain region lookup exactly."""
        selection = self.region_identity(cell)
        return self.region(*selection) if selection is not None else None

    def region_identity(self, cell: GroundCell) -> tuple[str, str] | None:
        key = f"{cell.terrain_class}:{cell.graphical_tile_id}"
        if self.region("terrain_variants", key) is not None:
            return "terrain_variants", key
        if cell.terrain_class != 13:
            key = f"{cell.terrain_class}:{cell.owner_slot}"
            if self.region("terrain", key) is not None:
                return "terrain", key
        return None

    def tile(self, region: dict[str, int]) -> bytes:
        """Return the region's 16x16 ground rows as contiguous RGBA bytes."""
        key = f"{region['x']}:{region['y']}"
        cached = self._tiles.get(key)
        if cached is not None:
            return cached
        rows = bytearray()
        for row in range(TILE):
            start = ((region["y"] + 16 + row) * self.width + region["x"]) * 4
            rows.extend(self.pixels[start : start + TILE * 4])
        tile = bytes(rows)
        self._tiles[key] = tile
        return tile

    def top_rows(self, region: dict[str, int]) -> bytes:
        """Return the 16x16 rows a 32-row frame draws on the cell *above* its anchor."""
        key = f"top:{region['x']}:{region['y']}"
        cached = self._tiles.get(key)
        if cached is not None:
            return cached
        rows = bytearray()
        for row in range(min(TILE, region["height"])):
            start = ((region["y"] + row) * self.width + region["x"]) * 4
            rows.extend(self.pixels[start : start + TILE * 4])
        tile = bytes(rows)
        self._tiles[key] = tile
        return tile

    def signature(self, region: dict[str, int]) -> bytes:
        return tile_signature(self.tile(region))

    def class_variants(self, terrain_class: int) -> list[str]:
        return sorted(
            key
            for key in self.manifest.get("terrain_variants", {})
            if key.split(":")[0] == str(terrain_class)
        )

    def artwork(self) -> list[tuple[str, str, bytes]]:
        """Every terrain tile with its manifest collection and key."""
        if self._artwork is None:
            candidates: list[tuple[str, str, bytes]] = []
            for kind in ("terrain", "terrain_variants"):
                for key, region in self.manifest.get(kind, {}).items():
                    candidates.append((kind, key, self.tile(region)))
            self._artwork = candidates
        return self._artwork


def rom_map_cells(rom: bytes, map: VersusMap) -> list[GroundCell]:
    """Decode a catalog map's cells from the ROM map table used at cold boot."""
    base = MAP_TABLE + map.rom_id * MAP_TABLE_STRIDE
    pointer = int.from_bytes(rom[base : base + 4], "little")
    if not 0x08000000 <= pointer < 0x08800000:
        raise AuditError(f"ROM map {map.name} header does not point into the ROM")
    payload = decode_lz77(rom, pointer - 0x08000000, maximum_size=65536)
    width, height = payload[0], payload[1]
    if len(payload) != 2 + width * height * 2:
        raise AuditError(f"ROM map {map.name} cell array does not match its dimensions")
    if (width, height) != (map.width, map.height):
        raise AuditError(
            f"ROM map {map.name} is {width}x{height} but the catalog says {map.width}x{map.height}"
        )
    lookup = rom[TERRAIN_LOOKUP : TERRAIN_LOOKUP + 0x300]
    cells: list[GroundCell] = []
    for index in range(width * height):
        tile_id = int.from_bytes(payload[2 + 2 * index : 4 + 2 * index], "little")
        cells.append(GroundCell(index % width, index // width, tile_id, lookup[tile_id] & 31, 0))
    return cells


async def battle_state(bridge: LuaBridgeClient, rom_path: Path) -> BattleState | None:
    """Return the battle the bridge is showing, or None when it is not in one."""
    try:
        state = await capture_game_state(bridge, rom_path=rom_path)
    except BridgeError, ValueError:
        return None
    return state.battle.value if state.battle.status is ValueStatus.AVAILABLE else None


def cells_from_state(battle: BattleState, loaded_map_id: int, map: VersusMap) -> list[GroundCell]:
    """Check the loaded ROM map ID and use the current terrain and property ownership."""
    if loaded_map_id != map.rom_id:
        raise AuditError(
            f"The bridge is showing ROM map {loaded_map_id}, but --map {map.name} "
            f"requires ROM map {map.rom_id}."
        )
    if (battle.map.width, battle.map.height) != (map.width, map.height):
        raise AuditError(
            f"The bridge is showing a {battle.map.width}x{battle.map.height} battle, but "
            f"--map {map.name} is {map.width}x{map.height}. Start the audit against the match "
            f"that is actually running this map, or pass the match's --run-dir."
        )
    return [
        GroundCell(tile.x, tile.y, tile.graphical_tile_id, tile.terrain_class, tile.owner_slot)
        for tile in battle.map.tiles
    ]


def rendered_tile(image: bytes, image_width: int, row: int, column: int) -> bytes:
    """Extract one 16x16 cell of the screenshot as contiguous RGBA bytes."""
    start = (row * TILE * image_width + column * TILE) * 4
    stride = image_width * 4
    rows = bytearray()
    for offset in range(TILE):
        rows.extend(image[start + stride * offset : start + stride * offset + TILE * 4])
    return bytes(rows)


def difference(left: bytes, right: bytes, *, mask: bytes | None = None) -> int:
    """Total RGB channel difference, ignoring atlas pixels the pack leaves transparent."""
    alpha = left if mask is None else mask
    total = 0
    for index in range(0, len(left), 4):
        if alpha[index + 3]:
            total += abs(left[index] - right[index])
            total += abs(left[index + 1] - right[index + 1])
            total += abs(left[index + 2] - right[index + 2])
    return total


def opaque_pixels(tile: bytes) -> int:
    """How many of a 16x16 atlas tile's pixels actually carry artwork."""
    return sum(1 for index in range(0, len(tile), 4) if tile[index + 3])


TRANSPARENT_TILE = bytes(TILE * TILE * 4)


def terrain_overhang(
    pack: SpritePack, cells: list[GroundCell], index: int, map_width: int
) -> bytes:
    """Return the part of the cell below's frame that is drawn on top of this cell.

    Mountains, headquarters, and cities are 16x32 frames anchored on their own cell, so
    their top half paints the cell above. Most packed frames are 16x32 with a transparent
    top half, so the height alone does not tell whether anything actually spills up.
    """
    below = index + map_width
    if below >= len(cells):
        return TRANSPARENT_TILE
    region = pack.region_for(cells[below])
    if region is None or region["height"] <= TILE:
        return TRANSPARENT_TILE
    top = pack.top_rows(region)
    return top if opaque_pixels(top) else TRANSPARENT_TILE


def expected_tile(
    pack: SpritePack,
    cells: list[GroundCell],
    map_width: int,
    index: int,
    cache: dict[int, bytes | None],
) -> bytes | None:
    """Return the atlas artwork one cell should show, including neighbour overhang.

    Comparing a cell with only its own ground would flag every cell below a mountain as
    mismatched, because the emulator draws the peak tip there.
    """
    cached = cache.get(index)
    if cached is not None:
        return cached
    cell = cells[index]
    region = pack.region_for(cell)
    if region is None:
        return None
    result = composite(pack.tile(region), terrain_overhang(pack, cells, index, map_width))
    cache[index] = result
    return result


def tile_signature(tile: bytes) -> bytes:
    """A 16-pixel fingerprint of a tile, used to locate the camera window cheaply."""
    return b"".join(
        tile[(row * TILE + column) * 4 : (row * TILE + column) * 4 + 3]
        for row in SAMPLE_ROWS
        for column in SAMPLE_COLUMNS
    )


def screen_signature(image: bytes, image_width: int, row: int, column: int) -> bytes:
    start = (row * TILE * image_width + column * TILE) * 4
    stride = image_width * 4
    return b"".join(
        image[start + stride * offset + pixel * 4 : start + stride * offset + pixel * 4 + 3]
        for offset in SAMPLE_ROWS
        for pixel in SAMPLE_COLUMNS
    )


def camera_offsets(width: int, height: int) -> list[tuple[int, int]]:
    """Every top-left cell the 15x10 battle camera can show on this map."""
    return [(x, y) for y in range(height - VIEW_HEIGHT + 1) for x in range(width - VIEW_WIDTH + 1)]


def camera_window(previous: tuple[int, int], cursor: tuple[int, int]) -> tuple[int, int]:
    """Pan the previous camera origin only when the cursor leaves its window."""
    x, y = cursor
    return (
        min(max(previous[0], x - VIEW_WIDTH + 1), x),
        min(max(previous[1], y - VIEW_HEIGHT + 1), y),
    )


CURSOR_DELTAS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}


def move_cursor(cursor: tuple[int, int], move: str, width: int, height: int) -> tuple[int, int]:
    """Advance the map cursor one cell, clamped to the map's bounds."""
    delta_x, delta_y = CURSOR_DELTAS[move]
    return (
        min(width - 1, max(0, cursor[0] + delta_x)),
        min(height - 1, max(0, cursor[1] + delta_y)),
    )


def audit_co_ids(map: VersusMap, save_profile: Path | None) -> tuple[CoId, ...]:
    """Return the commanders the audit can select for this map.

    A blank cartridge exposes only the fresh-save roster. Asking that roster for a CO it
    does not unlock silently selects whoever the Teams screen is already sitting on, so
    maps needing more than two commanders need a save profile with the COs unlocked.
    """
    if save_profile is None:
        if map.player_count > len(FRESH_SAVE_CO_IDS):
            raise AuditError(
                f"{map.name} seats {map.player_count} commanders, but a fresh Versus save "
                f"only unlocks {', '.join(FRESH_SAVE_CO_IDS)}. Pass --save-profile with the "
                "COs unlocked, or audit a two-player map."
            )
        return FRESH_SAVE_CO_IDS[: map.player_count]
    return AUDIT_CO_IDS[: map.player_count]


def find_camera_offset(
    pack: SpritePack,
    cells: list[GroundCell],
    map: VersusMap,
    image: bytes,
    image_width: int,
    image_height: int,
    art: dict[int, bytes | None],
    center: tuple[int, int] | None = None,
    expected: tuple[int, int] | None = None,
    *,
    cursor: tuple[int, int] | None = None,
) -> tuple[int, int]:
    """Return which map window the screenshot shows.

    The battle view fills the whole 240x160 GBA screen with 16-pixel tiles, so the only
    unknown is the camera's top-left cell. ``center`` narrows the search to the
    neighbourhood of the previous view because one D-pad press pans by at most one cell.

    The cursor constrains which windows are possible. A tracked viewport can resolve
    ties among the remaining windows.
    """
    if image_width != VIEW_WIDTH * TILE or image_height != VIEW_HEIGHT * TILE:
        raise AuditError(
            f"Battle screenshot is {image_width}x{image_height}, expected "
            f"{VIEW_WIDTH * TILE}x{VIEW_HEIGHT * TILE}"
        )
    screen = [
        screen_signature(image, image_width, row, column)
        for row in range(VIEW_HEIGHT)
        for column in range(VIEW_WIDTH)
    ]
    signatures: dict[int, bytes] = {}
    for index, cell in enumerate(cells):
        tile = expected_tile(pack, cells, map.width, index, art)
        signatures[index] = tile_signature(tile) if tile else b"\x00" * 48
    if center is None:
        candidates = camera_offsets(map.width, map.height)
    else:
        radius = 2
        candidates = [
            (x, y)
            for y in range(
                max(0, center[1] - radius),
                min(map.height - VIEW_HEIGHT + 1, center[1] + radius + 1),
            )
            for x in range(
                max(0, center[0] - radius), min(map.width - VIEW_WIDTH + 1, center[0] + radius + 1)
            )
        ]
    if cursor is not None:
        cursor_x, cursor_y = cursor
        candidates = [
            (x, y)
            for x, y in candidates
            if x <= cursor_x < x + VIEW_WIDTH and y <= cursor_y < y + VIEW_HEIGHT
        ]
    best_key: tuple[int, int] | None = None
    tied: list[tuple[int, int]] = []
    for offset_x, offset_y in candidates:
        exact = 0
        distance = 0
        for row in range(VIEW_HEIGHT):
            for column in range(VIEW_WIDTH):
                signature = signatures[(offset_y + row) * map.width + offset_x + column]
                rendered = screen[row * VIEW_WIDTH + column]
                if signature == rendered:
                    exact += 1
                else:
                    distance += sum(abs(a - b) for a, b in zip(signature, rendered))
        key = (exact, -distance)
        if best_key is None or key > best_key:
            best_key, tied = key, [(offset_x, offset_y)]
        elif key == best_key:
            tied.append((offset_x, offset_y))
    if best_key is None:
        raise AuditError("Could not identify the battle camera position in this screenshot")
    if len(tied) == 1:
        return tied[0]
    if expected is not None and expected in tied:
        return expected
    raise AuditError(
        "The battle camera position in this screenshot is ambiguous: "
        f"{len(tied)} candidate windows ({', '.join(f'{x},{y}' for x, y in sorted(tied))}) "
        f"score identically against the atlas ({best_key[0]} cells matched exactly), and no "
        "live cursor position identifies the view. Supply a pack with artwork for these "
        "cells, or audit an emulator that is in a validated battle turn."
    )


def interface_cells(
    image: bytes, image_width: int, offset: tuple[int, int]
) -> set[tuple[int, int]]:
    """Locate the battle HUD by the funds panel's black border and white highlight.

    The funds and terrain status panels switch sides as the cursor moves. The status
    panel is on the opposite side, and its full height depends on the selected cell.
    """
    covered: set[tuple[int, int]] = set()
    for left, start in ((True, 5), (False, image_width - 16)):
        border = (3 * image_width + start) * 4
        highlight = border + image_width * 4
        if image[border : border + 32] != b"\x00\x00\x00\xff" * 8:
            continue
        if image[highlight : highlight + 32] != b"\xff" * 32:
            continue
        funds = range(6) if left else range(VIEW_WIDTH - 6, VIEW_WIDTH)
        status = range(VIEW_WIDTH - 2, VIEW_WIDTH) if left else range(2)
        covered.update((offset[0] + x, offset[1] + y) for x in funds for y in range(3))
        covered.update(
            (offset[0] + x, offset[1] + y) for x in status for y in range(4, VIEW_HEIGHT)
        )
    return covered


def cursor_cells(cursor: tuple[int, int] | None) -> set[tuple[int, int]]:
    """Include the tiles touched by the marker and its offset pointer."""
    if cursor is None:
        return set()
    x, y = cursor
    return {(x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}


def measure_view(
    pack: SpritePack,
    cells: list[GroundCell],
    width: int,
    image: bytes,
    image_width: int,
    offset_x: int,
    offset_y: int,
    results: dict[tuple[int, int], CellMeasurement],
    occupied: set[tuple[int, int]],
    art: dict[int, bytes | None],
    cursor: tuple[int, int] | None = None,
) -> None:
    """Compare every cell of the camera window with the artwork the atlas selects for it.

    A cell the pack has no region for is still measured. Its rendered pixels are the
    evidence that the atlas is missing artwork, so recording it with an empty expectation
    keeps it in the report instead of hiding it among the cells never seen.
    """
    occluded_cells = interface_cells(image, image_width, (offset_x, offset_y))
    occluded_cells.update(cursor_cells(cursor))
    for row in range(VIEW_HEIGHT):
        for column in range(VIEW_WIDTH):
            x, y = offset_x + column, offset_y + row
            index = y * width + x
            cell = cells[index]
            key = (x, y)
            existing = results.get(key)
            region = pack.region_for(cell)
            coverage = opaque_pixels(pack.tile(region)) if region is not None else 0
            expected = expected_tile(pack, cells, width, index, art)
            rendered = rendered_tile(image, image_width, row, column)
            diff = difference(expected, rendered) if expected is not None else 0
            occluded = key in occluded_cells
            overhang = terrain_overhang(pack, cells, index, width) != TRANSPARENT_TILE
            better = existing is None or (occluded, diff) < (
                existing.occluded,
                existing.difference,
            )
            if better:
                results[key] = CellMeasurement(
                    x,
                    y,
                    cell.terrain_class,
                    cell.graphical_tile_id,
                    diff,
                    1 if existing is None else existing.views + 1,
                    unit_on_cell=key in occupied,
                    covered=coverage,
                    covered_by_terrain_overhang=overhang,
                    owner_slot=cell.owner_slot,
                    has_own_artwork=region is not None,
                    view=(offset_x, offset_y),
                    row=row,
                    column=column,
                    rendered=rendered,
                    occluded=occluded,
                )
            elif existing is not None:
                existing.views += 1


def composite(ground: bytes, overhang: bytes) -> bytes:
    """Paint an overhang sprite over a cell's ground, skipping transparent pixels."""
    result = bytearray(ground)
    for pixel in range(0, TILE * TILE * 4, 4):
        if overhang[pixel + 3]:
            result[pixel : pixel + 4] = overhang[pixel : pixel + 4]
    return bytes(result)


def bounded_difference(left: bytes, right: bytes, limit: int | None) -> int:
    """Like difference(), but stop early once the total passes ``limit``.

    The stopped value is still larger than ``limit``, so a caller ranking candidates by
    this score can never pick a truncated candidate over a fully measured one. The limit
    must be the current best candidate's score, not the selected region's difference: a
    fully transparent selected region has a difference of zero, which would stop every
    candidate at its first differing pixel and make all of them look close.
    """
    total = 0
    for index in range(0, len(left), 4):
        if left[index + 3]:
            total += abs(left[index] - right[index]) + abs(left[index + 1] - right[index + 1])
            total += abs(left[index + 2] - right[index + 2])
            if limit is not None and total > limit:
                return total
    return total


def add_nearest_artwork(
    pack: SpritePack,
    cells: list[GroundCell],
    map_width: int,
    results: dict[tuple[int, int], CellMeasurement],
) -> None:
    """For every unmatched cell, find the closest atlas artwork of any terrain class.

    A close match under a different key means the client is selecting the wrong region.
    Nothing close at all means mGBA drew something the atlas has no artwork for, such as
    the CO panels, a unit, or a property in an army colour the pack never captured.
    """
    for measurement in results.values():
        if (
            measurement.matched
            or measurement.occluded
            or measurement.unit_on_cell
            or measurement.nearest_other_region is not None
        ):
            continue
        index = measurement.y * map_width + measurement.x
        cell = cells[index]
        selected = pack.region_identity(cell)
        overhang = terrain_overhang(pack, cells, index, map_width)
        best: tuple[str, str] | None = None
        best_diff: int | None = None
        for collection, key, ground in pack.artwork():
            if (collection, key) == selected:
                continue
            if opaque_pixels(ground) == 0:
                # Invisible artwork cannot be what the emulator drew. Scoring it anyway
                # makes a cell the emulator painted look almost identical to nothing.
                continue
            candidate = composite(ground, overhang)
            diff = bounded_difference(candidate, measurement.rendered, best_diff)
            if best_diff is None or diff < best_diff:
                best, best_diff = (collection, key), diff
        if best is not None:
            measurement.nearest_other_collection, measurement.nearest_other_region = best
        measurement.nearest_other_difference = best_diff


def sweep_moves(map: VersusMap) -> list[str]:
    """Walk the cursor over every cell of the map, row by row.

    The battle camera scrolls one cell per D-pad press once the cursor reaches the
    viewport edge, so a cursor that visits every cell drags the viewport through every
    camera offset and each cell is measured from at least one view.
    """
    moves = ["up"] * map.height + ["left"] * map.width
    for row in range(map.height):
        direction = "right" if row % 2 == 0 else "left"
        moves.extend([direction] * (map.width - 1))
        if row < map.height - 1:
            moves.append("down")
    return moves


def write_comparison_tiles(
    pack: SpritePack,
    cells: list[GroundCell],
    map_width: int,
    report: AuditReport,
    tiles_dir: Path,
) -> list[str]:
    """Write one PNG per unmatched cell: atlas artwork on the left, mGBA on the right.

    Reviewing these side by side is how a mismatch becomes a concrete extraction bug, so
    the audit leaves them next to the screenshots instead of asking a human to crop them.
    """
    tiles_dir.mkdir(parents=True, exist_ok=True)
    art: dict[int, bytes | None] = {}
    width = TILE * 2 + 1
    paths: list[str] = []
    for cell in sorted(report.cells.values(), key=lambda item: -item.difference):
        if cell.matched:
            continue
        expected = expected_tile(pack, cells, map_width, cell.y * map_width + cell.x, art)
        if expected is None:
            # A visible cell the pack has no region for is exactly the gap a reviewer needs
            # to see, so the atlas half is drawn transparent rather than skipped.
            expected = TRANSPARENT_TILE
        pixels = bytearray()
        for row in range(TILE):
            for column in range(width):
                if column == TILE:
                    pixels.extend(b"\x00\x00\x00\xff")
                elif column < TILE:
                    offset = (row * TILE + column) * 4
                    pixels.extend(expected[offset : offset + 4])
                else:
                    offset = (row * TILE + column - TILE - 1) * 4
                    pixels.extend(cell.rendered[offset : offset + 4])
        name = f"mismatch-{cell.x}-{cell.y}-{cell.terrain_class}-{cell.graphical_tile_id}.png"
        path = tiles_dir / name
        path.write_bytes(encode_png(width, TILE, bytes(pixels)))
        paths.append(str(path))
    return paths


async def take_screenshot(
    bridge: LuaBridgeClient, directory: Path, index: int
) -> tuple[bytes, int, int]:
    """Return the screenshot pixels and their dimensions.

    mGBA resolves the filename against its own working directory, not the audit's, so the
    path handed to the bridge is absolute.
    """
    filename = directory.expanduser().resolve() / f"audit-{index:03d}.png"
    result = await bridge.request("screenshot", filename=str(filename))
    encoded = result.get("png_base64")
    if not isinstance(encoded, str):
        raise AuditError("Lua bridge screenshot did not return PNG data")
    width, height, pixels = decode_png(base64.b64decode(encoded))
    return pixels, width, height


async def audit_map(
    bridge: LuaBridgeClient,
    pack: SpritePack,
    map_id: str,
    rom_path: Path,
    screenshots_dir: Path,
    max_screenshots: int,
    animation_frames: int | None,
    tiles_dir: Path | None = None,
    state: GameState | None = None,
) -> AuditReport:
    """Measure every viewport of ``map_id`` on the emulator the bridge serves.

    The emulator must be sitting in a validated battle turn: the live map gives the real
    terrain classes and property owners, and the map cursor identifies which camera window
    a screenshot shows. ``state`` lets a caller reuse a GameState it already captured.
    """
    map = MAPS_BY_ID[map_id]
    screenshots_dir = screenshots_dir.expanduser().resolve()
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    if state is None:
        state = await capture_game_state(bridge, rom_path=rom_path)
    battle = state.battle
    if battle.status is not ValueStatus.AVAILABLE or battle.value is None:
        raise AuditError(
            f"The bridge is not in a validated battle turn, so the audit cannot measure the "
            f"live map for {map.name}: "
            f"{'; '.join(battle.reasons) or 'no battle'}. Start a match with "
            "aw2-lab play and leave it idle, or let the audit boot its own emulator by "
            "omitting --attach-live/--run-dir."
        )
    turn: BattleState = battle.value
    identity = await bridge.read_memory_snapshot([(BATTLE_MAP_ID_ADDRESS, 1)])
    if identity.frame != state.frame:
        raise AuditError("The emulator frame changed while verifying the live map")
    cells = cells_from_state(turn, identity.ranges[0][0], map)
    occupied = {(unit.x, unit.y) for unit in turn.units}
    report = AuditReport(
        map_id,
        map.name,
        map.width,
        map.height,
        str(pack.directory),
        turn.day,
    )
    cursor_observation = state.ui.map_cursor
    cursor: tuple[int, int] | None = None
    if (
        cursor_observation.status is CursorStatus.AVAILABLE
        and cursor_observation.x is not None
        and cursor_observation.y is not None
    ):
        cursor = (cursor_observation.x, cursor_observation.y)
    views: set[tuple[int, int]] = set()
    results: dict[tuple[int, int], CellMeasurement] = {}
    art: dict[int, bytes | None] = {}
    probes: list[dict[str, Any]] = []
    index = 0
    center: tuple[int, int] | None = None
    if animation_frames:
        # One view only samples the animation phase it happens to land on, so probe the
        # view before the sweep and the view the sweep ends on. These probes are not part
        # of the sweep, so --max-screenshots does not cut them off.
        probes.append(
            await check_animation(
                bridge,
                pack,
                cells,
                map,
                animation_frames,
                screenshots_dir,
                index,
                occupied,
                art,
                cursor,
            )
        )
        index += 2
        report.screenshots += 2
        probe_x, probe_y = probes[-1]["view"]
        center = (probe_x, probe_y)
    for swept, move in enumerate([""] + sweep_moves(map)):
        if swept >= max_screenshots:
            break
        expected_offset = center
        if move:
            expected_offset = None
            if cursor is not None:
                cursor = move_cursor(cursor, move, map.width, map.height)
                if center is not None:
                    expected_offset = camera_window(center, cursor)
            await bridge.press_keys(DIRECTIONS[move], PRESS_FRAMES)
            await bridge.advance_frames(SETTLE_FRAMES)
        image, image_width, image_height = await take_screenshot(bridge, screenshots_dir, index)
        index += 1
        report.screenshots += 1
        offset_x, offset_y = find_camera_offset(
            pack,
            cells,
            map,
            image,
            image_width,
            image_height,
            art,
            center,
            expected_offset,
            cursor=cursor,
        )
        center = (offset_x, offset_y)
        if (offset_x, offset_y) not in views:
            views.add((offset_x, offset_y))
            report.views.append((offset_x, offset_y))
        # Measure every screenshot, not just the first one per offset: the cursor and the
        # status panel move without scrolling the view, so a later capture of the same
        # window can show ground the earlier one hid.
        measure_view(
            pack,
            cells,
            map.width,
            image,
            image_width,
            offset_x,
            offset_y,
            results,
            occupied,
            art,
            cursor,
        )
    report.cells = results
    add_nearest_artwork(pack, cells, map.width, results)
    report.never_in_view = [(cell.x, cell.y) for cell in cells if (cell.x, cell.y) not in results]
    if animation_frames:
        probes.append(
            await check_animation(
                bridge,
                pack,
                cells,
                map,
                animation_frames,
                screenshots_dir,
                index,
                occupied,
                art,
                cursor,
                camera_hint=center,
            )
        )
        index += 2
        report.screenshots += 2
        report.animation = merge_animation(probes, animation_frames)
        report.animated_regions = set(report.animation["changed_regions"])
    if tiles_dir is not None:
        report.tile_images = write_comparison_tiles(
            pack, cells, map.width, report, tiles_dir.expanduser().resolve()
        )
    return report


def merge_animation(probes: list[dict[str, Any]], frames: int) -> dict[str, Any]:
    """Combine the per-view animation probes into one picture of what cycles in the game.

    Views can overlap, so the merged report unions both the region keys and the cell
    coordinates: a region key counts how many distinct regions cycle, while the cell set
    counts how many cells actually changed.
    """
    changed: dict[str, int] = {}
    changed_cells: set[tuple[int, int]] = set()
    excluded: dict[str, int] = {}
    for probe in probes:
        for key, diff in probe["changed_regions"].items():
            changed[key] = max(changed.get(key, 0), diff)
        changed_cells.update(tuple(cell) for cell in probe["changed_cells"])
        for reason, count in probe["cells_excluded"].items():
            excluded[reason] = excluded.get(reason, 0) + count
    return {
        "frames_between_screenshots": frames,
        "views_checked": [list(probe["view"]) for probe in probes],
        "changed_regions": changed,
        "changed_cells": sorted(changed_cells),
        "cells_changed": len(changed_cells),
        "cells_excluded": excluded,
        "largest_difference": max((probe["largest_difference"] for probe in probes), default=0),
        "probes": probes,
    }


async def check_animation(
    bridge: LuaBridgeClient,
    pack: SpritePack,
    cells: list[GroundCell],
    map: VersusMap,
    frames: int,
    screenshots_dir: Path,
    index: int,
    occupied: set[tuple[int, int]],
    art: dict[int, bytes | None],
    cursor: tuple[int, int] | None = None,
    *,
    camera_hint: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Diff two screenshots of the same view to find terrain that cycles in the game.

    Only unobstructed ground counts as evidence. Properties can draw effects on the tile
    above them even when the atlas frame has a transparent top half.
    """
    first, image_width, image_height = await take_screenshot(bridge, screenshots_dir, index)
    offset = find_camera_offset(
        pack,
        cells,
        map,
        first,
        image_width,
        image_height,
        art,
        expected=camera_hint,
        cursor=cursor,
    )
    offset_x, offset_y = offset
    await bridge.advance_frames(frames)
    second, second_width, second_height = await take_screenshot(bridge, screenshots_dir, index + 1)
    if (second_width, second_height) != (image_width, image_height):
        raise AuditError("Screenshot dimensions changed between animation frames")
    hud = interface_cells(first, image_width, offset) | interface_cells(second, image_width, offset)
    cursor_overlay = cursor_cells(cursor)
    changed: dict[str, int] = {}
    changed_cells: list[tuple[int, int]] = []
    excluded: dict[str, int] = {}
    largest = 0
    for row in range(VIEW_HEIGHT):
        for column in range(VIEW_WIDTH):
            x, y = offset_x + column, offset_y + row
            index_key = (x, y)
            cell_index = y * map.width + x
            cell = cells[cell_index]
            earlier = rendered_tile(first, image_width, row, column)
            later = rendered_tile(second, image_width, row, column)
            diff = difference(earlier, later)
            if not diff:
                continue
            if index_key in occupied:
                excluded["unit_on_cell"] = excluded.get("unit_on_cell", 0) + 1
                continue
            if index_key in cursor_overlay:
                excluded["map_cursor"] = excluded.get("map_cursor", 0) + 1
                continue
            if index_key in hud:
                excluded["hud"] = excluded.get("hud", 0) + 1
                continue
            if (
                y + 1 < map.height
                and cells[cell_index + map.width].terrain_class in PROPERTY_CLASSES
            ):
                excluded["property_overlay"] = excluded.get("property_overlay", 0) + 1
                continue
            region = pack.region_for(cell)
            if region is None:
                excluded["no_packed_region"] = excluded.get("no_packed_region", 0) + 1
                continue
            ground = pack.tile(region)
            if opaque_pixels(ground) < MIN_GROUND_COVERAGE:
                excluded["thin_ground_artwork"] = excluded.get("thin_ground_artwork", 0) + 1
                continue
            if terrain_overhang(pack, cells, cell_index, map.width) != TRANSPARENT_TILE:
                excluded["terrain_overhang"] = excluded.get("terrain_overhang", 0) + 1
                continue
            # Establish that at least one sample actually shows this region. Otherwise
            # the change could come from misaligned artwork or an unknown overlay.
            if min(difference(ground, earlier), difference(ground, later)) > MATCH_TOLERANCE:
                excluded["unverified_ground"] = excluded.get("unverified_ground", 0) + 1
                continue
            diff = difference(earlier, later, mask=ground)
            if not diff:
                continue
            key = f"{cell.terrain_class}:{cell.graphical_tile_id}"
            changed[key] = max(changed.get(key, 0), diff)
            changed_cells.append(index_key)
            largest = max(largest, diff)
    return {
        "frames_between_screenshots": frames,
        "view": [offset_x, offset_y],
        "cells_checked": VIEW_WIDTH * VIEW_HEIGHT,
        "cells_changed": len(changed_cells),
        "changed_cells": sorted(changed_cells),
        "cells_excluded": excluded,
        "largest_difference": largest,
        "changed_regions": dict(sorted(changed.items(), key=lambda item: -item[1])),
    }


def bridge_identity_from_run(run_dir: Path) -> tuple[int, str]:
    match_file = run_dir / "match.json"
    if not match_file.is_file():
        raise AuditError(
            f"{match_file} is missing; start a match with aw2-lab play and pass its run directory"
        )
    try:
        metadata = json.loads(match_file.read_text())
    except (OSError, ValueError) as error:
        raise AuditError(f"Cannot read bridge metadata from {match_file}: {error}") from error
    if not isinstance(metadata, dict):
        raise AuditError(f"{match_file} must contain a JSON object")
    port = metadata.get("bridge_port")
    if type(port) is not int or not 1 <= port <= 65535:
        raise AuditError(f"{match_file} does not record a valid bridge port")
    instance = metadata.get("bridge_instance")
    if not isinstance(instance, str) or not instance:
        raise AuditError(
            f"{match_file} does not record a bridge instance. Start a new match with "
            "this version of aw2-lab, or verify the running emulator and use --attach-live."
        )
    return port, instance


def bridge_port_is_free(port: int) -> bool:
    """True when nothing on loopback is already listening on this bridge port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        try:
            probe.connect(("127.0.0.1", port))
        except OSError:
            return True
        return False


@asynccontextmanager
async def isolated_bridge(settings: EmulatorSettings) -> AsyncIterator[LuaBridgeClient]:
    """Run an mGBA instance the audit owns.

    The camera sweep presses D-pad buttons and advances hundreds of frames. Sent to the
    emulator that is serving a match, that would put the running frame past the boundary
    the controller committed, and the next gameplay command would fail with
    RECOVERY_REQUIRED. The audit therefore boots its own cartridge into the map it is
    asked to measure.
    """
    if not bridge_port_is_free(settings.bridge_port):
        raise AuditError(
            f"bridge port {settings.bridge_port} is already serving an emulator. Pass a "
            f"different --bridge-port, stop that emulator, or use --attach-live {settings.bridge_port} "
            "to audit the emulator that is already running instead of starting a second one."
        )
    launcher = EmulatorLauncher(settings, isolate_saves=True)
    try:
        await launcher.start()
        bridge = launcher.bridge
        if bridge is None:
            raise AuditError("the audit emulator did not expose a Lua bridge")
        yield bridge
    finally:
        await launcher.stop()


async def restore_bridge_state(bridge: LuaBridgeClient, snapshot: tuple[bytes, int]) -> None:
    """Return an attached emulator to the frame the audit started from.

    Raises AuditError when the state cannot be loaded, or when the emulator lands on a
    different frame than the snapshot recorded: a silent partial restore leaves the match's
    controller and emulator out of step.
    """
    state, before = snapshot
    try:
        after = await bridge.load_state_buffer(state)
    except BridgeError as error:
        raise AuditError(
            f"the audit could not restore the attached emulator to its pre-audit state: {error}"
        ) from error
    if after != before:
        raise AuditError(
            f"the attached emulator was restored to frame {after} instead of frame {before}; "
            "the match's controller no longer matches its emulator"
        )


async def finish_on_sigterm(audit: Awaitable[AuditReport]) -> AuditReport:
    """Cancel the audit once and let its cleanup finish before exiting."""
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    assert task is not None
    previous = signal.getsignal(signal.SIGTERM)
    terminating = False

    def terminate() -> None:
        nonlocal terminating
        if not terminating:
            terminating = True
            task.cancel()

    loop.add_signal_handler(signal.SIGTERM, terminate)
    try:
        return await audit
    except asyncio.CancelledError:
        if terminating:
            raise SystemExit(128 + signal.SIGTERM) from None
        raise
    finally:
        loop.remove_signal_handler(signal.SIGTERM)
        signal.signal(signal.SIGTERM, previous)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="aw2-lab sprite-audit", description=__doc__)
    result.add_argument(
        "--map",
        required=True,
        choices=tuple(MAPS_BY_ID),
        help="catalog map id to boot in the audit's own emulator",
    )
    result.add_argument("--rom", type=Path, help="AW2 ROM (default: AW2_ROM_PATH)")
    result.add_argument(
        "--pack",
        type=Path,
        default=Path(os.environ.get("AW2_CLIENT_SPRITES", "~/.local/share/aw2-lab/sprites")),
        help="directory holding manifest.json and the atlas",
    )
    result.add_argument(
        "--save-profile",
        type=Path,
        help="mGBA or GameShark save to start the audit emulator from (for unlocked COs)",
    )
    result.add_argument(
        "--save-mode",
        choices=("existing", "fresh"),
        default="existing",
        help="how the audit emulator answers the Versus overwrite prompt (default: existing)",
    )
    result.add_argument(
        "--emulator-mode",
        choices=("headless", "windowed"),
        default=os.environ.get("AW2_EMULATOR_MODE", "headless"),
        help="mGBA frontend for the audit (default: headless)",
    )
    result.add_argument(
        "--mgba-headless",
        help="headless mGBA executable for the audit emulator (default: mgba-headless)",
    )
    result.add_argument(
        "--bridge-port",
        type=int,
        default=DEFAULT_AUDIT_BRIDGE_PORT,
        help=f"bridge port for the audit's own emulator (default: {DEFAULT_AUDIT_BRIDGE_PORT})",
    )
    result.add_argument(
        "--attach-live",
        type=int,
        metavar="BRIDGE_PORT",
        help=(
            "audit an emulator that is already serving a match instead of booting one. The "
            "sweep presses D-pad buttons on that emulator; the audit restores its state at "
            "the end, but the match must be idle for the whole audit."
        ),
    )
    result.add_argument(
        "--run-dir",
        type=Path,
        help="private directory printed by aw2-lab play, to attach to that match's bridge",
    )
    result.add_argument("--output", type=Path, help="write the full report as JSON")
    result.add_argument("--screenshots-dir", type=Path, help="where to keep audit screenshots")
    result.add_argument(
        "--max-screenshots",
        type=int,
        default=DEFAULT_MAX_SCREENSHOTS,
        help="cap on sweep screenshots, excluding the animation probes (default: enough for "
        "the largest catalog map)",
    )
    result.add_argument(
        "--animation-frames",
        type=int,
        default=0,
        help="also diff two screenshots this many frames apart (0 disables)",
    )
    result.add_argument(
        "--tiles-dir",
        type=Path,
        help="write a side-by-side atlas-versus-emulator PNG for each mismatch here",
    )
    return result


def main(argv: list[str] | None = None) -> None:
    arguments = parser()
    args = arguments.parse_args(argv)
    if args.max_screenshots < 1:
        arguments.error("--max-screenshots must be at least 1")
    if not 0 <= args.animation_frames <= 600:
        arguments.error("--animation-frames must be between 0 and 600")
    rom_path = (args.rom or Path(os.environ.get("AW2_ROM_PATH", ""))).expanduser().resolve()
    if not rom_path.is_file():
        arguments.error("an AW2 ROM is required; provide --rom or set AW2_ROM_PATH")
    pack = SpritePack(args.pack.expanduser().resolve())
    screenshots = (args.screenshots_dir or args.run_dir or Path("sprite-audit")).expanduser()
    screenshots.mkdir(parents=True, exist_ok=True)
    tiles_dir = args.tiles_dir.expanduser().resolve() if args.tiles_dir else None
    map = MAPS_BY_ID[args.map]

    async def run() -> AuditReport:
        if args.run_dir is not None or args.attach_live is not None:
            port, instance = args.attach_live, None
            if args.run_dir is not None:
                port, instance = bridge_identity_from_run(args.run_dir.expanduser().resolve())
            bridge = LuaBridgeClient(port=port, instance=instance)
            if instance is not None:
                await bridge.connect()
            print(
                f"Attaching to the match emulator on bridge port {port}. The sweep presses "
                "D-pad buttons on it, so keep that match idle; the audit restores its state "
                "when it finishes."
            )
            snapshot = await bridge.save_state_buffer_with_frame()
            try:
                return await audit_map(
                    bridge,
                    pack,
                    args.map,
                    rom_path,
                    screenshots,
                    args.max_screenshots,
                    args.animation_frames,
                    tiles_dir,
                )
            finally:
                restore = asyncio.create_task(restore_bridge_state(bridge, snapshot))
                try:
                    await asyncio.shield(restore)
                except asyncio.CancelledError:
                    await restore
                    raise
        settings = EmulatorSettings(
            rom_path=rom_path,
            save_profile_path=(
                args.save_profile.expanduser().resolve() if args.save_profile else None
            ),
            mode=EmulatorMode(args.emulator_mode),
            headless_executable=args.mgba_headless,
            bridge_port=args.bridge_port,
            use_adjacent_save=False,
            suppress_emulator_output=True,
        )
        async with isolated_bridge(settings) as bridge:
            print(
                f"Booting an isolated {args.emulator_mode} mGBA into {map.name} on bridge "
                f"port {args.bridge_port}"
            )
            try:
                boot = await boot_fixed_versus_match(
                    bridge,
                    rom_path=rom_path,
                    map_id=args.map,
                    co_ids=audit_co_ids(map, args.save_profile),
                    save_mode=args.save_mode,
                    fresh_roster=args.save_profile is None,
                )
            except ColdBootError as error:
                raise AuditError(
                    f"Could not start {map.name} in the audit emulator: {error}"
                ) from error
            if boot.map_id != map.rom_id:
                raise AuditError(
                    f"The audit emulator reached ROM map {boot.map_id} instead of {map.name} "
                    f"(ROM map {map.rom_id})"
                )
            return await audit_map(
                bridge,
                pack,
                args.map,
                rom_path,
                screenshots,
                args.max_screenshots,
                args.animation_frames,
                tiles_dir,
            )

    try:
        report = asyncio.run(finish_on_sigterm(run()))
    except (AuditError, BridgeError, EmulatorLaunchError, ColdBootError) as error:
        arguments.exit(1, f"Sprite audit failed: {error}\n")
        return
    summary = report.summary()
    if args.output:
        args.output.expanduser().write_text(json.dumps(summary, indent=2) + "\n")
    print(f"{summary['map_name']} ({summary['width']}x{summary['height']}) day {summary['day']}")
    print(
        f"  {summary['screenshots']} screenshots, {len(summary['views'])} distinct views, "
        f"{summary['cells_measured']} cells measured, {summary['cells_never_in_view']} never in view"
    )
    print(
        f"  matched {summary['cells_matched']}, mismatched {summary['cells_mismatched']} "
        f"({summary['cells_wrong_region']} picked the wrong atlas region, "
        f"{summary['cells_no_nearby_artwork']} have no nearby packed artwork, "
        f"{summary['cells_animated']} animated, "
        f"{summary['cells_occluded']} covered by HUD or cursor); "
        f"largest matched difference {summary['largest_matched_difference']} points"
    )
    if summary["cells_partial_artwork"]:
        print(
            f"  {summary['cells_partial_artwork']} cells have a packed region covering less "
            "than three quarters of the cell"
        )
    for terrain_class, counts in summary["by_terrain_class"].items():
        print(
            f"  class {terrain_class}: {counts['cells']} cells, {counts['matched']} matched, "
            f"{counts['mismatched']} mismatched"
        )
    for verdict, count in summary["verdicts"].items():
        print(f"  {count} mismatch(es): {verdict}")
    for mismatch in summary["mismatches"][:10]:
        decoy = (
            f"nearest atlas artwork is {mismatch['nearest_other_collection']}/"
            f"{mismatch['nearest_other_region']} at "
            f"{mismatch['nearest_other_difference']}"
            if mismatch["nearest_other_difference"] is not None
            else ""
        )
        nearest = f" [{decoy}]" if decoy else ""
        unit = " (unit sprite on the cell)" if mismatch["unit_on_cell"] else ""
        print(
            f"  mismatch ({mismatch['x']},{mismatch['y']}) "
            f"{mismatch['terrain_class']}:{mismatch['graphical_tile_id']} "
            f"difference {mismatch['difference']}: {mismatch['verdict']}"
            f"{nearest}{unit}"
        )
    animation = summary["animation"]
    if animation:
        samples = "; ".join(
            f"{probe['cells_changed']} of {probe['cells_checked']} cells changed in view "
            f"{probe['view'][0]},{probe['view'][1]}"
            for probe in animation["probes"]
        )
        print(
            f"  animation: {len(animation['changed_regions'])} terrain region(s) cycle over "
            f"{animation['frames_between_screenshots']} frames "
            f"(largest difference {animation['largest_difference']}): {samples}"
        )
    if args.output:
        print(f"Report: {args.output}")


if __name__ == "__main__":
    main()
