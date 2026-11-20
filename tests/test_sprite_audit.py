"""Tests for the emulator-versus-atlas sprite audit."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import signal
import struct
import sys
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from aw2_lab.bridge import BridgeError, LuaBridgeClient, MemorySnapshot
from aw2_lab.cli import main
from aw2_lab.emulator import EmulatorMode, EmulatorSettings
from aw2_lab.map_catalog import MAPS_BY_ID, MapCategory, VersusMap
from aw2_lab.sprite_audit import (
    DEFAULT_AUDIT_BRIDGE_PORT,
    MATCH_TOLERANCE,
    TILE,
    TRANSPARENT_TILE,
    VIEW_HEIGHT,
    VIEW_WIDTH,
    AuditError,
    AuditReport,
    CellMeasurement,
    GroundCell,
    SpritePack,
    add_nearest_artwork,
    audit_co_ids,
    audit_map,
    camera_window,
    cells_from_state,
    check_animation,
    decode_png,
    difference,
    expected_tile,
    find_camera_offset,
    isolated_bridge,
    measure_view,
    merge_animation,
    move_cursor,
    rendered_tile,
    rom_map_cells,
    sweep_moves,
    terrain_overhang,
    write_comparison_tiles,
)
from aw2_lab.state_model import ValueStatus
from aw2_lab.state_validation import BATTLE_MAP_ID_ADDRESS
from aw2_lab.ui_state import CursorStatus

PEAK = (255, 120, 40, 255)  # the top half of a 16x32 mountain frame
MOUNTAIN = (99, 204, 122, 255)
PLAINS = (220, 180, 80, 255)
WATER = (30, 60, 200, 255)
DRIFT = (60, 90, 230, 255)  # water one animation frame later
SAND = (150, 140, 110, 255)


def solid(color: tuple[int, int, int, int]) -> bytes:
    """One 16x16 block painted in a single colour."""
    return bytes(color * TILE * TILE)


def paint(atlas: bytearray, atlas_width: int, x: int, y: int, pixels: bytes) -> None:
    """Copy a 16-wide strip of pixels into the atlas at (x, y)."""
    rows = len(pixels) // (TILE * 4)
    for row in range(rows):
        start = ((y + row) * atlas_width + x) * 4
        atlas[start : start + TILE * 4] = pixels[row * TILE * 4 : (row + 1) * TILE * 4]


def png(width: int, height: int, pixels: bytes) -> bytes:
    """Encode 8-bit RGBA pixels as a PNG with no row filtering."""
    raw = b"".join(
        b"\x00" + pixels[row * width * 4 : (row + 1) * width * 4] for row in range(height)
    )

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def make_pack(directory: Path) -> SpritePack:
    """An atlas holding a mountain frame, plains, water, and a mostly empty frame.

    Like the real pack, frames that are not tall terrain keep their top half transparent,
    so only mountains, headquarters, and cities paint over the cell above them. The `1:1`
    frame covers only eight rows, which is how a thin or missing artwork region shows up.
    """
    atlas = bytearray(64 * 32 * 4)
    paint(atlas, 64, 0, 0, solid(PEAK))  # the half a mountain draws on the cell above
    paint(atlas, 64, 0, TILE, solid(MOUNTAIN))  # the mountain's own ground
    paint(atlas, 64, 16, TILE, solid(PLAINS))
    paint(atlas, 64, 32, TILE, solid(WATER))
    paint(atlas, 64, 48, TILE, solid(PLAINS)[: TILE * 4 * 8])  # eight rows of ground only
    frame = {"width": TILE, "height": TILE * 2}
    manifest = {
        "atlas": "atlas.png",
        "width": 64,
        "height": 32,
        "terrain": {"1:0": {"x": 16, "y": 0, **frame}},
        "terrain_variants": {
            "2:71": {"x": 0, "y": 0, **frame},
            "1:0": {"x": 16, "y": 0, **frame},
            "1:1": {"x": 48, "y": 0, **frame},
            "5:12": {"x": 32, "y": 0, **frame},
        },
    }
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "atlas.png").write_bytes(png(64, 32, bytes(atlas)))
    (directory / "manifest.json").write_text(json.dumps(manifest))
    return SpritePack(directory)


class FakeBridge(LuaBridgeClient):
    """A stand-in for the Lua bridge that replays canned battle screenshots."""

    def __init__(
        self,
        images: list[tuple[int, int, bytes]],
        *,
        fail_restore: bool = False,
        missing_frame_on: str | None = None,
        map_id: int | None = None,
    ) -> None:
        super().__init__()
        self.images = list(images)
        self.operations: list[str] = []
        self.filenames: list[str] = []
        self.frames = 0
        self.restored_state: str | None = None
        self.fail_restore = fail_restore
        self.missing_frame_on = missing_frame_on
        self.map_id = map_id

    def _image(self) -> tuple[int, int, bytes]:
        return self.images.pop(0) if len(self.images) > 1 else self.images[0]

    async def request(self, operation: str, **params: object) -> dict[str, object]:
        self.operations.append(operation)
        if operation == "screenshot":
            filename = str(params["filename"])
            self.filenames.append(filename)
            width, height, pixels = self._image()
            return {"png_base64": base64.b64encode(png(width, height, pixels)).decode()}
        if operation == "save_state_buffer":
            snapshot = {"state_base64": base64.b64encode(b"saved-state").decode()}
            if self.missing_frame_on == operation:
                return snapshot
            return {**snapshot, "frame": self.frames}
        if operation == "load_state_buffer":
            if self.fail_restore:
                raise BridgeError("the fake emulator refused the state load")
            self.restored_state = str(params["state_base64"])
            if self.missing_frame_on == operation:
                return {}
            return {"frame": self.frames}
        return {"frame": self.frames}

    async def advance_frames(self, frames: int) -> dict[str, int]:
        self.operations.append("advance_frames")
        self.frames += frames
        return {"frame": self.frames}

    async def read_memory_snapshot(self, ranges: list[tuple[int, int]]) -> MemorySnapshot:
        if self.map_id is not None and ranges == [(BATTLE_MAP_ID_ADDRESS, 1)]:
            return MemorySnapshot(self.frames, (bytes([self.map_id]),))
        raise BridgeError("the fake bridge cannot read emulator memory")

    async def press_keys(self, keys: tuple[int, ...], frames: int) -> dict[str, int]:
        self.operations.append("press_keys")
        return {"frame": self.frames}


def plains_cells(
    width: int, height: int, overrides: dict[tuple[int, int], GroundCell]
) -> list[GroundCell]:
    cells = [GroundCell(column, row, 0, 1, 0) for row in range(height) for column in range(width)]
    for (x, y), cell in overrides.items():
        cells[y * width + x] = cell
    return cells


def battle_window(
    pack: SpritePack,
    cells: list[GroundCell],
    width: int,
    overrides: dict[tuple[int, int], bytes] | None = None,
) -> tuple[int, int, bytes]:
    """Paint the 15x10 battle window the atlas expects at camera offset (0, 0).

    Cells are interleaved in the 240x160 pixel grid, so one 16x16 tile is 16 rows of 64
    bytes at a 960-byte stride, not 1024 contiguous bytes.
    """
    cache: dict[int, bytes | None] = {}
    image = bytearray(VIEW_WIDTH * TILE * VIEW_HEIGHT * TILE * 4)
    overrides = overrides or {}
    for row in range(VIEW_HEIGHT):
        for column in range(VIEW_WIDTH):
            tile = overrides.get((column, row)) or (
                expected_tile(pack, cells, width, row * width + column, cache) or TRANSPARENT_TILE
            )
            for tile_row in range(TILE):
                start = (((row * TILE + tile_row) * VIEW_WIDTH + column) * TILE) * 4
                image[start : start + TILE * 4] = tile[
                    tile_row * TILE * 4 : (tile_row + 1) * TILE * 4
                ]
    return VIEW_WIDTH * TILE, VIEW_HEIGHT * TILE, bytes(image)


def live_state(
    cells: list[GroundCell],
    entry: VersusMap,
    cursor: tuple[int, int] | None = None,
    day: int = 1,
) -> SimpleNamespace:
    """A stand-in for the GameState the decoder reports for a settled battle turn.

    The audit needs the live map (terrain classes and property owners) and the map cursor
    (which camera window a screenshot is showing). The fake bridge cannot read emulator
    memory, so these tests hand the observation to the audit directly.
    """
    tiles = [
        SimpleNamespace(
            x=cell.x,
            y=cell.y,
            graphical_tile_id=cell.graphical_tile_id,
            terrain_class=cell.terrain_class,
            owner_slot=cell.owner_slot,
        )
        for cell in cells
    ]
    battle = SimpleNamespace(
        day=day,
        units=[],
        map=SimpleNamespace(width=entry.width, height=entry.height, tiles=tiles),
    )
    if cursor is None:
        cursor_observation = SimpleNamespace(
            status=CursorStatus.UNAVAILABLE, x=None, y=None, reasons=("no cursor observed",)
        )
    else:
        cursor_observation = SimpleNamespace(
            status=CursorStatus.AVAILABLE, x=cursor[0], y=cursor[1]
        )
    return SimpleNamespace(
        frame=0,
        battle=SimpleNamespace(status=ValueStatus.AVAILABLE, value=battle, reasons=()),
        ui=SimpleNamespace(map_cursor=cursor_observation),
    )


def test_sprite_pack_prefers_the_cells_own_variant(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    mountain = pack.region_for(GroundCell(3, 1, 71, 2, 0))
    assert mountain == {"x": 0, "y": 0, "width": TILE, "height": TILE * 2}
    assert pack.tile(mountain) == solid(MOUNTAIN)
    assert pack.top_rows(mountain) == solid(PEAK)

    # A class without per-cell artwork falls back to the class-and-owner representative.
    assert pack.region_for(GroundCell(0, 0, 0, 1, 0)) == {
        "x": 16,
        "y": 0,
        "width": TILE,
        "height": 32,
    }
    assert pack.top_rows(pack.manifest["terrain"]["1:0"]) == bytes(TILE * TILE * 4)
    assert pack.region_for(GroundCell(0, 0, 0, 13, 0)) is None
    assert pack.class_variants(2) == ["2:71"]
    assert {key for _, key, _ in pack.artwork()} == {"1:0", "1:1", "2:71", "5:12"}


def test_rendered_tile_extracts_one_cell_of_the_screenshot() -> None:
    image = bytes((index % 255) + 1 for index in range((TILE * 2) * (TILE * 2) * 4))
    tile = rendered_tile(image, TILE * 2, 1, 1)
    assert len(tile) == TILE * TILE * 4
    start = (TILE * TILE * 2 + TILE) * 4  # first pixel of the cell at row 1, column 1
    assert tile[:4] == image[start : start + 4]
    # Pixels run contiguously inside a screenshot row, and each tile row is one
    # screenshot row further down the image.
    assert tile[4:8] == image[start + 4 : start + 8]
    assert tile[64:68] == image[start + TILE * 4 * 2 : start + TILE * 4 * 2 + 4]
    assert difference(tile, tile) == 0


def test_difference_counts_every_rgb_channel() -> None:
    assert difference(bytes([10, 20, 30, 255]), bytes([12, 21, 30, 255])) == 3
    # Atlas pixels the pack leaves transparent are not the emulator's fault.
    assert difference(bytes([255, 255, 255, 0]), bytes([0, 0, 0, 255])) == 0
    assert difference(solid(PLAINS), solid(WATER)) == (220 - 30 + 180 - 60 + 200 - 80) * TILE * TILE


def test_expected_tile_paints_the_overhang_of_the_frame_below(tmp_path: Path) -> None:
    """A 16x32 mountain frame is anchored on its own cell and draws over the cell above."""
    pack = make_pack(tmp_path)
    cells = [
        GroundCell(0, 0, 0, 1, 0),  # plains
        GroundCell(1, 0, 0, 1, 0),
        GroundCell(0, 1, 71, 2, 0),  # mountain, its frame reaches up into row 0
        GroundCell(1, 1, 12, 5, 0),  # water, whose frame draws nothing above it
    ]
    cache: dict[int, bytes | None] = {}
    assert expected_tile(pack, cells, 2, 0, cache) == solid(PEAK)
    assert expected_tile(pack, cells, 2, 1, cache) == solid(PLAINS)
    assert expected_tile(pack, cells, 2, 2, cache) == solid(MOUNTAIN)
    assert expected_tile(pack, cells, 2, 3, cache) == solid(WATER)


def test_find_camera_offset_locates_the_rendered_window(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    map = MAPS_BY_ID["bean_island"]
    mountains = {(3, 5), (10, 8), (14, 12)}
    cells = [
        GroundCell(x, y, 71, 2, 0) if (x, y) in mountains else GroundCell(x, y, 0, 1, 0)
        for y in range(map.height)
        for x in range(map.width)
    ]
    offset_x, offset_y = 1, 3
    image = bytearray(VIEW_WIDTH * TILE * VIEW_HEIGHT * TILE * 4)
    for row in range(VIEW_HEIGHT):
        for column in range(VIEW_WIDTH):
            tile = pack.tile(
                pack.region_for(cells[(offset_y + row) * map.width + offset_x + column])
            )
            for tile_row in range(TILE):
                start = (((row * TILE + tile_row) * VIEW_WIDTH + column) * TILE) * 4
                image[start : start + TILE * 4] = tile[
                    tile_row * TILE * 4 : (tile_row + 1) * TILE * 4
                ]

    assert find_camera_offset(
        pack, cells, map, bytes(image), VIEW_WIDTH * TILE, VIEW_HEIGHT * TILE, {}
    ) == (offset_x, offset_y)


def test_terrain_overhang_only_counts_artwork_that_reaches_up(tmp_path: Path) -> None:
    """Every packed frame is 16x32, so only an opaque top half spills into the cell above."""
    pack = make_pack(tmp_path)
    cells = [
        GroundCell(0, 0, 0, 1, 0),  # plains under a mountain
        GroundCell(0, 1, 71, 2, 0),  # the mountain itself
        GroundCell(0, 2, 12, 5, 0),  # water below the plains
    ]
    assert terrain_overhang(pack, cells, 0, 1) == solid(PEAK)
    assert terrain_overhang(pack, cells, 1, 1) == TRANSPARENT_TILE
    assert terrain_overhang(pack, cells, 2, 1) == TRANSPARENT_TILE


def simulated_windows(map: VersusMap, moves: list[str]) -> set[tuple[int, int]]:
    """Track the cursor and the camera viewport for a sequence of D-pad presses."""
    deltas = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
    # The camera starts parked at the bottom-right corner of the map.
    cursor_x, cursor_y = map.width - 1, map.height - 1

    window = (map.width - VIEW_WIDTH, map.height - VIEW_HEIGHT)
    windows = {window}
    for move in moves:
        dx, dy = deltas[move]
        cursor_x = max(0, min(map.width - 1, cursor_x + dx))
        cursor_y = max(0, min(map.height - 1, cursor_y + dy))
        window = camera_window(window, (cursor_x, cursor_y))
        windows.add(window)
    return windows


def test_measure_view_records_cells_the_pack_has_no_region_for(tmp_path: Path) -> None:
    """A visible cell with no packed artwork is a gap, not a cell never seen."""
    pack = make_pack(tmp_path)
    cells = plains_cells(VIEW_WIDTH, VIEW_HEIGHT, {(5, 3): GroundCell(5, 3, 200, 20, 0)})
    _, _, image = battle_window(pack, cells, VIEW_WIDTH, {(5, 3): solid(PEAK)})
    results: dict[tuple[int, int], CellMeasurement] = {}
    measure_view(
        pack,
        cells,
        VIEW_WIDTH,
        image,
        VIEW_WIDTH * TILE,
        0,
        0,
        results,
        set(),
        {},
        (5, 3),
    )
    assert len(results) == VIEW_WIDTH * VIEW_HEIGHT
    assert results[(5, 3)].occluded
    width, _, clear = battle_window(pack, cells, VIEW_WIDTH, {(5, 3): solid(SAND)})
    measure_view(pack, cells, VIEW_WIDTH, clear, width, 0, 0, results, set(), {}, (8, 3))
    measurement = results[(5, 3)]
    assert measurement.views == 2
    assert measurement.rendered == solid(SAND)
    assert not measurement.occluded
    assert not measurement.has_own_artwork
    assert not measurement.matched
    add_nearest_artwork(pack, cells, VIEW_WIDTH, results)
    report = AuditReport("probe", "Probe", VIEW_WIDTH, VIEW_HEIGHT, str(pack.directory))
    report.cells = results
    assert report.never_in_view == []
    assert report.verdict(measurement) == "the pack selects no artwork region for this cell"
    assert report.summary()["cells_never_in_view"] == 0
    assert report.summary()["cells_missing_artwork"] == 1


def test_merge_animation_combines_the_views_it_probed() -> None:
    probes = [
        {
            "view": (0, 12),
            "cells_checked": 150,
            "cells_changed": 2,
            "changed_cells": [(7, 15), (8, 15)],
            "cells_excluded": {"unit_on_cell": 3},
            "largest_difference": 3820,
            "changed_regions": {"1:1": 3820, "2:24": 1037},
        },
        {
            "view": (7, 12),
            "cells_checked": 150,
            "cells_changed": 2,
            "changed_cells": [(10, 15), (8, 15)],
            "cells_excluded": {"unit_on_cell": 2, "thin_ground_artwork": 1},
            "largest_difference": 3130,
            "changed_regions": {"1:1": 3100, "5:97": 3130},
        },
    ]
    merged = merge_animation(probes, 60)
    assert merged["changed_regions"] == {"1:1": 3820, "2:24": 1037, "5:97": 3130}
    assert merged["changed_cells"] == [(7, 15), (8, 15), (10, 15)]
    assert merged["cells_changed"] == 3
    assert merged["cells_excluded"] == {"unit_on_cell": 5, "thin_ground_artwork": 1}
    assert merged["views_checked"] == [[0, 12], [7, 12]]
    assert merged["largest_difference"] == 3820
    assert merged["frames_between_screenshots"] == 60
    assert len(merged["probes"]) == 2


def test_sweep_moves_drag_the_camera_over_every_cell_of_every_map() -> None:
    for map_id, map in MAPS_BY_ID.items():
        windows = simulated_windows(map, sweep_moves(map))
        covered = {
            (offset_x + column, offset_y + row)
            for offset_x, offset_y in windows
            for row in range(VIEW_HEIGHT)
            for column in range(VIEW_WIDTH)
            if offset_x + column < map.width and offset_y + row < map.height
        }
        assert covered == {(x, y) for y in range(map.height) for x in range(map.width)}, map_id


def test_add_nearest_artwork_names_the_atlas_region_the_emulator_drew(tmp_path: Path) -> None:
    """A cell whose pixels match some other packed frame is a wrong-region bug, not a gap."""
    pack = make_pack(tmp_path)
    cells = [GroundCell(0, 0, 0, 1, 0), GroundCell(1, 0, 12, 5, 0)]
    results = {
        (0, 0): CellMeasurement(0, 0, 1, 0, 4800, 1, has_own_artwork=True, rendered=solid(WATER)),
        (
            1,
            0,
        ): CellMeasurement(
            1, 0, 5, 12, 122880, 1, has_own_artwork=True, rendered=bytes(TILE * TILE * 4)
        ),
    }
    add_nearest_artwork(pack, cells, 2, results)

    measurement = results[(0, 0)]
    assert measurement.nearest_other_region == "5:12"
    assert measurement.nearest_other_difference == 0

    report = AuditReport("bean_island", "Bean Island", 2, 1, str(pack.directory))
    report.cells = results
    summary = report.summary()
    assert summary["cells_wrong_region"] == 1
    assert summary["cells_no_nearby_artwork"] == 1
    assert summary["mismatches"][0]["verdict"] == (
        "the packed 5:12 region does not match what mGBA drew"
    )
    assert summary["mismatches"][1]["verdict"] == "atlas region wrong"

    # A cell with no packed region at all is a genuine coverage gap.
    report.cells[(1, 0)] = CellMeasurement(1, 0, 20, 1, 9000, 1, has_own_artwork=False)
    assert report.summary()["mismatches"][0]["verdict"] == (
        "the pack selects no artwork region for this cell"
    )


def test_comparison_tiles_put_the_atlas_next_to_the_emulator(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    cells = [GroundCell(0, 0, 0, 1, 0)]
    report = AuditReport("bean_island", "Bean Island", 1, 1, str(pack.directory))
    report.cells[(0, 0)] = CellMeasurement(0, 0, 1, 0, 4800, 1, rendered=solid(WATER))
    paths = write_comparison_tiles(pack, cells, 1, report, tmp_path / "tiles")
    assert len(paths) == 1
    data = Path(paths[0]).read_bytes()
    assert data.startswith(b"\x89PNG")
    assert struct.unpack(">II", data[16:24]) == (TILE * 2 + 1, TILE)
    assert "mismatch-0-0-1-0" in paths[0]


def test_report_summary_groups_cells_by_terrain_class() -> None:
    report = AuditReport("pipe_maze", "Pipe Maze", 24, 22, "/tmp/pack")
    report.cells[(9, 0)] = CellMeasurement(9, 0, 13, 70, 64, 2)
    report.cells[(3, 1)] = CellMeasurement(3, 1, 2, 71, 0, 1, unit_on_cell=True)
    report.cells[(5, 5)] = CellMeasurement(5, 5, 13, 85, 1400, 1)
    report.animated_regions = {"13:85"}
    report.never_in_view = [(0, 21)]
    summary = report.summary()
    assert summary["cells_measured"] == 3
    assert summary["cells_matched"] == 1
    assert summary["cells_mismatched"] == 2
    assert summary["largest_matched_difference"] == 64
    assert summary["cells_never_in_view"] == 1
    assert summary["by_terrain_class"] == {
        "2": {"cells": 1, "matched": 0, "mismatched": 1},
        "13": {"cells": 2, "matched": 1, "mismatched": 1},
    }
    assert summary["cells_wrong_region"] == 0
    assert summary["cells_no_nearby_artwork"] == 0
    assert summary["cells_animated"] == 1
    assert summary["cells_covered_by_units"] == 1
    assert summary["mismatches"][0] == {
        "x": 5,
        "y": 5,
        "terrain_class": 13,
        "graphical_tile_id": 85,
        "difference": 1400,
        "unit_on_cell": False,
        "occluded": False,
        "covered_by_terrain_overhang": False,
        "has_own_artwork": False,
        "owner_slot": 0,
        "nearest_other_region": None,
        "nearest_other_collection": None,
        "nearest_other_difference": None,
        "verdict": "animated terrain; the atlas stores only frame 0",
        "views": 1,
    }
    assert summary["verdicts"] == {
        "animated terrain; the atlas stores only frame 0": 1,
        "a unit sprite or the status panel covers this cell": 1,
    }
    report.cells[(5, 5)].nearest_other_difference = 0
    assert report.summary()["cells_wrong_region"] == 0


def test_a_packed_but_wrong_property_region_is_not_called_missing(tmp_path: Path) -> None:
    """HQ and city art is army keyed, so a bad match there names the region we tried."""
    pack = make_pack(tmp_path)
    report = AuditReport("pipe_maze", "Pipe Maze", 2, 1, str(pack.directory))
    report.cells[(0, 0)] = CellMeasurement(
        0,
        0,
        8,
        463,
        12733,
        1,
        owner_slot=3,
        has_own_artwork=True,
        rendered=solid(PEAK),
    )
    summary = report.summary()
    assert summary["mismatches"][0]["verdict"] == (
        "army 3 property art does not match the packed 8:3 region"
    )

    # A transparent atlas region matches nothing, so it cannot count as a verified cell.
    report.cells[(1, 0)] = CellMeasurement(
        1, 0, 9, 41, 0, 1, covered=0, has_own_artwork=True, rendered=solid(WATER)
    )
    summary = report.summary()
    assert summary["cells_matched"] == 0
    assert summary["mismatches"][1]["verdict"] == "the atlas region for this cell is transparent"


def test_a_later_screenshot_of_the_same_view_can_clear_an_occluded_cell(tmp_path: Path) -> None:
    """The cursor or a unit can cover a tile in one view and move away in the next."""
    pack = make_pack(tmp_path)
    cells = plains_cells(VIEW_WIDTH, VIEW_HEIGHT, {(5, 3): GroundCell(5, 3, 12, 5, 0)})
    results: dict[tuple[int, int], CellMeasurement] = {}
    width, _, covered = battle_window(pack, cells, VIEW_WIDTH)
    _, _, clear = battle_window(pack, cells, VIEW_WIDTH, {(5, 3): solid(SAND)})
    measure_view(pack, cells, VIEW_WIDTH, covered, width, 0, 0, results, set(), {}, (5, 3))
    add_nearest_artwork(pack, cells, VIEW_WIDTH, results)
    sample = results[(5, 3)]
    assert not sample.matched
    assert sample.nearest_other_region is None
    report = AuditReport("probe", "Probe", VIEW_WIDTH, VIEW_HEIGHT, str(pack.directory))
    assert report.verdict(sample) == "the HUD or cursor covers this cell in every sampled view"
    measure_view(pack, cells, VIEW_WIDTH, clear, VIEW_WIDTH * TILE, 0, 0, results, set(), {})
    assert results[(5, 3)].difference == difference(solid(SAND), solid(WATER))
    assert results[(5, 3)].views == 2
    assert not results[(5, 3)].occluded


def test_animation_probe_only_trusts_unobstructed_ground(tmp_path: Path) -> None:
    """A blinking cursor or a moving unit must not make static terrain look animated."""
    pack = make_pack(tmp_path)
    cells = plains_cells(
        VIEW_WIDTH,
        VIEW_HEIGHT,
        {
            (2, 2): GroundCell(2, 2, 12, 5, 0),  # water that really does cycle
            (6, 6): GroundCell(6, 6, 0, 1, 0),  # plains with a unit standing on it
            (7, 7): GroundCell(7, 7, 1, 1, 0),  # plains whose packed frame is nearly empty
        },
    )
    map = VersusMap(
        "audit_probe", "Audit Probe", 500, VIEW_WIDTH, VIEW_HEIGHT, MapCategory.CLASSIC, 0
    )
    first = battle_window(pack, cells, VIEW_WIDTH)
    second = battle_window(
        pack,
        cells,
        VIEW_WIDTH,
        {(2, 2): solid(DRIFT), (6, 6): solid(SAND), (7, 7): solid(SAND)},
    )
    bridge = FakeBridge([first, second])
    probe = asyncio.run(
        check_animation(bridge, pack, cells, map, 30, tmp_path / "shots", 0, {(6, 6)}, {})
    )
    assert probe["view"] == [0, 0]
    assert probe["changed_cells"] == [(2, 2)]
    assert probe["changed_regions"] == {"5:12": difference(solid(DRIFT), solid(WATER))}
    assert probe["cells_excluded"] == {
        "unit_on_cell": 1,
        "thin_ground_artwork": 1,
    }
    report = AuditReport("audit_probe", "Audit Probe", VIEW_WIDTH, VIEW_HEIGHT, str(pack.directory))
    report.animated_regions = set(probe["changed_regions"])
    static = CellMeasurement(9, 9, 1, 0, 5000, 1)
    assert report.verdict(static) != "animated terrain; the atlas stores only frame 0"


def test_animation_probe_ignores_the_cell_the_map_cursor_is_on(tmp_path: Path) -> None:
    """The cursor marker blinks and the panel beside it changes; neither is terrain."""
    pack = make_pack(tmp_path)
    cells = plains_cells(
        VIEW_WIDTH,
        VIEW_HEIGHT,
        {(2, 2): GroundCell(2, 2, 12, 5, 0), (5, 5): GroundCell(5, 5, 12, 5, 0)},
    )
    map = VersusMap(
        "audit_probe", "Audit Probe", 500, VIEW_WIDTH, VIEW_HEIGHT, MapCategory.CLASSIC, 0
    )
    first = battle_window(pack, cells, VIEW_WIDTH)
    second = battle_window(
        pack, cells, VIEW_WIDTH, {(2, 2): solid(DRIFT), (3, 2): solid(SAND), (5, 5): solid(DRIFT)}
    )
    bridge = FakeBridge([first, second])
    probe = asyncio.run(
        check_animation(bridge, pack, cells, map, 30, tmp_path / "shots", 0, set(), {}, (2, 2))
    )
    assert probe["changed_cells"] == [(5, 5)]
    assert probe["cells_excluded"] == {"map_cursor": 2}
    assert probe["changed_regions"] == {"5:12": difference(solid(DRIFT), solid(WATER))}


def test_animation_probe_masks_unpacked_property_effects_and_hud(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    cells = plains_cells(VIEW_WIDTH, VIEW_HEIGHT, {(8, 7): GroundCell(8, 7, 463, 8, 1)})
    map = VersusMap(
        "audit_probe", "Audit Probe", 500, VIEW_WIDTH, VIEW_HEIGHT, MapCategory.CLASSIC, 0
    )

    def with_hud(overrides: dict[tuple[int, int], bytes]) -> tuple[int, int, bytes]:
        width, height, pixels = battle_window(pack, cells, VIEW_WIDTH, overrides)
        pixels = bytearray(pixels)
        border = (3 * width + 5) * 4
        highlight = border + width * 4
        pixels[border : border + 32] = b"\x00\x00\x00\xff" * 8
        pixels[highlight : highlight + 32] = b"\xff" * 32
        return width, height, bytes(pixels)

    bridge = FakeBridge([with_hud({}), with_hud({(8, 6): solid(PEAK), (14, 8): solid(SAND)})])
    probe = asyncio.run(
        check_animation(bridge, pack, cells, map, 8, tmp_path / "shots", 0, set(), {})
    )
    assert probe["changed_regions"] == {}
    assert probe["cells_excluded"] == {"property_overlay": 1, "hud": 1}


def test_animation_probe_uses_a_viewport_origin_for_a_tied_window(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    map = MAPS_BY_ID["pipe_maze"]
    cells = plains_cells(map.width, map.height, {})
    bridge = FakeBridge([battle_window(pack, cells, map.width)])
    probe = asyncio.run(
        check_animation(
            bridge,
            pack,
            cells,
            map,
            8,
            tmp_path / "shots",
            0,
            set(),
            {},
            (18, 14),
            camera_hint=(4, 5),
        )
    )
    assert probe["view"] == [4, 5]


def make_pack_with_invisible_region(directory: Path) -> SpritePack:
    """Same pack as make_pack, plus a manifest key pointing at unpainted atlas space."""
    pack = make_pack(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    atlas = b"".join(
        pack.pixels[row : row + pack.width * 4] + bytes(TILE * 4)
        for row in range(0, len(pack.pixels), pack.width * 4)
    )
    (directory / "atlas.png").write_bytes(png(pack.width + TILE, pack.height, atlas))
    manifest["width"] = pack.width + TILE
    manifest["terrain_variants"]["9:9"] = {
        "x": pack.width,
        "y": 0,
        "width": TILE,
        "height": TILE * 2,
    }
    manifest["terrain"]["8:3"] = {"x": 16, "y": TILE, "width": TILE, "height": TILE * 2}
    (directory / "manifest.json").write_text(json.dumps(manifest))
    return SpritePack(directory)


def test_overhang_does_not_hide_transparent_ground(tmp_path: Path) -> None:
    pack = make_pack_with_invisible_region(tmp_path)
    cells = plains_cells(
        VIEW_WIDTH,
        VIEW_HEIGHT,
        {(5, 3): GroundCell(5, 3, 9, 9, 0), (5, 4): GroundCell(5, 4, 71, 2, 0)},
    )
    width, _, image = battle_window(pack, cells, VIEW_WIDTH)
    results: dict[tuple[int, int], CellMeasurement] = {}
    measure_view(pack, cells, VIEW_WIDTH, image, width, 0, 0, results, set(), {})
    measurement = results[(5, 3)]
    assert measurement.covered_by_terrain_overhang
    assert measurement.difference == 0
    assert measurement.covered == 0
    assert not measurement.matched


def test_nearest_artwork_ignores_regions_that_paint_no_pixels(tmp_path: Path) -> None:
    """A fully transparent atlas region scores zero against any pixels drawn."""
    pack = make_pack_with_invisible_region(tmp_path)
    cells = [GroundCell(0, 0, 1, 1, 0)]
    results = {
        (0, 0): CellMeasurement(
            0,
            0,
            1,
            1,
            4000,
            1,
            covered=TILE * TILE * 8,
            has_own_artwork=True,
            rendered=solid((200, 30, 40, 255)),
        )
    }
    add_nearest_artwork(pack, cells, 1, results)
    measurement = results[(0, 0)]
    assert measurement.nearest_other_region != "9:9"
    assert measurement.nearest_other_difference is not None
    assert measurement.nearest_other_difference > MATCH_TOLERANCE


def test_nearest_artwork_excludes_the_region_the_cell_actually_selected(tmp_path: Path) -> None:
    """A property cell is drawn from its class:owner fallback, not from its tile id.

    Reporting that fallback as an "other" region that matches perfectly would tell the
    reviewer the client picked the wrong artwork when it picked exactly the right one.
    """
    pack = make_pack_with_invisible_region(tmp_path)
    cells = [GroundCell(0, 0, 463, 8, 3)]
    results = {
        (0, 0): CellMeasurement(
            0,
            0,
            8,
            463,
            4000,
            1,
            covered=TILE * TILE,
            has_own_artwork=True,
            owner_slot=3,
            rendered=solid((200, 30, 40, 255)),
        )
    }
    add_nearest_artwork(pack, cells, 1, results)
    measurement = results[(0, 0)]
    assert measurement.nearest_other_region != "8:3"
    assert measurement.nearest_other_difference is not None
    assert measurement.nearest_other_difference > MATCH_TOLERANCE
    report = AuditReport("probe", "Probe", 1, 1, str(pack.directory))
    report.cells = results
    assert "army 3 property art" in report.verdict(measurement)


def test_nearest_artwork_can_share_the_selected_variants_key(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    pack.manifest["terrain"]["1:0"] = pack.manifest["terrain_variants"]["5:12"]
    cells = [GroundCell(0, 0, 0, 1, 0)]
    sample = CellMeasurement(0, 0, 1, 0, 5000, 1, rendered=solid(WATER))
    add_nearest_artwork(pack, cells, 1, {(0, 0): sample})
    assert sample.nearest_other_region == "1:0"
    assert sample.nearest_other_collection == "terrain"
    assert sample.nearest_other_difference == 0


def test_comparison_tiles_show_a_transparent_half_for_missing_artwork(tmp_path: Path) -> None:
    """The gap a reviewer needs to see is a cell the pack has no region for at all."""
    pack = make_pack(tmp_path)
    cells = [GroundCell(0, 0, 77, 12, 0)]  # a terrain class the manifest never lists
    report = AuditReport("probe", "Probe", 1, 1, str(pack.directory))
    report.cells[(0, 0)] = CellMeasurement(
        0,
        0,
        12,
        77,
        0,
        1,
        covered=0,
        has_own_artwork=False,
        rendered=solid(PLAINS),
    )
    paths = write_comparison_tiles(pack, cells, 1, report, tmp_path / "tiles")
    assert len(paths) == 1
    width, height, pixels = decode_png(Path(paths[0]).read_bytes())
    assert (width, height) == (TILE * 2 + 1, TILE)
    atlas_side = pixels[: TILE * 4]  # first row of the atlas half
    assert all(alpha == 0 for alpha in atlas_side[3::4])
    emulator_side = pixels[(TILE + 1) * 4 : (TILE + 2) * 4]
    assert emulator_side[0] == PLAINS[0] and emulator_side[3] == 255


def test_nearest_artwork_is_not_truncated_by_a_transparent_region(tmp_path: Path) -> None:
    """A transparent selected region cannot make every candidate look like a near miss."""
    pack = make_pack(tmp_path)
    cells = [GroundCell(0, 0, 3, 9, 0)]
    results = {
        (0, 0): CellMeasurement(
            0,
            0,
            9,
            3,
            0,
            1,
            covered=0,
            has_own_artwork=True,
            rendered=solid(PEAK),
        )
    }
    add_nearest_artwork(pack, cells, 1, results)
    measurement = results[(0, 0)]
    assert measurement.nearest_other_difference > MATCH_TOLERANCE
    report = AuditReport("probe", "Probe", 1, 1, str(pack.directory))
    report.cells = results
    assert report.verdict(measurement) == "the atlas region for this cell is transparent"


ROM = Path(os.environ.get("AW2_ROM_PATH", ""))
PACK = Path(os.environ.get("AW2_CLIENT_SPRITES", ""))
needs_rom = pytest.mark.skipif(not ROM.is_file(), reason="AW2_ROM_PATH is not set")
needs_pack = pytest.mark.skipif(
    not (PACK / "manifest.json").is_file(), reason="AW2_CLIENT_SPRITES pack is not packed"
)


@needs_rom
@needs_pack
def test_every_playable_map_cell_has_artwork_in_the_packed_atlas() -> None:
    """The pack the client ships with must cover every cell of the maps we can play."""
    pack = SpritePack(PACK)
    rom = ROM.read_bytes()
    for map_id in ("pipe_maze", "big_daddy", "alara_range"):
        for cell in rom_map_cells(rom, MAPS_BY_ID[map_id]):
            region = pack.region_for(cell)
            assert region is not None, f"{map_id} cell ({cell.x},{cell.y}) has no packed artwork"
            assert pack.tile(region), f"{map_id} cell ({cell.x},{cell.y}) has an empty tile"


@needs_rom
def test_rom_map_cells_reports_the_live_tile_ids() -> None:
    rom = ROM.read_bytes()
    pipe = {(cell.x, cell.y): cell for cell in rom_map_cells(rom, MAPS_BY_ID["pipe_maze"])}
    daddy = {(cell.x, cell.y): cell for cell in rom_map_cells(rom, MAPS_BY_ID["big_daddy"])}
    assert len(pipe) == 22 * 22
    assert len(daddy) == 19 * 15
    assert pipe[(9, 0)] == GroundCell(9, 0, 323, 15, 0)  # a pipe cell
    assert pipe[(10, 0)] == GroundCell(10, 0, 24, 2, 0)  # a mountain, drawn 16x32
    assert pipe[(3, 2)] == GroundCell(3, 2, 355, 16, 0)  # a pipe seam
    assert daddy[(9, 5)] == GroundCell(9, 5, 322, 15, 0)


@needs_rom
@needs_pack
def test_the_sweep_cap_limits_the_sweep_not_the_animation_probes(tmp_path: Path) -> None:
    """--max-screenshots bounds the camera sweep; the animation probes are measured too."""
    pack = SpritePack(PACK)
    rom = ROM.read_bytes()
    entry = MAPS_BY_ID["bean_island"]
    cells = rom_map_cells(rom, entry)
    bridge = FakeBridge([battle_window(pack, cells, entry.width)], map_id=entry.rom_id)
    report = asyncio.run(
        audit_map(
            bridge,
            pack,
            "bean_island",
            ROM,
            tmp_path / "shots",
            3,
            20,
            None,
            live_state(cells, entry, cursor=(14, 9)),
        )
    )
    assert report.screenshots == 7  # three sweep views plus two animation probes of two shots
    assert bridge.operations.count("screenshot") == 7
    assert bridge.operations.count("press_keys") == 2
    assert len(report.cells) == VIEW_WIDTH * VIEW_HEIGHT
    assert report.animation is not None
    assert len(report.animation["views_checked"]) == 2
    assert report.animated_regions == set(report.animation["changed_regions"])


def test_the_audit_boots_its_own_emulator_by_default(tmp_path: Path, monkeypatch) -> None:
    """The audit never touches a match's emulator unless it is told to attach."""
    launches: list[dict[str, object]] = []
    audited_bridges: list[object] = []

    class FakeLauncher:
        def __init__(self, settings, *, isolate_saves: bool) -> None:
            launches.append({"settings": settings, "isolate_saves": isolate_saves})
            self.bridge = None

        async def start(self) -> None:
            self.bridge = FakeBridge([])
            launches[-1]["bridge"] = self.bridge

        async def stop(self) -> None:
            launches.append({"stopped": True})

    async def fake_boot(bridge, **kwargs):
        audited_bridges.append(bridge)
        return SimpleNamespace(map_id=MAPS_BY_ID["bean_island"].rom_id)

    async def fake_audit(bridge, pack, map_id, rom_path, screenshots, cap, frames, tiles):
        audited_bridges.append(bridge)
        return AuditReport(map_id, MAPS_BY_ID[map_id].name, 16, 15, str(pack.directory))

    rom = tmp_path / "fake-cartridge.gba"
    rom.write_bytes(b"\x00" * 64)
    pack = make_pack(tmp_path / "pack")
    monkeypatch.setattr("aw2_lab.sprite_audit.bridge_port_is_free", lambda port: True)
    monkeypatch.setattr("aw2_lab.sprite_audit.EmulatorLauncher", FakeLauncher)
    monkeypatch.setattr("aw2_lab.sprite_audit.boot_fixed_versus_match", fake_boot)
    monkeypatch.setattr("aw2_lab.sprite_audit.audit_map", fake_audit)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "aw2-lab",
            "sprite-audit",
            "--map",
            "bean_island",
            "--rom",
            str(rom),
            "--pack",
            str(pack.directory),
            "--emulator-mode",
            "headless",
            "--screenshots-dir",
            str(tmp_path),
        ],
    )
    main()
    settings = launches[0]["settings"]
    assert settings.bridge_port == DEFAULT_AUDIT_BRIDGE_PORT
    assert settings.mode.name == "HEADLESS"
    assert settings.suppress_emulator_output
    assert not settings.use_adjacent_save
    assert launches[0]["isolate_saves"] is True
    assert launches[-1] == {"stopped": True}
    # Every screenshot and D-pad press went to the emulator the audit launched itself.
    assert audited_bridges[0] is launches[0]["bridge"]
    assert audited_bridges[0] is audited_bridges[1]


def test_attaching_to_a_live_emulator_restores_its_state(tmp_path: Path, monkeypatch) -> None:
    """When the audit does attach, it snapshots the emulator and puts it back."""
    pack = make_pack(tmp_path / "pack")
    entry = MAPS_BY_ID["bean_island"]
    cells = plains_cells(entry.width, entry.height, {})
    rom = tmp_path / "fake-cartridge.gba"
    rom.write_bytes(b"\x00" * 64)
    bridge = FakeBridge([battle_window(pack, cells, entry.width)])
    audited: list[object] = []

    async def fake_audit(bridge, pack, map_id, rom_path, screenshots, cap, frames, tiles):
        audited.append((map_id, cap, frames))
        return AuditReport(map_id, MAPS_BY_ID[map_id].name, entry.width, entry.height, pack)

    monkeypatch.setattr("aw2_lab.sprite_audit.LuaBridgeClient", lambda **kwargs: bridge)
    monkeypatch.setattr("aw2_lab.sprite_audit.audit_map", fake_audit)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "aw2-lab",
            "sprite-audit",
            "--map",
            "bean_island",
            "--rom",
            str(rom),
            "--pack",
            str(pack.directory),
            "--attach-live",
            "43129",
            "--max-screenshots",
            "2",
            "--screenshots-dir",
            str(tmp_path),
        ],
    )
    main()
    assert bridge.operations[0] == "save_state_buffer"
    assert bridge.operations[-1] == "load_state_buffer"
    assert bridge.restored_state is not None
    assert audited == [("bean_island", 2, 0)]


@pytest.mark.parametrize("during_restore", [False, True])
def test_sigterm_waits_for_attached_frame_restoration(tmp_path: Path, monkeypatch, during_restore):
    pack = make_pack(tmp_path / "pack")
    rom = tmp_path / "fake.gba"
    rom.touch()

    class TerminatingBridge(FakeBridge):
        async def load_state_buffer(self, state: bytes) -> int:
            if during_restore:
                signal.raise_signal(signal.SIGTERM)
            await asyncio.sleep(0.01)
            self.frames = 0
            return await super().load_state_buffer(state)

    bridge = TerminatingBridge([])

    async def audit(*args):
        bridge.frames = 100
        if not during_restore:
            signal.raise_signal(signal.SIGTERM)
            await asyncio.sleep(10)
        return AuditReport("bean_island", "Bean Island", 16, 15, str(pack.directory))

    monkeypatch.setattr("aw2_lab.sprite_audit.LuaBridgeClient", lambda **kwargs: bridge)
    monkeypatch.setattr("aw2_lab.sprite_audit.audit_map", audit)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "aw2-lab",
            "sprite-audit",
            "--map",
            "bean_island",
            "--rom",
            str(rom),
            "--pack",
            str(pack.directory),
            "--attach-live",
            "43129",
            "--screenshots-dir",
            str(tmp_path),
        ],
    )
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 128 + signal.SIGTERM
    assert bridge.frames == 0
    assert bridge.operations == ["save_state_buffer", "load_state_buffer"]


@pytest.mark.parametrize("instance", [None, "original", "replacement"])
def test_run_directory_requires_the_recorded_bridge_before_snapshot(
    tmp_path: Path, monkeypatch, instance: str | None
) -> None:
    pack = make_pack(tmp_path / "pack")
    rom = tmp_path / "fake-cartridge.gba"
    rom.touch()
    (tmp_path / "match.json").write_text(
        json.dumps({"bridge_port": 43129, "bridge_instance": instance})
    )
    operations = []

    async def request(self, operation, **params):
        operations.append(operation)
        if operation == "connect":
            assert self.port == 43129
            return {"instance": "original"}
        if operation == "save_state_buffer":
            return {"frame": 100, "state_base64": "c2F2ZWQ="}
        return {"frame": 100}

    async def audit(*args):
        operations.append("audit")
        return AuditReport("bean_island", "Bean Island", 16, 15, str(pack.directory))

    monkeypatch.setattr(LuaBridgeClient, "request", request)
    monkeypatch.setattr("aw2_lab.sprite_audit.audit_map", audit)
    argv = [
        "sprite-audit",
        "--map",
        "bean_island",
        "--rom",
        str(rom),
        "--pack",
        str(pack.directory),
        "--run-dir",
        str(tmp_path),
    ]
    monkeypatch.setattr(sys, "argv", ["aw2-lab", *argv])
    if instance == "original":
        main()
        assert operations == ["connect", "save_state_buffer", "audit", "load_state_buffer"]
    else:
        with pytest.raises(SystemExit) as exit_info:
            main()
        assert exit_info.value.code == 1
        assert operations == (["connect"] if instance else [])


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--max-screenshots", "-1"),
        ("--max-screenshots", "0"),
        ("--animation-frames", "-1"),
        ("--animation-frames", "601"),
    ],
)
def test_invalid_capture_limits_are_rejected_before_reading_the_rom(
    option: str, value: str, capsys, monkeypatch
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["aw2-lab", "sprite-audit", "--map", "bean_island", "--rom", "/missing.gba", option, value],
    )
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 2
    assert f"{option} must be" in capsys.readouterr().err


@pytest.mark.parametrize("missing_frame_on", [None, "save_state_buffer", "load_state_buffer"])
def test_an_unverifiable_restore_ends_the_audit_with_an_error(
    tmp_path: Path, monkeypatch, missing_frame_on: str | None
) -> None:
    """A partial restore leaves the match's controller and emulator out of step, so the
    command must fail rather than report a successful audit."""
    pack = make_pack(tmp_path / "pack")
    rom = tmp_path / "fake-cartridge.gba"
    rom.write_bytes(b"\x00" * 64)
    bridge = FakeBridge(
        [], fail_restore=missing_frame_on is None, missing_frame_on=missing_frame_on
    )
    monkeypatch.setattr("aw2_lab.sprite_audit.LuaBridgeClient", lambda **kwargs: bridge)
    audited = []

    async def fake_audit(*args):
        audited.append(True)

    monkeypatch.setattr("aw2_lab.sprite_audit.audit_map", fake_audit)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "aw2-lab",
            "sprite-audit",
            "--map",
            "bean_island",
            "--rom",
            str(rom),
            "--pack",
            str(pack.directory),
            "--attach-live",
            "43129",
        ],
    )
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 1
    if missing_frame_on == "save_state_buffer":
        assert bridge.operations == ["save_state_buffer"]
        assert not audited
    else:
        assert bridge.operations == ["save_state_buffer", "load_state_buffer"]
        assert audited


def test_sprite_audit_cli_is_wired_into_the_main_command(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["aw2-lab", "sprite-audit", "--help"])
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 0


def test_sprite_audit_needs_a_rom(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["aw2-lab", "sprite-audit", "--map", "pipe_maze", "--rom", str(tmp_path / "missing.gba")],
    )
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 2


def test_a_fresh_save_can_only_audit_maps_its_roster_unlocks(tmp_path: Path) -> None:
    """Selecting a locked CO from a blank cartridge silently picks another commander."""
    assert audit_co_ids(MAPS_BY_ID["bean_island"], None) == ("andy", "max")
    assert audit_co_ids(MAPS_BY_ID["bean_island"], tmp_path / "unlocked.sps") == ("andy", "max")
    unlocked = audit_co_ids(MAPS_BY_ID["pipe_maze"], tmp_path / "unlocked.sps")
    assert unlocked == ("andy", "max", "sami", "flak")
    with pytest.raises(AuditError, match="seats 4 commanders.*only unlocks andy, max"):
        audit_co_ids(MAPS_BY_ID["pipe_maze"], None)


def test_the_audit_refuses_a_bridge_port_another_emulator_already_has(
    tmp_path: Path, monkeypatch
) -> None:
    """Starting a second mGBA on a port that is already served measures the wrong emulator."""
    port = DEFAULT_AUDIT_BRIDGE_PORT
    monkeypatch.setattr("aw2_lab.sprite_audit.bridge_port_is_free", lambda checked: checked != port)
    settings = EmulatorSettings(
        rom_path=tmp_path / "fake-cartridge.gba",
        mode=EmulatorMode.HEADLESS,
        bridge_port=port,
    )
    with pytest.raises(AuditError, match=f"bridge port {port} is already serving"):
        asyncio.run(isolated_bridge(settings).__aenter__())


def test_camera_window_follows_the_map_cursor() -> None:
    assert camera_window((0, 0), (14, 9)) == (0, 0)
    assert camera_window((0, 0), (15, 10)) == (1, 1)
    assert camera_window((7, 12), (0, 0)) == (0, 0)
    assert camera_window((7, 12), (20, 20)) == (7, 12)
    assert move_cursor((0, 0), "up", 22, 22) == (0, 0)
    assert move_cursor((0, 0), "right", 22, 22) == (1, 0)


@needs_rom
@needs_pack
def test_the_sweep_keeps_measuring_views_after_every_cell_has_one(tmp_path: Path) -> None:
    """Brace Range is exactly one viewport, so the old early stop ended the sweep at shot 1."""
    pack = SpritePack(PACK)
    entry = MAPS_BY_ID["brace_range"]
    cells = rom_map_cells(ROM.read_bytes(), entry)
    assert (entry.width, entry.height) == (VIEW_WIDTH, VIEW_HEIGHT)
    bridge = FakeBridge([battle_window(pack, cells, entry.width)], map_id=entry.rom_id)
    report = asyncio.run(
        audit_map(
            bridge,
            pack,
            "brace_range",
            ROM,
            tmp_path / "shots",
            6,
            0,
            None,
            live_state(cells, entry, cursor=(14, 9)),
        )
    )
    assert len(report.cells) == VIEW_WIDTH * VIEW_HEIGHT
    assert report.screenshots == 6
    assert bridge.operations.count("screenshot") == 6
    assert bridge.operations.count("press_keys") == 5
    assert report.views == [(0, 0)]


def test_the_audit_refuses_an_emulator_that_is_not_in_a_battle(tmp_path: Path) -> None:
    """Without a validated battle there is no live map to measure, so the audit stops.

    Falling back to the ROM's map table would let an attached menu screen, or the wrong
    map, be reported as a completed audit.
    """
    pack = make_pack(tmp_path / "pack")
    entry = MAPS_BY_ID["bean_island"]
    cells = plains_cells(entry.width, entry.height, {})
    rom = tmp_path / "fake-cartridge.gba"
    rom.write_bytes(b"\x00" * 64)
    bridge = FakeBridge([battle_window(pack, cells, entry.width)])
    setup_screen = SimpleNamespace(
        battle=SimpleNamespace(
            status=ValueStatus.UNAVAILABLE,
            value=None,
            reasons=("the bridge is on the Versus setup screen",),
        ),
        ui=SimpleNamespace(
            map_cursor=SimpleNamespace(status=CursorStatus.UNAVAILABLE, x=None, y=None, reasons=())
        ),
    )
    with pytest.raises(AuditError, match="not in a validated battle turn"):
        asyncio.run(
            audit_map(
                bridge, pack, "bean_island", rom, tmp_path / "shots", 5, 0, None, setup_screen
            )
        )
    assert bridge.operations == []


def test_an_ambiguous_camera_view_is_reported_not_guessed(tmp_path: Path) -> None:
    """When the pack has no artwork to tell two windows apart, the audit says so."""
    pack = make_pack(tmp_path)
    entry = MAPS_BY_ID["big_daddy"]  # 19x15, so several camera windows are possible
    cells = plains_cells(entry.width, entry.height, {})
    blank = bytes((90, 90, 90, 255) * VIEW_WIDTH * TILE * VIEW_HEIGHT * TILE)
    with pytest.raises(AuditError, match="camera position in this screenshot is ambiguous"):
        find_camera_offset(pack, cells, entry, blank, VIEW_WIDTH * TILE, VIEW_HEIGHT * TILE, {})


def test_camera_rejects_a_stronger_match_outside_the_cursor_window(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    entry = MAPS_BY_ID["pipe_maze"]
    cells = plains_cells(entry.width, entry.height, {(0, 0): GroundCell(0, 0, 12, 5, 0)})
    width, height, image = battle_window(pack, cells, entry.width)
    assert find_camera_offset(pack, cells, entry, image, width, height, {}) == (0, 0)
    assert find_camera_offset(
        pack,
        cells,
        entry,
        image,
        width,
        height,
        {},
        cursor=(entry.width - 1, entry.height - 1),
    ) == (entry.width - VIEW_WIDTH, entry.height - VIEW_HEIGHT)


def test_spent_silos_are_accepted_for_the_loaded_map() -> None:
    entry = MAPS_BY_ID["missile_plains"]
    spent = {(x, y): GroundCell(x, y, 0, 18, 0) for y in range(3) for x in range(7)}
    cells = plains_cells(entry.width, entry.height, spent)
    battle = live_state(cells, entry).battle.value
    assert cells_from_state(battle, entry.rom_id, entry) == cells
    with pytest.raises(AuditError, match="showing ROM map"):
        cells_from_state(battle, entry.rom_id + 1, entry)


def test_the_live_cursor_resolves_an_ambiguous_camera_view(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    entry = MAPS_BY_ID["big_daddy"]
    cells = plains_cells(entry.width, entry.height, {})
    blank = bytes((90, 90, 90, 255) * VIEW_WIDTH * TILE * VIEW_HEIGHT * TILE)
    offset = find_camera_offset(
        pack,
        cells,
        entry,
        blank,
        VIEW_WIDTH * TILE,
        VIEW_HEIGHT * TILE,
        {},
        cursor=(entry.width - 1, entry.height - 1),
    )
    assert offset == (entry.width - VIEW_WIDTH, entry.height - VIEW_HEIGHT)


def test_camera_tie_keeps_the_viewport_when_cursor_reverses_inside_it(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    entry = MAPS_BY_ID["pipe_maze"]
    cells = plains_cells(entry.width, entry.height, {})
    width, height, image = battle_window(pack, cells, entry.width)
    previous = (7, 12)
    cursor = (20, 21)
    assert (
        find_camera_offset(
            pack,
            cells,
            entry,
            image,
            width,
            height,
            {},
            previous,
            camera_window(previous, cursor),
            cursor=cursor,
        )
        == previous
    )
    with pytest.raises(AuditError, match="camera position in this screenshot is ambiguous"):
        find_camera_offset(pack, cells, entry, image, width, height, {}, cursor=cursor)
