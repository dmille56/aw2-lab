"""Interactive, isolated cold-boot evidence recorder for the supported AW2 ROM."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from struct import unpack_from

from aw2_lab import __version__
from aw2_lab.bridge import BridgeError, LuaBridgeClient
from aw2_lab.cold_boot import ColdBootError, boot_fixed_versus_match
from aw2_lab.emulator import EmulatorLauncher, EmulatorMode, EmulatorSettings
from aw2_lab.lifecycle import BattleControlObservation, classify_lifecycle
from aw2_lab.rom_profile import select_rom_profile

_PROCESS_POOL = (0x0200D610, 32 * 0x6C)
_CONTROL = (0x03003F3C, 0xC4)
_CALLBACKS = (0x030040D0, 0x20)
_SETUP = (0x02017C61, 0x10)
_MAP = (0x0201E450, 4)
_BATTLE_STATE = (0x030032D8, 2)
_LOCK = (0x030030F0, 1)
_INPUT_GATE = (0x030040E4, 2)
_INPUT_STATE = (0x03003334, 2)
_KEYS = {
    "a": 1,
    "b": 2,
    "select": 4,
    "start": 8,
    "right": 16,
    "left": 32,
    "up": 64,
    "down": 128,
    "r": 256,
    "l": 512,
}
_FULL_RAM_REGIONS = ((0x02000000, 0x40000), (0x03000000, 0x8000))
_CHUNK_BYTES = 4096


def recorder_main(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="aw2-lab record-cold-boot",
        description=(
            "Launch an isolated AW2 emulator and record a manual cold-boot input trace, "
            "screenshots, lifecycle evidence, and optional full RAM snapshots."
        ),
    )
    parser.add_argument(
        "--rom",
        type=Path,
        default=Path(os.environ["AW2_ROM_PATH"]) if os.environ.get("AW2_ROM_PATH") else None,
        metavar="PATH",
    )
    parser.add_argument("--mode", type=EmulatorMode, choices=tuple(EmulatorMode), required=True)
    parser.add_argument("--output", type=Path, required=True, metavar="DIR")
    parser.add_argument("--save-mode", choices=("fresh", "existing"), required=True)
    parser.add_argument(
        "--existing-save",
        type=Path,
        metavar="PATH",
        help="copy this save into the isolated run (required with --save-mode existing)",
    )
    parser.add_argument("--mgba-headless", metavar="PATH")
    parser.add_argument("--mgba-windowed", metavar="PATH")
    parser.add_argument("--lua-bridge", type=Path, metavar="PATH")
    parser.add_argument(
        "--full-ram",
        action="store_true",
        help="capture all EWRAM and IWRAM after each step (slower; recommended for setup research)",
    )
    parser.add_argument(
        "--automate-fixed-match",
        action="store_true",
        help="run the captured fresh-save path automatically and stop at the first player turn",
    )
    args = parser.parse_args(arguments)

    if not args.rom:
        parser.error("an AW2 ROM is required; provide --rom or set AW2_ROM_PATH")
    rom_path = args.rom.expanduser().resolve()
    if not rom_path.is_file():
        parser.error(f"ROM path is not a file: {rom_path}")
    if args.save_mode == "existing" and args.existing_save is None:
        parser.error("--existing-save is required when --save-mode is existing")
    if args.save_mode == "fresh" and args.existing_save is not None:
        parser.error("--existing-save cannot be used with --save-mode fresh")
    if args.automate_fixed_match and args.save_mode != "fresh":
        parser.error("--automate-fixed-match is only verified for --save-mode fresh")
    if args.existing_save is not None and not args.existing_save.expanduser().is_file():
        parser.error(f"existing save is not a file: {args.existing_save}")

    try:
        profile = select_rom_profile(rom_path)
        output = _create_output_directory(args.output)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    save_directory = output / "save-data"
    save_directory.mkdir()
    if args.existing_save is not None:
        source = args.existing_save.expanduser().resolve()
        if source.suffix.lower() != ".sav":
            parser.error("--existing-save must be an mGBA .sav file")
        shutil.copy2(source, save_directory / f"{rom_path.stem}.sav")

    config_root = output / "mgba-config"
    data_root = output / "mgba-data"
    cache_root = output / "mgba-cache"
    config_root.mkdir()
    data_root.mkdir()
    cache_root.mkdir()
    mgba_config = config_root / "mgba"
    mgba_config.mkdir()
    (mgba_config / "config.ini").write_text(
        "".join(
            f"[ports.{frontend}]\nsavegamePath={save_directory}\nsavestatePath={output}\n"
            for frontend in ("headless", "qt")
        ),
        encoding="utf-8",
    )

    settings = EmulatorSettings(
        rom_path=rom_path,
        mode=args.mode,
        headless_executable=args.mgba_headless,
        windowed_executable=args.mgba_windowed,
        bridge_script=args.lua_bridge.expanduser().resolve() if args.lua_bridge else None,
        suppress_emulator_output=True,
    )
    launcher = EmulatorLauncher(settings)
    bridge = LuaBridgeClient(timeout=2)
    _write_json(
        output / "manifest.json",
        {
            "schema_version": 1,
            "tool_version": __version__,
            "rom_profile": profile.__dict__
            if hasattr(profile, "__dict__")
            else {field: getattr(profile, field) for field in profile.__dataclass_fields__},
            "rom_path": str(rom_path),
            "rom_sha256": profile.sha256,
            "mode": args.mode.value,
            "save_mode": args.save_mode,
            "existing_save_sha256": (
                _sha256_file(args.existing_save.expanduser())
                if args.existing_save is not None
                else None
            ),
            "full_ram": args.full_ram,
            "started_at": datetime.now(UTC).isoformat(),
        },
    )

    async def run() -> None:
        with _isolated_xdg(config_root, data_root, cache_root):
            await launcher.start()
        try:
            print(
                f"mGBA {args.mode.value} ready; build identity: {launcher.build_identity}\n"
                f"Evidence directory: {output}\n"
                "Enter a button combination and frame count (for example `start 1`, "
                "`down+a 1`, `neutral 30`), `capture LABEL`, or `quit`.\n"
                "Buttons: a b select start up down left right l r. Inputs are sent only "
                "through the bridge; local window input stays disabled."
            )
            await _capture_step(bridge, output, 0, "initial", None, args.full_ram)
            _append_trace(
                output,
                {
                    "event": "emulator_started",
                    "at": datetime.now(UTC).isoformat(),
                    "emulator_build": launcher.build_identity,
                },
            )
            index = 1
            if args.automate_fixed_match:

                async def record_checkpoint(label: str, input_event: dict[str, int] | None) -> None:
                    nonlocal index
                    frame = await _capture_step(
                        bridge,
                        output,
                        index,
                        label,
                        input_event,
                        args.full_ram,
                    )
                    _append_trace(
                        output,
                        {
                            "step": index,
                            "label": label,
                            "frame": frame,
                            "input": input_event,
                        },
                    )
                    print(f"Captured {label} at frame {frame}.")
                    index += 1

                result = await boot_fixed_versus_match(
                    bridge,
                    rom_path=rom_path,
                    checkpoint_recorder=record_checkpoint,
                )
                battle = result.game_state.battle.value
                if battle is None:
                    raise ColdBootError("Verified cold boot returned no battle state")
                _write_json(
                    output / "automation-result.json",
                    {
                        "status": "verified",
                        "final_frame": result.game_state.frame,
                        "map_id": result.map_id,
                        "phase": result.game_state.lifecycle.phase.value,
                        "day": battle.day,
                        "active_player_slot": battle.active_player_slot,
                        "events": [
                            {
                                "label": event.label,
                                "frame": event.frame,
                                "phase": event.phase.value,
                                "input": event.input,
                            }
                            for event in result.events
                        ],
                    },
                )
                print(
                    f"Fixed Versus match ready at frame {result.game_state.frame}; "
                    "final state verified."
                )
                return

            while True:
                try:
                    command = await asyncio.to_thread(input, "cold-boot> ")
                except EOFError:
                    break
                command = command.strip()
                if not command:
                    continue
                if command.lower() in {"q", "quit", "exit"}:
                    break
                if command.lower().startswith("capture "):
                    label = command[8:].strip()
                    if not label:
                        print("Provide a short capture label.")
                        continue
                    frame = await _capture_step(bridge, output, index, label, None, args.full_ram)
                else:
                    try:
                        buttons, frames = _parse_input(command)
                        frame = await bridge.press_keys(buttons, frames)
                    except (ValueError, BridgeError) as error:
                        print(f"Input rejected: {error}")
                        continue
                    frame = await _capture_step(
                        bridge,
                        output,
                        index,
                        command,
                        {"keys": buttons, "frames": frames},
                        args.full_ram,
                        expected_frame=frame,
                    )
                _append_trace(
                    output,
                    {
                        "step": index,
                        "label": command if not command.lower().startswith("capture ") else label,
                        "frame": frame,
                    },
                )
                print(f"Captured step {index:04d} at frame {frame}.")
                index += 1
        finally:
            await launcher.stop()
            _append_trace(
                output,
                {"event": "emulator_stopped", "at": datetime.now(UTC).isoformat()},
            )

    try:
        asyncio.run(run())
    except (BridgeError, ColdBootError, OSError, RuntimeError) as error:
        print(f"Recorder stopped: {error}", file=sys.stderr)
        raise SystemExit(1) from error


async def _capture_step(
    bridge: LuaBridgeClient,
    output: Path,
    index: int,
    label: str,
    input_event: dict[str, int] | None,
    full_ram: bool,
    *,
    expected_frame: int | None = None,
) -> int:
    ranges = [
        _PROCESS_POOL,
        _CONTROL,
        _CALLBACKS,
        _SETUP,
        _MAP,
        _BATTLE_STATE,
        _LOCK,
        _INPUT_GATE,
        _INPUT_STATE,
    ]
    snapshot = await bridge.read_memory_snapshot(ranges)
    if expected_frame is not None and snapshot.frame != expected_frame:
        raise BridgeError(
            f"frame changed after input: bridge returned {expected_frame}, "
            f"snapshot reports {snapshot.frame}"
        )
    pool, control, callbacks, setup, map_data, battle_state, lock, gate, input_state = (
        snapshot.ranges
    )
    scripts = tuple(unpack_from("<I", pool, slot * 0x6C)[0] for slot in range(32))
    lifecycle = classify_lifecycle(
        unpack_from("<I", callbacks)[0],
        unpack_from("<I", callbacks, 0x1C)[0],
        scripts,
        battle_control=BattleControlObservation(
            mode=unpack_from("<I", control)[0],
            state=unpack_from("<H", battle_state)[0],
            lock_count=lock[0],
            input_gate=int.from_bytes(gate, "little", signed=True),
            input_state=unpack_from("<H", input_state)[0],
        ),
    )
    screenshot = await bridge.screenshot()
    if await bridge.advance_frames(0) != snapshot.frame:
        raise BridgeError("emulator advanced while the observation was being captured")

    prefix = output / f"step-{index:04d}"
    (prefix.with_suffix(".png")).write_bytes(screenshot)
    ram_record: dict[str, object] | None = None
    if full_ram:
        chunks: list[bytes] = []
        for base, length in _FULL_RAM_REGIONS:
            for offset in range(0, length, _CHUNK_BYTES):
                chunk = await bridge.read_memory_snapshot(
                    [(base + offset, min(_CHUNK_BYTES, length - offset))]
                )
                if chunk.frame != snapshot.frame:
                    raise BridgeError("emulator frame changed during full RAM capture")
                chunks.extend(chunk.ranges)
        raw = b"".join(chunks)
        ram_path = prefix.with_suffix(".ram.bin")
        ram_path.write_bytes(raw)
        ram_record = {
            "path": ram_path.name,
            "layout": [{"address": base, "length": length} for base, length in _FULL_RAM_REGIONS],
            "sha256": hashlib.sha256(raw).hexdigest(),
        }

    record = {
        "schema_version": 1,
        "step": index,
        "label": label,
        "input": input_event,
        "captured_at": datetime.now(UTC).isoformat(),
        "frame": snapshot.frame,
        "screenshot": prefix.with_suffix(".png").name,
        "lifecycle": {
            "phase": lifecycle.phase.value,
            "engine": lifecycle.engine.value,
            "battle_decode_safety": lifecycle.battle_decode_safety.value,
            "matched_scripts": [f"0x{value:08X}" for value in lifecycle.matched_scripts],
            "active_process_scripts": [
                f"0x{value:08X}" for value in lifecycle.active_process_scripts
            ],
        },
        "observed_bytes": {
            "process_pool": pool.hex(),
            "control": control.hex(),
            "callbacks": callbacks.hex(),
            "setup": setup.hex(),
            "map": map_data.hex(),
            "battle_control_state": battle_state.hex(),
            "battle_control_lock": lock.hex(),
            "battle_input_gate": gate.hex(),
            "battle_input_state": input_state.hex(),
        },
        "ram": ram_record,
    }
    _write_json(prefix.with_suffix(".json"), record)
    return snapshot.frame


def _parse_input(command: str) -> tuple[int, int]:
    pieces = command.lower().split()
    if len(pieces) != 2:
        raise ValueError("expected BUTTON[+BUTTON...] FRAMES")
    names, frame_text = pieces
    try:
        frames = int(frame_text, 10)
    except ValueError as error:
        raise ValueError("frame count must be an integer from 1 to 600") from error
    if not 1 <= frames <= 600:
        raise ValueError("frame count must be an integer from 1 to 600")
    keys = 0
    if names == "neutral":
        return 0, frames
    for name in names.split("+"):
        if name not in _KEYS:
            raise ValueError(f"unknown button {name!r}")
        if keys & _KEYS[name]:
            raise ValueError(f"button {name!r} was repeated")
        keys |= _KEYS[name]
    return keys, frames


def _create_output_directory(path: Path) -> Path:
    destination = path.expanduser().resolve()
    repository_root = Path(__file__).resolve().parents[2]
    protected_roots = (repository_root, Path("/nix/store"))
    if any(
        destination == protected or protected in destination.parents
        for protected in protected_roots
    ):
        raise ValueError("evidence output must be outside the checkout and /nix/store")
    destination.mkdir(parents=True, exist_ok=False)
    return destination


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _append_trace(output: Path, payload: dict[str, object]) -> None:
    with (output / "trace.jsonl").open("a", encoding="utf-8") as trace:
        trace.write(json.dumps(payload, separators=(",", ":")) + "\n")


@contextmanager
def _isolated_xdg(config: Path, data: Path, cache: Path) -> Iterator[None]:
    names = {
        "XDG_CONFIG_HOME": str(config),
        "XDG_DATA_HOME": str(data),
        "XDG_CACHE_HOME": str(cache),
    }
    previous = {name: os.environ.get(name) for name in names}
    os.environ.update(names)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
