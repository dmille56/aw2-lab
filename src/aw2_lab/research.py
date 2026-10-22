"""Coherent memory captures, comparisons, and portable research artifacts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeGuard

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


@dataclass(frozen=True, slots=True)
class ChangedByte:
    address: int
    before: int
    after: int
    range_index: int
    range_address: int
    range_length: int


@dataclass(frozen=True, slots=True)
class MemoryDiff:
    before: MemoryDump
    after: MemoryDump
    changes: tuple[ChangedByte, ...]


@dataclass(frozen=True, slots=True)
class WatchSample:
    frame: int
    ranges: tuple[DumpRange, ...]


@dataclass(frozen=True, slots=True)
class WatchedByteChange:
    frame: int
    address: int
    before: int
    after: int
    range_index: int


@dataclass(frozen=True, slots=True)
class MemoryWatch:
    schema_version: int
    captured_at: str
    tool_version: str
    rom_profile: RomProfile
    context: ResearchContext
    samples: tuple[WatchSample, ...]
    changes: tuple[WatchedByteChange, ...]


def read_memory_dump(source: Path) -> MemoryDump:
    """Load and validate a schema version 1 memory dump."""
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise TypeError("dump must be a JSON object")
        if not _is_integer(data.get("schema_version")) or data["schema_version"] != 1:
            raise ValueError("unsupported dump schema version; expected 1")
        profile_data = data.get("rom_profile")
        if not isinstance(profile_data, dict):
            raise TypeError("rom_profile must be an object")
        if any(
            not isinstance(profile_data.get(name), str)
            for name in (
                "name",
                "title",
                "game_code",
                "maker_code",
                "sha256",
                "memory_layout_version",
                "decoder_version",
            )
        ) or not _is_integer(profile_data.get("revision")):
            raise ValueError("rom_profile has invalid fields")
        profile = RomProfile(**profile_data)
        context_data = data.get("context")
        if not isinstance(context_data, dict):
            raise TypeError("context must be an object")
        context = ResearchContext(
            emulator_mode=EmulatorMode(context_data["emulator_mode"]),
            emulator_build=_required_string(context_data, "emulator_build"),
            checkpoint=_required_string(context_data, "checkpoint"),
            reproduction=_required_string(context_data, "reproduction"),
        )
        frame = data.get("frame")
        if not _is_integer(frame) or not 0 <= frame < 1 << 32:
            raise ValueError("frame must be an unsigned 32-bit integer")
        range_data = data.get("ranges")
        if not isinstance(range_data, list) or not 1 <= len(range_data) <= 64:
            raise ValueError("ranges must contain between 1 and 64 entries")
        ranges: list[DumpRange] = []
        total_length = 0
        for entry in range_data:
            if not isinstance(entry, dict):
                raise TypeError("each range must be an object")
            address = entry.get("address")
            length = entry.get("length")
            encoded = entry.get("bytes_hex")
            if not _is_integer(address) or not 0 <= address < 1 << 32:
                raise ValueError("range address must be an unsigned 32-bit integer")
            if not _is_integer(length) or length < 0:
                raise ValueError("range length must be a nonnegative integer")
            if address + length > 1 << 32:
                raise ValueError("range extends beyond the 32-bit address space")
            if not isinstance(encoded, str):
                raise TypeError("range bytes_hex must be a string")
            try:
                raw = bytes.fromhex(encoded)
            except ValueError as error:
                raise ValueError("range bytes_hex must contain valid hexadecimal bytes") from error
            if len(raw) != length:
                raise ValueError("range length does not match bytes_hex")
            total_length += length
            ranges.append(DumpRange(address, length, raw.hex()))
        if total_length > 4096:
            raise ValueError("dump ranges exceed the 4096-byte limit")
        return MemoryDump(
            schema_version=1,
            captured_at=_required_string(data, "captured_at"),
            tool_version=_required_string(data, "tool_version"),
            rom_profile=profile,
            context=context,
            frame=frame,
            ranges=tuple(ranges),
        )
    except (KeyError, TypeError) as error:
        raise ValueError(f"invalid memory dump {source}: {error}") from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError(f"invalid JSON memory dump {source}: {error}") from error
    except ValueError as error:
        raise ValueError(f"invalid memory dump {source}: {error}") from error


def compare_memory_dumps(before: MemoryDump, after: MemoryDump) -> MemoryDiff:
    """Compare dumps with matching ROM identity and ordered ranges."""
    if before.rom_profile != after.rom_profile:
        raise ValueError("memory dumps use different ROM profiles")
    before_layout = tuple((item.address, item.length) for item in before.ranges)
    after_layout = tuple((item.address, item.length) for item in after.ranges)
    if before_layout != after_layout:
        raise ValueError("memory dumps must contain identical ranges in the same order")
    changes = tuple(
        ChangedByte(
            address=range_item.address + offset,
            before=old,
            after=new,
            range_index=range_index,
            range_address=range_item.address,
            range_length=range_item.length,
        )
        for range_index, (range_item, new_range) in enumerate(
            zip(before.ranges, after.ranges, strict=True)
        )
        for offset, (old, new) in enumerate(
            zip(
                bytes.fromhex(range_item.bytes_hex),
                bytes.fromhex(new_range.bytes_hex),
                strict=True,
            )
        )
        if old != new
    )
    return MemoryDiff(before=before, after=after, changes=changes)


def format_memory_diff(diff: MemoryDiff) -> str:
    """Render a comparison with both observations' frame and reproduction context."""
    before = diff.before
    after = diff.after
    lines = [
        (
            f"Before: frame {before.frame} ({before.context.emulator_mode.value}, "
            f"{before.context.emulator_build}) — {before.context.checkpoint}; "
            f"{before.context.reproduction}"
        ),
        (
            f"After:  frame {after.frame} ({after.context.emulator_mode.value}, "
            f"{after.context.emulator_build}) — {after.context.checkpoint}; "
            f"{after.context.reproduction}"
        ),
        f"Changed bytes: {len(diff.changes)}",
    ]
    if diff.changes:
        lines.append("ADDRESS     BEFORE  AFTER   RANGE")
        lines.extend(
            f"0x{change.address:08X}  0x{change.before:02X}    0x{change.after:02X}    "
            f"#{change.range_index + 1} 0x{change.range_address:08X}:0x{change.range_length:X}"
            for change in diff.changes
        )
    return "\n".join(lines)


def format_memory_watch(watch: MemoryWatch) -> str:
    """Render each observed value change with its resulting frame and address."""
    lines = [
        f"Samples: {len(watch.samples)}",
        f"Frame span: {watch.samples[0].frame}–{watch.samples[-1].frame}",
        f"Changed bytes: {len(watch.changes)}",
    ]
    if watch.changes:
        lines.append("FRAME  ADDRESS     BEFORE  AFTER")
        lines.extend(
            f"{change.frame:<6} 0x{change.address:08X}  0x{change.before:02X}    "
            f"0x{change.after:02X}"
            for change in watch.changes
        )
    return "\n".join(lines)


def _required_string(data: dict[str, object], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    return value


def _is_integer(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


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


async def watch_memory(
    bridge: LuaBridgeClient,
    *,
    rom_path: Path,
    ranges: list[tuple[int, int]],
    context: ResearchContext,
    steps: int,
    frames_per_step: int,
) -> MemoryWatch:
    """Capture an initial sample and then one sample after each explicit neutral step."""
    for name in ("emulator_build", "checkpoint", "reproduction"):
        if not getattr(context, name).strip():
            raise ValueError(f"{name} must contain research context")
    if isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= 600:
        raise ValueError("steps must be an integer from 1 to 600")
    if (
        isinstance(frames_per_step, bool)
        or not isinstance(frames_per_step, int)
        or not 1 <= frames_per_step <= 600
    ):
        raise ValueError("frames_per_step must be an integer from 1 to 600")

    profile = select_rom_profile(rom_path)
    samples: list[WatchSample] = []
    changes: list[WatchedByteChange] = []

    async def sample(expected_frame: int | None = None) -> WatchSample:
        snapshot = await bridge.read_memory_snapshot(ranges)
        if expected_frame is not None and snapshot.frame != expected_frame:
            raise ValueError(
                f"emulator frame changed unexpectedly: expected {expected_frame}, "
                f"observed {snapshot.frame}"
            )
        return WatchSample(
            frame=snapshot.frame,
            ranges=tuple(
                DumpRange(address, length, data.hex())
                for (address, length), data in zip(ranges, snapshot.ranges, strict=True)
            ),
        )

    samples.append(await sample())
    for _ in range(steps):
        frame = await bridge.press_keys(0, frames_per_step)
        current = await sample(frame)
        previous = samples[-1]
        for range_index, (old_range, new_range) in enumerate(
            zip(previous.ranges, current.ranges, strict=True)
        ):
            for offset, (old, new) in enumerate(
                zip(
                    bytes.fromhex(old_range.bytes_hex),
                    bytes.fromhex(new_range.bytes_hex),
                    strict=True,
                )
            ):
                if old != new:
                    changes.append(
                        WatchedByteChange(
                            frame=current.frame,
                            address=old_range.address + offset,
                            before=old,
                            after=new,
                            range_index=range_index,
                        )
                    )
        samples.append(current)

    return MemoryWatch(
        schema_version=1,
        captured_at=datetime.now(UTC).isoformat(),
        tool_version=__version__,
        rom_profile=profile,
        context=context,
        samples=tuple(samples),
        changes=tuple(changes),
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


def write_memory_watch(watch: MemoryWatch, destination: Path) -> None:
    """Write a new watch JSON artifact, preserving existing files and cleaning failed writes."""
    payload = json.dumps(asdict(watch), indent=2) + "\n"
    output = destination.open("x", encoding="utf-8")
    try:
        with output:
            output.write(payload)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
