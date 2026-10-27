"""Run the real API with prototype assets and explicit native origins; needs a ROM."""

import argparse
import os
from pathlib import Path

import uvicorn
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from aw2_lab.api.app import create_app
from aw2_lab.emulator import EmulatorSettings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rom-path",
        default=os.environ.get("AW2_ROM_PATH"),
        metavar="PATH",
        help="path to your AW2 ROM (required; default: AW2_ROM_PATH)",
    )
    args = parser.parse_args()
    if not args.rom_path:
        parser.error("an AW2 ROM is required; provide --rom-path or set AW2_ROM_PATH")
    rom_path = Path(args.rom_path).expanduser()
    if not rom_path.is_file():
        parser.error(f"ROM path is not a file: {rom_path}")
    app = create_app(settings=EmulatorSettings(rom_path=rom_path.resolve()))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"],
        allow_methods=["GET"],
    )
    app.mount("/client", StaticFiles(directory=Path(__file__).parent / "web", html=True))
    uvicorn.run(app, host="127.0.0.1", port=43127)


if __name__ == "__main__":
    main()
