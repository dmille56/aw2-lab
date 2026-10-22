"""Command-line entry point for the local backend."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import fields
from pathlib import Path

import uvicorn

from aw2_lab.bridge import BridgeError, LuaBridgeClient
from aw2_lab.emulator import EmulatorMode, EmulatorSettings
from aw2_lab.research import ResearchContext, capture_memory_dump, write_memory_dump
from aw2_lab.rom_profile import UnsupportedRomError


def main() -> None:
    if sys.argv[1:2] == ["dump-memory"]:
        _dump_memory(sys.argv[2:])
        return
    parser = argparse.ArgumentParser(
        prog="aw2-lab",
        epilog="Research tools: aw2-lab dump-memory --help",
    )
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
        help="headless mGBA executable (default: mgba-headless)",
    )
    parser.add_argument(
        "--mgba-windowed",
        metavar="PATH",
        help="windowed mGBA executable (default: mgba-qt)",
    )
    parser.add_argument(
        "--lua-bridge",
        metavar="PATH",
        type=Path,
        help="Lua bridge script to load (default: bundled lua/bridge.lua)",
    )
    parser.add_argument(
        "--scripting-console",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="show mGBA's scripting console in windowed mode (default: false; "
        "AW2_MGBA_SCRIPTING_CONSOLE)",
    )
    args = parser.parse_args()

    if not args.rom:
        parser.error("an AW2 ROM is required; provide --rom or set AW2_ROM_PATH")
    rom_path = Path(args.rom).expanduser()
    if not rom_path.is_file():
        parser.error(f"ROM path is not a file: {rom_path}")
    rom_path = rom_path.resolve()

    try:
        emulator_mode = args.emulator_mode or EmulatorMode(
            os.environ.get("AW2_EMULATOR_MODE", EmulatorMode.HEADLESS)
        )
    except ValueError:
        parser.error("AW2_EMULATOR_MODE must be 'headless' or 'windowed'")
    console_env = os.environ.get("AW2_MGBA_SCRIPTING_CONSOLE", "false").lower()
    true_values = {"1", "true", "yes", "on"}
    false_values = {"0", "false", "no", "off"}
    if console_env not in true_values | false_values:
        parser.error("AW2_MGBA_SCRIPTING_CONSOLE must be true or false")
    show_scripting_console = (
        args.scripting_console if args.scripting_console is not None else console_env in true_values
    )

    settings = EmulatorSettings(
        rom_path=rom_path,
        mode=emulator_mode,
        headless_executable=args.mgba_headless,
        windowed_executable=args.mgba_windowed,
        bridge_script=args.lua_bridge.expanduser().resolve() if args.lua_bridge else None,
        show_scripting_console=show_scripting_console,
    )
    print("Emulator settings:")
    for setting in fields(settings):
        print(f"  {setting.name}: {getattr(settings, setting.name)}")

    from aw2_lab.api.app import create_app

    try:
        application = create_app(settings=settings)
    except UnsupportedRomError as error:
        parser.error(str(error))

    uvicorn.run(
        application,
        host=args.host,
        port=args.port,
    )


def _memory_range(value: str) -> tuple[int, int]:
    try:
        address, length = value.split(":")
        return int(address, 0), int(length, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "expected ADDRESS:LENGTH in decimal or hexadecimal"
        ) from error


def _dump_memory(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="aw2-lab dump-memory",
        description="Capture up to 4 KiB from the running local bridge without advancing frames.",
    )
    parser.add_argument("--rom", default=os.environ.get("AW2_ROM_PATH"), metavar="PATH")
    parser.add_argument(
        "--range", dest="ranges", action="append", type=_memory_range, required=True
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--emulator-mode", type=EmulatorMode, choices=tuple(EmulatorMode), required=True
    )
    parser.add_argument("--emulator-build", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--reproduction", required=True)
    args = parser.parse_args(arguments)
    if not args.rom:
        parser.error("an AW2 ROM is required; provide --rom or set AW2_ROM_PATH")
    context = ResearchContext(
        emulator_mode=args.emulator_mode,
        emulator_build=args.emulator_build,
        checkpoint=args.checkpoint,
        reproduction=args.reproduction,
    )
    try:
        dump = asyncio.run(
            capture_memory_dump(
                LuaBridgeClient(),
                rom_path=Path(args.rom).expanduser(),
                ranges=args.ranges,
                context=context,
            )
        )
        destination = args.output.expanduser()
        write_memory_dump(dump, destination)
    except (ValueError, OSError, BridgeError) as error:
        parser.error(str(error))
    print(f"Saved {len(dump.ranges)} ranges at frame {dump.frame} to {destination}")
