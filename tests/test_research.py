import json
from pathlib import Path
from typing import Self
from unittest.mock import AsyncMock

import pytest
from test_bridge import mock_connection

from aw2_lab import research
from aw2_lab.bridge import BridgeError, LuaBridgeClient
from aw2_lab.emulator import EmulatorMode
from aw2_lab.research import ResearchContext, capture_memory_dump, write_memory_dump
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
