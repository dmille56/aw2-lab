"""Serve a validated external sprite pack for the local prototype client."""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response

from aw2_lab.sprite_pack import SpritePackManifest, sprite_pack_lock


def configure_sprite_assets(app: FastAPI, directory: Path | None) -> None:
    manifest: SpritePackManifest | None = None
    atlas_bytes = b""
    animation_bytes = b""
    if directory is not None:
        # Validate at startup; keep only these documents in memory. No directory mount.
        with sprite_pack_lock(directory, shared=True):
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
            if manifest.animation is not None:
                animation_bytes = (directory / manifest.animation.atlas).read_bytes()
                if len(animation_bytes) > 8 * 1024 * 1024:
                    raise ValueError("Animation atlas exceeds the size limit")
                if (
                    not animation_bytes.startswith(b"\x89PNG\r\n\x1a\n")
                    or len(animation_bytes) < 33
                    or animation_bytes[12:16] != b"IHDR"
                    or struct.unpack_from(">II", animation_bytes, 16)
                    != (manifest.animation.width, manifest.animation.height)
                    or hashlib.sha256(animation_bytes).hexdigest()
                    != manifest.animation.atlas_sha256
                ):
                    raise ValueError("Animation atlas does not match its manifest")

    @app.get("/client-sprites/manifest.json", include_in_schema=False)
    async def sprite_manifest() -> JSONResponse:
        return JSONResponse(
            content=manifest.model_dump(mode="json", exclude_unset=True) if manifest else None,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/client-sprites/{name}", include_in_schema=False)
    async def sprite_atlas(name: str) -> Response:
        if manifest is None:
            raise HTTPException(404, "Sprite asset not found")
        if name == manifest.atlas:
            content, cache = atlas_bytes, "public, max-age=31536000, immutable"
        elif manifest.animation is not None and name == manifest.animation.atlas:
            # Captured frames are replaced every time the audit runs, so they are not
            # immutable the way the ROM-derived atlas is.
            content, cache = animation_bytes, "no-store"
        else:
            raise HTTPException(404, "Sprite asset not found")
        return Response(content=content, media_type="image/png", headers={"Cache-Control": cache})
