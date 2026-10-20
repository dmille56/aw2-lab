"""Command-line entry point for the local backend."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(prog="aw2-lab")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind address (default: loopback)")
    parser.add_argument("--port", default=43127, type=int, help="HTTP port (default: %(default)s)")
    parser.add_argument(
        "--rom",
        default=os.environ.get("AW2_ROM_PATH"),
        metavar="PATH",
        help="path to your AW2 ROM (default: AW2_ROM_PATH)",
    )
    args = parser.parse_args()

    rom_path: Path | None = None
    if args.rom:
        rom_path = Path(args.rom).expanduser()
        if not rom_path.is_file():
            parser.error(f"ROM path is not a file: {rom_path}")
        rom_path = rom_path.resolve()

    from aw2_lab.api.app import create_app

    uvicorn.run(create_app(rom_path=rom_path), host=args.host, port=args.port)
