"""Serve a validated external sprite pack for the local prototype client."""

from __future__ import annotations

import hashlib
import re
import struct
from pathlib import Path
from typing import Literal, Self

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from aw2_lab.rom_profile import AW2_US_REVISION_0
from aw2_lab.sprite_pack import TERRAIN_VARIANT_CLASSES

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


def configure_sprite_assets(app: FastAPI, directory: Path | None) -> None:
    manifest: SpritePackManifest | None = None
    atlas_bytes = b""
    if directory is not None:
        # Validate at startup; keep only these two documents in memory. No directory mount.
        manifest = SpritePackManifest.model_validate_json(
            (directory / "manifest.json").read_bytes()
        )
        atlas_bytes = (directory / manifest.atlas).read_bytes()
        if len(atlas_bytes) > 8 * 1024 * 1024:
            raise ValueError("Sprite atlas exceeds the size limit")
        if (
            not atlas_bytes.startswith(b"\x89PNG\r\n\x1a\n")
            or len(atlas_bytes) < 33
            or atlas_bytes[12:16] != b"IHDR"
            or struct.unpack_from(">II", atlas_bytes, 16) != (manifest.width, manifest.height)
            or hashlib.sha256(atlas_bytes).hexdigest() != manifest.atlas_sha256
        ):
            raise ValueError("Sprite atlas does not match its manifest")

    @app.get("/client-sprites/manifest.json", include_in_schema=False)
    async def sprite_manifest() -> JSONResponse:
        return JSONResponse(
            content=manifest.model_dump(mode="json", exclude_unset=True) if manifest else None,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/client-sprites/{name}", include_in_schema=False)
    async def sprite_atlas(name: str) -> Response:
        if manifest is None or name != manifest.atlas:
            raise HTTPException(404, "Sprite asset not found")
        return Response(
            content=atlas_bytes,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )
