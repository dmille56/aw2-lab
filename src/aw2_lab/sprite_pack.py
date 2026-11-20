"""Build an external, static client atlas from the supported local AW2 ROM."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal, Self, TypedDict, TypeGuard

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aw2_lab.aw2_rules_data import UNIT_DATA
from aw2_lab.rom_profile import AW2_US_REVISION_0, select_rom_profile
from aw2_lab.sprite_extraction import (
    co_portrait_sample,
    compose_tiles,
    decode_palette,
    decode_tile,
    encode_png,
    terrain_sample,
    unit_sample,
)

TERRAIN_CLASSES = tuple(range(1, 9)) + tuple(range(10, 20))
# Sources selected by the original terrain information renderer at 0x0803F6BC. Their
# artwork is chosen by army (headquarters, cities, and other property classes), so
# their per-cell graphical IDs cannot be packed without an army-specific overlay.
PROPERTY_SOURCES = {
    6: (0x0CFFC4 + 0x440, 6),
    10: (0x0CFFC4 + 0x140, 6),
    11: (0x0CFFC4 + 0x240, 6),
    14: (0x0CFFC4 + 0x80, 4),
    17: (0x0CFFC4 + 0xA40, 6),
    18: (0x0CFFC4 + 0xB00, 4),
}

# Terrain classes whose artwork varies per map cell rather than per army. Cells of
# these classes reference distinct graphical tile IDs whose four-tile composition,
# palette index, or flips differ from the class representative. Plains cells are not
# flat: the ID they reference carries the tip of a mountain range that spills out of
# the mountain cell below, so every non-property class needs per-cell artwork.
TERRAIN_VARIANT_CLASSES = tuple(
    terrain for terrain in TERRAIN_CLASSES if terrain not in PROPERTY_SOURCES and terrain != 8
)


class Region(TypedDict):
    x: int
    y: int
    width: int
    height: int


class AnimationSection(TypedDict):
    atlas: str
    atlas_sha256: str
    width: int
    height: int
    cycle_frames: int
    samples_per_view: int
    map_id: str | None
    maps: list[str]
    captured_by: str
    frames: dict[str, dict[str, list[Region]]]


class SpriteManifest(TypedDict):
    kind: str
    version: int
    rom_sha256: str
    atlas: str
    atlas_sha256: str
    width: int
    height: int
    units: dict[str, Region]
    terrain: dict[str, Region]
    portraits: dict[str, Region]
    terrain_variants: dict[str, Region]
    animation: AnimationSection | None


ANIMATION_COLUMNS = 16
FRAME_WIDTH = 16
FRAME_HEIGHT = 32
# The client API refuses an animation section with more than these, so the pack builder
# stops before writing a manifest the server would reject.
MAX_FRAMES_PER_REGION = 16
MAX_ANIMATION_FRAMES = 2048
MAX_ANIMATION_SAMPLES = 64


def valid_animation_atlas_name(name: object, digest: object) -> TypeGuard[str]:
    return (
        isinstance(name, str)
        and isinstance(digest, str)
        and re.fullmatch(r"[0-9a-f]{64}", digest) is not None
        and name == f"animation-{digest}.png"
    )


@contextmanager
def sprite_pack_lock(directory: Path, *, shared: bool = False) -> Iterator[None]:
    """Lock the pack directory itself so readers can also open read-only packs."""
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


# Terrain variant keys are "<terrain class>:<graphical tile ID>". Only classes whose
# artwork varies per map cell can appear; property classes are keyed by army instead.
TERRAIN_VARIANT_KEY_PATTERN = (
    r"(?:"
    + "|".join(str(terrain) for terrain in TERRAIN_VARIANT_CLASSES)
    + r"):(?:0|[1-9][0-9]{0,3})"
)


class SpriteRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: int = Field(ge=0, le=4096, strict=True)
    y: int = Field(ge=0, le=4096, strict=True)
    width: int = Field(ge=1, le=48, strict=True)
    height: int = Field(ge=1, le=48, strict=True)


class AnimationFrames(BaseModel):
    """Frames the sprite audit captured from a live match for regions that cycle.

    Packs built before the audit recorded frames simply have no animation section, so
    every field is optional at the top level and older manifests keep validating.
    """

    model_config = ConfigDict(extra="forbid")
    atlas: str
    atlas_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    width: int = Field(ge=1, le=4096, strict=True)
    height: int = Field(ge=1, le=4096, strict=True)
    cycle_frames: int = Field(ge=1, le=600, strict=True)
    samples_per_view: int = Field(ge=2, le=MAX_ANIMATION_SAMPLES, strict=True)
    map_id: str | None = None
    maps: list[str] = Field(default_factory=list, max_length=32)
    captured_by: str
    frames: dict[str, dict[str, list[SpriteRegion]]]

    @model_validator(mode="after")
    def validate_frames(self) -> Self:
        if not valid_animation_atlas_name(self.atlas, self.atlas_sha256):
            raise ValueError("Invalid animation atlas filename")
        if len(self.maps) != len(set(self.maps)):
            raise ValueError("Duplicate map in the animation capture list")
        if any(
            not 1 <= len(name) <= 64 or not re.fullmatch(r"[a-z0-9_]+", name) for name in self.maps
        ):
            raise ValueError("Invalid map name in the animation capture list")
        if len(self.frames) > 2:
            raise ValueError("Animation frames may only cover terrain collections")
        total = 0
        for kind, collection in self.frames.items():
            pattern = (
                TERRAIN_VARIANT_KEY_PATTERN if kind == "terrain_variants" else r"[0-9]{1,2}:[0-5]"
            )
            if kind not in ("terrain", "terrain_variants"):
                raise ValueError("Animation frames may only cover terrain collections")
            if len(collection) > 256:
                raise ValueError("Too many animated terrain regions")
            for key, regions in collection.items():
                if not re.fullmatch(pattern, key):
                    raise ValueError("Invalid animated region key")
                if len(regions) > MAX_FRAMES_PER_REGION:
                    raise ValueError("Too many frames for one animated region")
                for region in regions:
                    if region.width != 16 or region.height != 32:
                        raise ValueError("Animation frames are 16x32")
                    if (
                        region.x + region.width > self.width
                        or region.y + region.height > self.height
                    ):
                        raise ValueError("Animation frame is outside the atlas")
                total += len(regions)
        if total > MAX_ANIMATION_FRAMES:
            raise ValueError("Too many animation frames")
        return self


class SpritePackManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["aw2-client-sprites"]
    version: Literal[1]
    rom_sha256: str
    atlas: str
    atlas_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    width: int = Field(ge=1, le=4096, strict=True)
    height: int = Field(ge=1, le=4096, strict=True)
    units: dict[str, SpriteRegion]
    terrain: dict[str, SpriteRegion]
    portraits: dict[str, SpriteRegion] = Field(default_factory=dict)
    terrain_variants: dict[str, SpriteRegion] = Field(default_factory=dict)
    animation: AnimationFrames | None = None

    @model_validator(mode="after")
    def validate_pack(self) -> Self:
        if self.rom_sha256 != AW2_US_REVISION_0.sha256:
            raise ValueError("Unsupported sprite-pack ROM identity")
        if self.atlas != f"atlas-{self.atlas_sha256}.png":
            raise ValueError("Invalid sprite atlas filename")
        if len(self.units) > 256 or len(self.terrain) > 256:
            raise ValueError("Too many sprite regions")
        if len(self.terrain_variants) > 256:
            raise ValueError("Too many terrain variants")
        if len(self.portraits) > 19:
            raise ValueError("Too many CO portrait regions")
        if any(
            region.width > 32 or region.height > 32
            for collection in (self.units, self.terrain, self.terrain_variants)
            for region in collection.values()
        ):
            raise ValueError("Map sprite regions cannot exceed 32 pixels")
        for collection, pattern in (
            (self.units, r"[0-9]{1,2}:[0-5]"),
            (self.terrain, r"[0-9]{1,2}:[0-5]"),
            (self.portraits, r"(?:[0-9]|1[0-8])"),
            (self.terrain_variants, TERRAIN_VARIANT_KEY_PATTERN),
        ):
            for key, region in collection.items():
                if not re.fullmatch(pattern, key):
                    raise ValueError("Invalid sprite region key")
                if collection is self.terrain_variants and int(key.split(":")[1]) > 1023:
                    raise ValueError("Graphical tile ID is outside the lookup")
                if region.x + region.width > self.width or region.y + region.height > self.height:
                    raise ValueError("Sprite region is outside the atlas")
        return self


def animation_atlas(
    frames: dict[str, dict[str, list[bytes]]],
) -> tuple[int, int, bytes, dict[str, dict[str, list[Region]]]]:
    """Lay every captured frame in a 16-column grid and index it by collection and key.

    ``frames`` maps a collection (``terrain`` or ``terrain_variants``) and region key to
    the full 16x32 frames that region cycles through, in the order the emulator drew them.
    """
    ordered = {kind: dict(sorted(keys.items())) for kind, keys in sorted(frames.items())}
    total = sum(len(values) for keys in ordered.values() for values in keys.values())
    width = ANIMATION_COLUMNS * FRAME_WIDTH
    height = ((total + ANIMATION_COLUMNS - 1) // ANIMATION_COLUMNS) * FRAME_HEIGHT
    pixels = bytearray(width * height * 4)
    regions: dict[str, dict[str, list[Region]]] = {}
    slot = 0
    for kind, keys in ordered.items():
        regions[kind] = {}
        for key, frames_for_key in keys.items():
            placed: list[Region] = []
            for frame in frames_for_key:
                if len(frame) != FRAME_WIDTH * FRAME_HEIGHT * 4:
                    raise ValueError(f"frame {kind}/{key} is not a 16x32 RGBA frame")
                x = slot % ANIMATION_COLUMNS * FRAME_WIDTH
                y = slot // ANIMATION_COLUMNS * FRAME_HEIGHT
                for row in range(FRAME_HEIGHT):
                    start = ((y + row) * width + x) * 4
                    frame_row = frame[row * FRAME_WIDTH * 4 : (row + 1) * FRAME_WIDTH * 4]
                    pixels[start : start + FRAME_WIDTH * 4] = frame_row
                placed.append({"x": x, "y": y, "width": FRAME_WIDTH, "height": FRAME_HEIGHT})
                slot += 1
            regions[kind][key] = placed
    return width, height, encode_png(width, height, bytes(pixels)), regions


def attach_animation_frames(
    pack_directory: Path,
    frames: dict[str, dict[str, list[bytes]]],
    *,
    cycle_frames: int,
    samples: int = 2,
    map_id: str | None = None,
) -> AnimationSection:
    """Write frames the sprite audit captured into a pack that already has a manifest.

    The frames live in their own atlas next to the existing one, so packs without them
    keep working and re-auditing does not need to rebuild the pack from the ROM. The
    caller passes the whole set of frames for every region that cycles, including ones
    an earlier audit already stored, and the previous animation atlas is replaced with
    the single new one. Callers that merge existing frames hold the pack lock
    from reading through publication.
    """
    pack_directory = pack_directory.expanduser().resolve()
    manifest_path = pack_directory / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"No sprite manifest at {manifest_path}")
    manifest: dict[str, Any] = json.loads(manifest_path.read_text())
    for kind, keys in frames.items():
        if kind not in ("terrain", "terrain_variants"):
            raise ValueError(f"animation frames cannot be stored in {kind}")
        for key, captured in keys.items():
            if key not in manifest.get(kind, {}):
                raise ValueError(f"the pack has no {kind} region for {key}")
            if len(captured) > MAX_FRAMES_PER_REGION:
                raise ValueError(
                    f"region {kind}/{key} has more than {MAX_FRAMES_PER_REGION} frames"
                )
    total = sum(len(values) for keys in frames.values() for values in keys.values())
    if total > MAX_ANIMATION_FRAMES:
        raise ValueError(f"more than {MAX_ANIMATION_FRAMES} animation frames")
    width, height, png, regions = animation_atlas(frames)
    digest = hashlib.sha256(png).hexdigest()
    atlas = f"animation-{digest}.png"
    previous = manifest.get("animation")
    maps: list[str] = list(previous.get("maps", [])) if isinstance(previous, dict) else []
    for name in ((previous.get("map_id") if isinstance(previous, dict) else None), map_id):
        if name and name not in maps:
            maps.append(name)
    section: AnimationSection = {
        "atlas": atlas,
        "atlas_sha256": digest,
        "width": width,
        "height": height,
        "cycle_frames": cycle_frames,
        "samples_per_view": samples,
        "map_id": map_id,
        "maps": maps,
        "captured_by": "aw2-lab sprite-audit",
        "frames": regions,
    }
    manifest["animation"] = section
    SpritePackManifest.model_validate(manifest)
    with TemporaryDirectory(prefix=".animation-", dir=pack_directory) as staging:
        staged_atlas = Path(staging) / atlas
        staged_manifest = Path(staging) / manifest_path.name
        staged_atlas.write_bytes(png)
        staged_manifest.write_text(json.dumps(manifest, indent=2) + "\n")
        atlas_path = pack_directory / atlas
        atlas_existed = os.path.lexists(atlas_path)
        staged_atlas.replace(atlas_path)
        try:
            staged_manifest.replace(manifest_path)
        except OSError:
            if not atlas_existed:
                atlas_path.unlink(missing_ok=True)
            raise
    if isinstance(previous, dict):
        stale = previous.get("atlas")
        if stale != atlas and valid_animation_atlas_name(stale, previous.get("atlas_sha256")):
            stale_path = pack_directory / stale
            if stale_path.is_file():
                stale_path.unlink(missing_ok=True)
    return section


def property_frame(rom: bytes, terrain: int, army: int) -> tuple[int, int, bytes]:
    if terrain == 8:
        offset, count = 0x0D16C4 + max(0, army - 1) * 256, 8
    else:
        offset, count = PROPERTY_SOURCES[terrain]
    palette = decode_palette(rom, 0x0D3EE4 + army * 32, transparent=True)
    return compose_tiles([decode_tile(rom, offset + i * 32, palette) for i in range(count)], 2)


def terrain_frame(rom: bytes, terrain: int, army: int) -> tuple[int, int, bytes]:
    tile = next(
        (i for i, value in enumerate(rom[0x0C1BC4:0x0C1FC4]) if value & 31 == terrain),
        None,
    )
    if tile is None:
        raise ValueError(f"No verified graphical tile for terrain {terrain}")
    # The first sea entry (8) is a tiny island/shore transition. Use the
    # interior water tile observed at Bean Island (0,0), not a repeated coast.
    if terrain == 7:
        tile = 42
        if rom[0x0C1BC4 + tile] & 31 != terrain:
            raise ValueError("Representative sea tile does not match the terrain lookup")
    _, _, ground = terrain_sample(rom, tile)
    result = bytearray(16 * 32 * 4)
    result[16 * 16 * 4 :] = ground
    if terrain in PROPERTY_SOURCES or terrain == 8:
        _, height, foreground = property_frame(rom, terrain, army)
        for y in range(height):
            for x in range(16):
                source = (y * 16 + x) * 4
                destination = ((32 - height + y) * 16 + x) * 4
                if foreground[source + 3]:
                    result[destination : destination + 4] = foreground[source : source + 4]
    return 16, 32, bytes(result)


def terrain_variant_frame(rom: bytes, graphical_tile_id: int) -> tuple[int, int, bytes]:
    """Keep a map cell's own ground composition, palette, orientation, and flips."""
    if not 0 <= graphical_tile_id < 1024 or (
        rom[0x0C1BC4 + graphical_tile_id] & 31 not in TERRAIN_VARIANT_CLASSES
    ):
        raise ValueError("Expected a verified per-cell terrain graphical tile")
    _, _, ground = terrain_sample(rom, graphical_tile_id)
    return 16, 32, bytes(16 * 16 * 4) + ground


def build_sprite_pack(rom_path: Path, output: Path) -> SpriteManifest:
    profile = select_rom_profile(rom_path)
    output = output.expanduser().resolve()
    project = Path(__file__).resolve().parents[2]
    if output.is_relative_to(project) or output.is_relative_to(Path("/nix/store")):
        raise ValueError("Generated artwork must be outside the repository and Nix store")
    rom = rom_path.read_bytes()
    frames: list[tuple[str, str, tuple[int, int, bytes]]] = []
    for unit in sorted(UNIT_DATA):
        for army in range(1, 6):
            frames.append(("units", f"{unit}:{army}", unit_sample(rom, unit, army)))
    for terrain in TERRAIN_CLASSES:
        for army in range(6):
            frames.append(("terrain", f"{terrain}:{army}", terrain_frame(rom, terrain, army)))
    map_count = len(frames)
    map_height = ((map_count + 15) // 16) * 32
    for co_id in range(19):
        frames.append(("portraits", str(co_id), co_portrait_sample(rom, co_id)))
    variant_ids = [
        tile
        for tile, value in enumerate(rom[0x0C1BC4:0x0C1FC4])
        if value & 31 in TERRAIN_VARIANT_CLASSES
    ]
    for tile in variant_ids:
        terrain = rom[0x0C1BC4 + tile] & 31
        frames.append(("terrain_variants", f"{terrain}:{tile}", terrain_variant_frame(rom, tile)))
    variants_y = map_height + 4 * 48
    width, height = 256, variants_y + ((len(variant_ids) + 15) // 16) * 32
    pixels = bytearray(width * height * 4)
    units: dict[str, Region] = {}
    terrains: dict[str, Region] = {}
    portraits: dict[str, Region] = {}
    terrain_variants: dict[str, Region] = {}
    collections = {
        "units": units,
        "terrain": terrains,
        "portraits": portraits,
        "terrain_variants": terrain_variants,
    }
    for index, (kind, key, (w, h, frame)) in enumerate(frames):
        if kind == "portraits":
            portrait_index = index - map_count
            x, y = portrait_index % 5 * 48, map_height + portrait_index // 5 * 48
        elif kind == "terrain_variants":
            variant_index = index - map_count - 19
            x, y = variant_index % 16 * 16, variants_y + variant_index // 16 * 32
        else:
            x, y = index % 16 * 16, index // 16 * 32
        for row in range(h):
            start = ((y + row) * width + x) * 4
            pixels[start : start + w * 4] = frame[row * w * 4 : (row + 1) * w * 4]
        collections[kind][key] = {
            "x": x,
            "y": y,
            "width": w,
            "height": h,
        }
    png = encode_png(width, height, bytes(pixels))
    digest = hashlib.sha256(png).hexdigest()
    atlas = f"atlas-{digest}.png"
    manifest: SpriteManifest = {
        "kind": "aw2-client-sprites",
        "version": 1,
        "rom_sha256": profile.sha256,
        "atlas": atlas,
        "atlas_sha256": digest,
        "width": width,
        "height": height,
        "units": units,
        "terrain": terrains,
        "portraits": portraits,
        "terrain_variants": terrain_variants,
        "animation": None,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / atlas).write_bytes(png)
    temporary = output / ".manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, indent=2) + "\n")
    temporary.replace(output / "manifest.json")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = build_sprite_pack(args.rom, args.output_dir)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Sprite pack extraction failed: {error}\n")
    print(
        f"Extracted {len(manifest['units'])} unit, {len(manifest['terrain'])} terrain, "
        f"{len(manifest['portraits'])} CO portraits, and {len(manifest['terrain_variants'])} terrain variants"
    )


if __name__ == "__main__":
    main()
