"""Serve the shared browser client from a local production build."""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from aw2_lab.api.client_sprites import configure_sprite_assets


def configure_client(
    app: FastAPI, *, assets: Path | None = None, sprite_pack: Path | None = None
) -> None:
    """Serve shared browser/native assets and permit explicit native origins."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"],
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization"],
        expose_headers=["X-AW2-Match-ID", "X-AW2-Revision", "X-AW2-Frame"],
    )
    directory = assets or Path(
        os.environ.get("AW2_CLIENT_DIST", Path.cwd() / "prototypes/client/dist")
    )
    if not (directory / "index.html").is_file():
        raise ValueError(
            "Client assets are missing; run nix build .#client-web "
            "--out-link prototypes/client/dist or set AW2_CLIENT_DIST to a production build"
        )
    pack_path = sprite_pack or os.environ.get("AW2_CLIENT_SPRITES")
    configure_sprite_assets(app, Path(pack_path).expanduser() if pack_path else None)
    app.mount("/client", StaticFiles(directory=directory, html=True))
