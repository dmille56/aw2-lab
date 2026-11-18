"""Sprite delivery must expose only the validated manifest and PNG, without a ROM."""

import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from aw2_lab.api.client_sprites import configure_sprite_assets
from aw2_lab.rom_profile import AW2_US_REVISION_0
from aw2_lab.sprite_extraction import encode_png


def write_synthetic_pack(directory: Path, width: int = 16, height: int = 32) -> dict:
    png = encode_png(width, height, bytes((40, 140, 80, 255)) * width * height)
    digest = hashlib.sha256(png).hexdigest()
    manifest = {
        "kind": "aw2-client-sprites",
        "version": 1,
        "rom_sha256": AW2_US_REVISION_0.sha256,
        "atlas": f"atlas-{digest}.png",
        "atlas_sha256": digest,
        "width": width,
        "height": height,
        "units": {"1:1": {"x": 0, "y": 0, "width": 16, "height": 16}},
        "terrain": {"1:0": {"x": 0, "y": 0, "width": 16, "height": 32}},
    }
    (directory / manifest["atlas"]).write_bytes(png)
    (directory / "manifest.json").write_text(json.dumps(manifest))
    (directory / "private.gba").write_bytes(b"not an asset")
    return manifest


def test_only_manifest_and_validated_atlas_are_served(tmp_path: Path) -> None:
    manifest = write_synthetic_pack(tmp_path)
    app = FastAPI()
    configure_sprite_assets(app, tmp_path)

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/client-sprites/manifest.json")
            assert response.json() == manifest
            assert response.headers["cache-control"] == "no-store"
            response = await client.get("/client-sprites/" + manifest["atlas"])
            assert response.headers["content-type"] == "image/png"
            assert hashlib.sha256(response.content).hexdigest() == manifest["atlas_sha256"]
            assert (await client.get("/client-sprites/private.gba")).status_code == 404
            assert (await client.get("/client-sprites/unknown.png")).status_code == 404

    asyncio.run(scenario())


def test_absent_pack_is_a_quiet_symbolic_fallback() -> None:
    app = FastAPI()
    configure_sprite_assets(app, None)

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/client-sprites/manifest.json")).json() is None

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["path", "hash", "region", "rom", "dimensions"])
def test_invalid_pack_fails_before_serving(tmp_path: Path, failure: str) -> None:
    manifest = write_synthetic_pack(tmp_path)
    if failure == "path":
        manifest["atlas"] = "../private.gba"
    elif failure == "hash":
        (tmp_path / manifest["atlas"]).write_bytes(b"wrong image")
    elif failure == "region":
        manifest["units"]["1:1"]["x"] = 100
    elif failure == "rom":
        manifest["rom_sha256"] = "0" * 64
    else:
        manifest["width"] = 17
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        configure_sprite_assets(FastAPI(), tmp_path)


def test_optional_co_portraits_are_validated_and_served(tmp_path: Path) -> None:
    manifest = write_synthetic_pack(tmp_path, width=48, height=48)
    manifest["portraits"] = {"1": {"x": 0, "y": 0, "width": 48, "height": 48}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    app = FastAPI()
    configure_sprite_assets(app, tmp_path)

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/client-sprites/manifest.json")).json() == manifest

    asyncio.run(scenario())
    manifest["portraits"]["19"] = manifest["portraits"]["1"]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        configure_sprite_assets(FastAPI(), tmp_path)


def test_wide_map_sprite_still_fails_before_serving(tmp_path: Path) -> None:
    manifest = write_synthetic_pack(tmp_path, width=48)
    manifest["units"]["1:1"]["width"] = 48
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Map sprite regions"):
        configure_sprite_assets(FastAPI(), tmp_path)


def test_optional_terrain_variants_are_served(tmp_path: Path) -> None:
    manifest = write_synthetic_pack(tmp_path)
    manifest["terrain_variants"] = {
        key: {"x": 0, "y": 0, "width": 16, "height": 32}
        for key in ("3:2", "3:34", "4:134", "5:64", "13:16", "7:42")
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    app = FastAPI()
    configure_sprite_assets(app, tmp_path)

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/client-sprites/manifest.json")).json() == manifest

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "key", ["13:1024", "13:-1", "13:0016", "6:16", "5:1024", "4:1024", "3:1024", "3:0032", "2:32"]
)
def test_invalid_terrain_variant_keys_are_rejected(tmp_path: Path, key: str) -> None:
    manifest = write_synthetic_pack(tmp_path)
    manifest["terrain_variants"] = {key: {"x": 0, "y": 0, "width": 16, "height": 32}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        configure_sprite_assets(FastAPI(), tmp_path)
