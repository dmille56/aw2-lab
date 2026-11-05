"""Run the real API with prototype assets and explicit native origins; needs a ROM."""

import argparse
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from aw2_lab.api.app import create_app
from aw2_lab.emulator import EmulatorMode, EmulatorSettings


def configure_client(app: FastAPI, *, assets: Path | None = None) -> None:
    """Serve shared browser/native assets and permit explicit native origins."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"],
        allow_methods=["GET"],
        allow_headers=["Authorization"],
        expose_headers=["X-AW2-Match-ID", "X-AW2-Revision", "X-AW2-Frame"],
    )
    directory = assets or Path(os.environ.get("AW2_CLIENT_DIST", Path(__file__).parent / "dist"))
    if not (directory / "index.html").is_file():
        raise ValueError(
            "Client assets are missing; run nix build .#client-web "
            "--out-link prototypes/client/dist or set AW2_CLIENT_DIST to a production build"
        )
    app.mount("/client", StaticFiles(directory=directory, html=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rom-path",
        default=os.environ.get("AW2_ROM_PATH"),
        metavar="PATH",
        help="path to your AW2 ROM (required; default: AW2_ROM_PATH)",
    )
    parser.add_argument("--operator-secret-file", type=Path)
    parser.add_argument("--storage-dir", type=Path)
    parser.add_argument("--emulator-mode", choices=list(EmulatorMode), default="headless")
    args = parser.parse_args()
    if not args.rom_path:
        parser.error("an AW2 ROM is required; provide --rom-path or set AW2_ROM_PATH")
    rom_path = Path(args.rom_path).expanduser()
    if not rom_path.is_file():
        parser.error(f"ROM path is not a file: {rom_path}")
    options = {}
    if args.operator_secret_file is not None:
        options["operator_secret_file"] = args.operator_secret_file.expanduser()
    if args.storage_dir is not None:
        options["storage_root"] = args.storage_dir.expanduser()
    app = create_app(
        settings=EmulatorSettings(
            rom_path=rom_path.resolve(), mode=EmulatorMode(args.emulator_mode)
        ),
        **options,
    )
    configure_client(app)
    uvicorn.run(app, host="127.0.0.1", port=43127)


if __name__ == "__main__":
    main()
