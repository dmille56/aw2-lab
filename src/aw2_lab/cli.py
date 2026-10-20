"""Command-line entry point for the local backend."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn

from aw2_lab.emulator import EmulatorMode, EmulatorSettings


def main() -> None:
    parser = argparse.ArgumentParser(prog="aw2-lab")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind address (default: loopback)")
    parser.add_argument("--port", default=43127, type=int, help="HTTP port (default: %(default)s)")
    parser.add_argument(
        "--rom",
        default=os.environ.get("AW2_ROM_PATH"),
        metavar="PATH",
        help="path to your AW2 ROM (required; default: AW2_ROM_PATH)",
    )
    parser.add_argument(
        "--emulator-mode",
        type=EmulatorMode,
        choices=tuple(EmulatorMode),
        default=None,
        help="mGBA frontend (default: AW2_EMULATOR_MODE or headless)",
    )
    parser.add_argument(
        "--mgba-headless",
        metavar="PATH",
        help="headless mGBA executable (default: mgba)",
    )
    parser.add_argument(
        "--mgba-windowed",
        metavar="PATH",
        help="windowed mGBA executable (default: mgba-qt)",
    )
    args = parser.parse_args()

    if not args.rom:
        parser.error("an AW2 ROM is required; provide --rom or set AW2_ROM_PATH")
    rom_path = Path(args.rom).expanduser()
    if not rom_path.is_file():
        parser.error(f"ROM path is not a file: {rom_path}")
    rom_path = rom_path.resolve()
    print(f"Using AW2 ROM: {rom_path}")

    try:
        emulator_mode = args.emulator_mode or EmulatorMode(
            os.environ.get("AW2_EMULATOR_MODE", EmulatorMode.HEADLESS)
        )
    except ValueError:
        parser.error("AW2_EMULATOR_MODE must be 'headless' or 'windowed'")
    print(f"Starting mGBA in {emulator_mode.value} mode")

    from aw2_lab.api.app import create_app

    uvicorn.run(
        create_app(
            settings=EmulatorSettings(
                rom_path=rom_path,
                mode=emulator_mode,
                headless_executable=args.mgba_headless,
                windowed_executable=args.mgba_windowed,
            )
        ),
        host=args.host,
        port=args.port,
    )
