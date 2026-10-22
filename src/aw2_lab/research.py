"""Coherent memory captures and portable research artifacts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from aw2_lab import __version__
from aw2_lab.bridge import LuaBridgeClient
from aw2_lab.emulator import EmulatorMode
from aw2_lab.rom_profile import RomProfile, select_rom_profile


@dataclass(frozen=True, slots=True)
class ResearchContext:
    """Operator-supplied context for reproducing an observation."""

    emulator_mode: EmulatorMode
    emulator_build: str
    checkpoint: str
    reproduction: str


@dataclass(frozen=True, slots=True)
class DumpRange:
    address: int
    length: int
    bytes_hex: str


@dataclass(frozen=True, slots=True)
class MemoryDump:
    schema_version: int
    captured_at: str
    tool_version: str
    rom_profile: RomProfile
    context: ResearchContext
    frame: int
    ranges: tuple[DumpRange, ...]


async def capture_memory_dump(
    bridge: LuaBridgeClient,
    *,
    rom_path: Path,
    ranges: list[tuple[int, int]],
    context: ResearchContext,
) -> MemoryDump:
    """Verify the supplied ROM file and capture one non-advancing memory batch.

    The operator must ensure the running emulator uses the supplied ROM and context.
    """
    for name in ("emulator_build", "checkpoint", "reproduction"):
        if not getattr(context, name).strip():
            raise ValueError(f"{name} must contain research context")
    profile = select_rom_profile(rom_path)
    snapshot = await bridge.read_memory_snapshot(ranges)
    return MemoryDump(
        schema_version=1,
        captured_at=datetime.now(UTC).isoformat(),
        tool_version=__version__,
        rom_profile=profile,
        context=context,
        frame=snapshot.frame,
        ranges=tuple(
            DumpRange(address, length, data.hex())
            for (address, length), data in zip(ranges, snapshot.ranges, strict=True)
        ),
    )


def write_memory_dump(dump: MemoryDump, destination: Path) -> None:
    """Write a new JSON artifact, preserving existing files and cleaning failed writes."""
    payload = json.dumps(asdict(dump), indent=2) + "\n"
    output = destination.open("x", encoding="utf-8")
    try:
        with output:
            output.write(payload)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
