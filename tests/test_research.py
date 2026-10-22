import json
from dataclasses import replace
from pathlib import Path
from typing import Self
from unittest.mock import AsyncMock

import pytest
from test_bridge import mock_connection

from aw2_lab import research
from aw2_lab.bridge import BridgeError, LuaBridgeClient
from aw2_lab.emulator import EmulatorMode
from aw2_lab.research import (
    DumpRange,
    MemoryDump,
    ResearchContext,
    capture_memory_dump,
    compare_memory_dumps,
    format_memory_diff,
    format_memory_watch,
    read_memory_dump,
    watch_memory,
    write_memory_dump,
)
from aw2_lab.rom_profile import AW2_US_REVISION_0, UnsupportedRomError


@pytest.fixture
def context() -> ResearchContext:
    return ResearchContext(EmulatorMode.HEADLESS, "pinned build", "initial boot", "No inputs")


@pytest.mark.anyio
async def test_capture_round_trip_and_exclusive_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, context: ResearchContext
) -> None:
    monkeypatch.setattr(research, "select_rom_profile", lambda _: AW2_US_REVISION_0)
    requests, _ = mock_connection(
        monkeypatch,
        {
            "id": "$request",
            "ok": True,
            "result": {
                "frame": 42,
                "ranges": [
                    {"address": 0x03000000, "bytes": [0, 255]},
                    {"address": 0x02000000, "bytes": [128]},
                ],
            },
        },
    )
    dump = await capture_memory_dump(
        LuaBridgeClient(),
        rom_path=Path("unused.gba"),
        ranges=[(0x03000000, 2), (0x02000000, 1)],
        context=context,
    )
    assert len(requests) == 1
    assert requests[0]["operation"] == "read_memory_batch"
    output = tmp_path / "dump.json"
    write_memory_dump(dump, output)
    encoded = output.read_text()
    data = json.loads(encoded)
    assert data["frame"] == 42
    assert data["schema_version"] == 1
    assert data["captured_at"].endswith("+00:00")
    assert data["rom_profile"]["sha256"] == AW2_US_REVISION_0.sha256
    assert data["context"]["emulator_build"] == "pinned build"
    assert [r["address"] for r in data["ranges"]] == [0x03000000, 0x02000000]
    assert [bytes.fromhex(r["bytes_hex"]) for r in data["ranges"]] == [b"\0\xff", b"\x80"]
    with pytest.raises(FileExistsError):
        write_memory_dump(dump, output)
    assert output.read_text() == encoded


@pytest.mark.anyio
async def test_rejected_rom_never_contacts_bridge(
    monkeypatch: pytest.MonkeyPatch, context: ResearchContext
) -> None:
    def reject(_: Path) -> None:
        raise UnsupportedRomError("unsupported checksum")

    monkeypatch.setattr(research, "select_rom_profile", reject)
    bridge = LuaBridgeClient()
    request = AsyncMock()
    monkeypatch.setattr(bridge, "request", request)
    with pytest.raises(UnsupportedRomError):
        await capture_memory_dump(bridge, rom_path=Path("unused"), ranges=[(0, 1)], context=context)
    request.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize("frame", [None, True, -1, 1 << 32, "42"])
async def test_snapshot_rejects_invalid_frame(
    monkeypatch: pytest.MonkeyPatch, frame: object
) -> None:
    mock_connection(
        monkeypatch,
        {
            "id": "$request",
            "ok": True,
            "result": {
                "frame": frame,
                "ranges": [{"address": 0, "bytes": [1]}],
            },
        },
    )
    with pytest.raises(BridgeError, match="frame"):
        await LuaBridgeClient().read_memory_snapshot([(0, 1)])


@pytest.mark.anyio
@pytest.mark.parametrize(
    "item",
    [
        {"address": 1, "bytes": [1]},
        {"address": False, "bytes": [1]},
        {"address": 0, "bytes": [True]},
        {"address": 0, "bytes": []},
        {"address": 0, "bytes": [256]},
    ],
)
async def test_snapshot_rejects_malformed_ranges(
    monkeypatch: pytest.MonkeyPatch, item: object
) -> None:
    mock_connection(
        monkeypatch,
        {
            "id": "$request",
            "ok": True,
            "result": {
                "frame": 42,
                "ranges": [item],
            },
        },
    )
    with pytest.raises(BridgeError):
        await LuaBridgeClient().read_memory_snapshot([(0, 1)])


@pytest.mark.anyio
async def test_partial_output_is_removed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, context: ResearchContext
) -> None:
    from aw2_lab.bridge import MemorySnapshot

    monkeypatch.setattr(research, "select_rom_profile", lambda _: AW2_US_REVISION_0)
    bridge = LuaBridgeClient()
    monkeypatch.setattr(
        bridge, "read_memory_snapshot", AsyncMock(return_value=MemorySnapshot(1, (b"x",)))
    )
    dump = await capture_memory_dump(
        bridge, rom_path=Path("unused"), ranges=[(0, 1)], context=context
    )
    original_open = Path.open

    class FailingWriter:
        def __init__(self, path: Path) -> None:
            self.file = original_open(path, "x", encoding="utf-8")

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            self.file.close()

        def write(self, payload: str) -> None:
            self.file.write(payload[:10])
            raise OSError("disk full")

    monkeypatch.setattr(Path, "open", lambda path, *args, **kwargs: FailingWriter(path))
    output = tmp_path / "dump.json"
    with pytest.raises(OSError, match="disk full"):
        write_memory_dump(dump, output)
    assert not output.exists()


@pytest.mark.anyio
async def test_blank_context_is_rejected_before_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = LuaBridgeClient()
    request = AsyncMock()
    monkeypatch.setattr(bridge, "request", request)
    with pytest.raises(ValueError, match="checkpoint"):
        await capture_memory_dump(
            bridge,
            rom_path=Path("unused"),
            ranges=[(0, 1)],
            context=ResearchContext(EmulatorMode.HEADLESS, "build", "   ", "No inputs"),
        )
    request.assert_not_called()


@pytest.mark.anyio
async def test_watch_samples_initial_and_explicit_steps(
    monkeypatch: pytest.MonkeyPatch, context: ResearchContext
) -> None:
    from aw2_lab.bridge import MemorySnapshot

    monkeypatch.setattr(research, "select_rom_profile", lambda _: AW2_US_REVISION_0)
    bridge = LuaBridgeClient()
    snapshots = iter(
        [
            MemorySnapshot(10, (b"\x00\x01",)),
            MemorySnapshot(12, (b"\x02\x01",)),
            MemorySnapshot(14, (b"\x02\x03",)),
        ]
    )
    read = AsyncMock(side_effect=lambda _: next(snapshots))
    press = AsyncMock(side_effect=[12, 14])
    monkeypatch.setattr(bridge, "read_memory_snapshot", read)
    monkeypatch.setattr(bridge, "press_keys", press)

    watch = await watch_memory(
        bridge,
        rom_path=Path("unused.gba"),
        ranges=[(0x02000000, 2)],
        context=context,
        steps=2,
        frames_per_step=2,
    )

    assert [sample.frame for sample in watch.samples] == [10, 12, 14]
    assert [sample.ranges[0].bytes_hex for sample in watch.samples] == ["0001", "0201", "0203"]
    assert [
        (change.frame, change.address, change.before, change.after) for change in watch.changes
    ] == [
        (12, 0x02000000, 0, 2),
        (14, 0x02000001, 1, 3),
    ]
    assert [call.args for call in press.await_args_list] == [(0, 2), (0, 2)]
    assert read.await_count == 3
    assert "Changed bytes: 2" in format_memory_watch(watch)


@pytest.mark.anyio
async def test_watch_rejects_unrequested_frame_advance(
    monkeypatch: pytest.MonkeyPatch, context: ResearchContext
) -> None:
    from aw2_lab.bridge import MemorySnapshot

    monkeypatch.setattr(research, "select_rom_profile", lambda _: AW2_US_REVISION_0)
    bridge = LuaBridgeClient()
    monkeypatch.setattr(
        bridge,
        "read_memory_snapshot",
        AsyncMock(side_effect=[MemorySnapshot(10, (b"\x00",)), MemorySnapshot(12, (b"\x01",))]),
    )
    monkeypatch.setattr(bridge, "press_keys", AsyncMock(return_value=11))

    with pytest.raises(ValueError, match="changed unexpectedly"):
        await watch_memory(
            bridge,
            rom_path=Path("unused.gba"),
            ranges=[(0x02000000, 1)],
            context=context,
            steps=1,
            frames_per_step=1,
        )


@pytest.mark.anyio
async def test_snapshot_preserves_overlaps_and_empty_ranges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_connection(
        monkeypatch,
        {
            "id": "$request",
            "ok": True,
            "result": {
                "frame": 42,
                "ranges": [
                    {"address": 32, "bytes": [1, 2]},
                    {"address": 33, "bytes": [2]},
                    {"address": 32, "bytes": []},
                ],
            },
        },
    )
    snapshot = await LuaBridgeClient().read_memory_snapshot([(32, 2), (33, 1), (32, 0)])
    assert snapshot.ranges == (b"\x01\x02", b"\x02", b"")


def _memory_dump(
    context: ResearchContext,
    *,
    frame: int = 1,
    ranges: tuple[DumpRange, ...] | None = None,
) -> MemoryDump:
    return MemoryDump(
        schema_version=1,
        captured_at="2026-10-21T00:00:00+00:00",
        tool_version="test",
        rom_profile=AW2_US_REVISION_0,
        context=context,
        frame=frame,
        ranges=ranges or (DumpRange(0x02000000, 3, "000102"),),
    )


def test_memory_diff_reports_changed_values_and_range_context(
    context: ResearchContext,
) -> None:
    before = _memory_dump(
        context,
        ranges=(DumpRange(0x02000000, 3, "000102"), DumpRange(0x03000000, 2, "AABB")),
    )
    after = _memory_dump(
        replace(context, checkpoint="after event", reproduction="Capture unit"),
        frame=4,
        ranges=(DumpRange(0x02000000, 3, "000A02"), DumpRange(0x03000000, 2, "AACC")),
    )
    diff = compare_memory_dumps(before, after)

    assert len(diff.changes) == 2
    assert diff.changes[0].address == 0x02000001
    assert (diff.changes[0].before, diff.changes[0].after) == (1, 10)
    assert (diff.changes[0].range_index, diff.changes[0].range_address) == (0, 0x02000000)
    assert diff.changes[1].address == 0x03000001
    assert (diff.changes[1].range_index, diff.changes[1].range_address) == (1, 0x03000000)
    output = format_memory_diff(diff)
    assert "Before: frame 1" in output
    assert "After:  frame 4" in output
    assert "0x02000001  0x01    0x0A    #1 0x02000000:0x3" in output
    assert "0x03000001  0xBB    0xCC    #2 0x03000000:0x2" in output


def test_memory_diff_reports_zero_changes(context: ResearchContext) -> None:
    dump = _memory_dump(context)
    assert format_memory_diff(compare_memory_dumps(dump, dump)).endswith("Changed bytes: 0")


def test_memory_diff_requires_matching_rom_and_ordered_ranges(
    context: ResearchContext,
) -> None:
    before = _memory_dump(context)
    different_rom = replace(
        before,
        rom_profile=replace(before.rom_profile, name="other"),
    )
    with pytest.raises(ValueError, match="different ROM profiles"):
        compare_memory_dumps(before, different_rom)

    different_ranges = _memory_dump(context, ranges=(DumpRange(0x02000001, 3, "000102"),))
    with pytest.raises(ValueError, match="identical ranges"):
        compare_memory_dumps(before, different_ranges)


def test_read_memory_dump_loads_schema_version_1(tmp_path: Path, context: ResearchContext) -> None:
    dump = _memory_dump(context)
    output = tmp_path / "dump.json"
    write_memory_dump(dump, output)
    assert read_memory_dump(output) == dump


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda data: data.update(schema_version=2), "unsupported dump schema"),
        (lambda data: data.update(schema_version=1.0), "unsupported dump schema"),
        (lambda data: data.update(frame=True), "frame must be"),
        (lambda data: data["ranges"][0].update(bytes_hex="xyz"), "valid hexadecimal"),
        (lambda data: data["ranges"][0].update(length=4), "does not match"),
    ],
)
def test_read_memory_dump_rejects_invalid_artifacts(
    tmp_path: Path,
    context: ResearchContext,
    mutation: object,
    message: str,
) -> None:
    output = tmp_path / "dump.json"
    write_memory_dump(_memory_dump(context), output)
    data = json.loads(output.read_text())
    mutation(data)  # type: ignore[operator]
    output.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=message):
        read_memory_dump(output)
