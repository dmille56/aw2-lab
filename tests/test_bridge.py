"""ROM-independent tests for the Python bridge transport."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from aw2_lab.bridge import BridgeError, BridgeInstanceMismatch, LuaBridgeClient


def mock_connection(
    monkeypatch: pytest.MonkeyPatch,
    response: dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    requests: list[dict[str, Any]] = []
    connection: list[str] = []

    class Reader:
        data = b""

        async def readline(self) -> bytes:
            return self.data

    reader = Reader()

    class Writer:
        def write(self, payload: bytes) -> None:
            request = json.loads(payload)
            requests.append(request)
            actual_response = response(request) if callable(response) else response.copy()
            if actual_response.get("id") == "$request":
                actual_response["id"] = request["id"]
            reader.data = json.dumps(actual_response).encode() + b"\n"

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            connection.append("closed")

        async def wait_closed(self) -> None:
            return None

    async def open_connection(host: str, port: int, **kwargs: object) -> tuple[Reader, Writer]:
        assert host == "127.0.0.1"
        assert port == 43128
        assert kwargs["limit"] == 4718593
        return reader, Writer()

    monkeypatch.setattr(asyncio, "open_connection", open_connection)
    return requests, connection


@pytest.mark.anyio
async def test_client_sends_versioned_request_and_returns_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests, connection = mock_connection(
        monkeypatch, {"id": "$request", "ok": True, "result": {"protocol_version": 1}}
    )
    result = await LuaBridgeClient().connect()

    assert result == {"protocol_version": 1}
    assert requests == [{"id": 1, "version": 1, "operation": "connect"}]
    assert connection == ["closed"]


@pytest.mark.anyio
async def test_client_accepts_a_handshake_from_the_emulator_it_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests, _ = mock_connection(
        monkeypatch,
        {"id": "$request", "ok": True, "result": {"protocol_version": 1, "instance": "nonce-1"}},
    )
    client = LuaBridgeClient(instance="nonce-1")
    assert await client.connect() == {"protocol_version": 1, "instance": "nonce-1"}
    assert requests == [{"id": 1, "version": 1, "operation": "connect"}]


@pytest.mark.anyio
async def test_client_rejects_a_bridge_from_another_emulator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale mGBA on the same port must not be mistaken for the one just launched."""
    mock_connection(
        monkeypatch,
        {"id": "$request", "ok": True, "result": {"protocol_version": 1}},
    )
    client = LuaBridgeClient(instance="nonce-1")
    with pytest.raises(BridgeInstanceMismatch, match="not this launcher's emulator"):
        await client.connect()

    mock_connection(
        monkeypatch,
        {"id": "$request", "ok": True, "result": {"protocol_version": 1, "instance": "other"}},
    )
    with pytest.raises(BridgeInstanceMismatch, match="observed 'other'"):
        await LuaBridgeClient(instance="nonce-1").connect()


@pytest.mark.anyio
@pytest.mark.parametrize("instance,guard", [("nonce-1", True), ("other", True), ("nonce-1", False)])
async def test_guard_verifies_restore_on_the_connection_that_receives_it(
    monkeypatch, instance, guard
):
    def reply(request):
        result = (
            {"instance": instance, "instance_guard": guard}
            if request["operation"] == "connect"
            else {"frame": 100}
        )
        return {"id": "$request", "ok": True, "result": result}

    requests, connection = mock_connection(monkeypatch, reply)
    client = LuaBridgeClient(instance="nonce-1")
    if instance == "nonce-1" and guard:
        assert await client.load_state_buffer(b"saved state") == 100
        assert [request["operation"] for request in requests] == ["connect", "load_state_buffer"]
    else:
        with pytest.raises(BridgeInstanceMismatch):
            await client.load_state_buffer(b"saved state")
        assert [request["operation"] for request in requests] == ["connect"]
    assert requests[0]["guard_next"] is True
    assert all(request["expected_instance"] == "nonce-1" for request in requests)
    assert connection == ["closed"]


@pytest.mark.anyio
async def test_client_turns_bridge_error_into_bridge_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_connection(
        monkeypatch,
        {
            "id": "$request",
            "ok": False,
            "error": {"code": "unsupported_operation", "message": "not implemented"},
        },
    )
    with pytest.raises(BridgeError, match="unsupported_operation: not implemented"):
        await LuaBridgeClient().request("unknown")


@pytest.mark.anyio
async def test_client_reports_disconnect_without_response(monkeypatch: pytest.MonkeyPatch) -> None:
    class Reader:
        async def readline(self) -> bytes:
            return b""

    class Writer:
        def write(self, payload: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    async def open_connection(*args: object, **kwargs: object) -> tuple[Reader, Writer]:
        return Reader(), Writer()

    monkeypatch.setattr(asyncio, "open_connection", open_connection)

    with pytest.raises(BridgeError, match="Lua bridge disconnected without a response"):
        await LuaBridgeClient().connect()


@pytest.mark.anyio
async def test_set_keys_returns_confirmed_mask_and_zero_releases_buttons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests, _ = mock_connection(
        monkeypatch,
        {"id": "$request", "ok": True, "result": {"keys": 0}},
    )
    client = LuaBridgeClient()

    assert await client.set_keys(0) == 0
    assert requests[0]["operation"] == "set_keys"
    assert requests[0]["keys"] == 0


@pytest.mark.anyio
async def test_press_keys_requires_exact_frame_count_and_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_connection(
        monkeypatch,
        {
            "id": "$request",
            "ok": True,
            "result": {
                "keys": 1,
                "frames": 3,
                "start_frame": 100,
                "frame": 103,
                "frames_advanced": 3,
                "released": True,
            },
        },
    )

    assert await LuaBridgeClient().press_keys(1, 3) == 103


@pytest.mark.anyio
async def test_press_keys_rejects_unconfirmed_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_connection(
        monkeypatch,
        {
            "id": "$request",
            "ok": True,
            "result": {
                "keys": 1,
                "start_frame": 10,
                "frame": 11,
                "frames_advanced": 1,
                "released": False,
            },
        },
    )
    with pytest.raises(BridgeError, match="final release"):
        await LuaBridgeClient().press_keys(1, 1)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("frame", "taps", "stop", "released", "valid"),
    [
        (118, 2, "complete", True, True),
        (117, 1, "cursor", True, True),
        (109, 1, "phase", True, True),
        (118, 1, "complete", True, False),
        (110, 1, "cursor", True, False),
        (118, 2, "complete", False, False),
    ],
)
async def test_map_cursor_batch_requires_consistent_frames_and_release(
    monkeypatch, frame, taps, stop, released, valid
) -> None:
    requests, _ = mock_connection(
        monkeypatch,
        {
            "id": "$request",
            "ok": True,
            "result": {"frame": frame, "taps": taps, "stop": stop, "released": released},
        },
    )
    bridge = LuaBridgeClient()
    if valid:
        result = await bridge.move_map_cursor_batch(
            16, start_frame=100, start=(1, 0), steps=2, gap=8
        )
        assert (result.frame, result.taps, result.stop) == (frame, taps, stop)
    else:
        with pytest.raises(BridgeError, match="map cursor batch"):
            await bridge.move_map_cursor_batch(16, start_frame=100, start=(1, 0), steps=2, gap=8)

    assert requests[0] == {
        "id": 1,
        "version": 1,
        "operation": "move_map_cursor_batch",
        "keys": 16,
        "start_frame": 100,
        "x": 1,
        "y": 0,
        "steps": 2,
        "gap": 8,
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("sample_frame", "matches", "accepted"),
    [
        (123, True, True),
        (124, True, False),
        (123, False, False),
    ],
)
async def test_cursor_probe_requires_a_same_frame_match(
    monkeypatch, sample_frame, matches, accepted
) -> None:
    requests, _ = mock_connection(
        monkeypatch,
        {"id": "$request", "ok": True, "result": {"frame": sample_frame, "matches": matches}},
    )
    client = LuaBridgeClient()
    assert (
        await client.verify_map_cursor(
            frame=123, position=(3, 6), width=16, height=15, player=1, day=1
        )
        is accepted
    )
    assert requests[0]["operation"] == "verify_map_cursor"


@pytest.mark.anyio
async def test_input_methods_reject_invalid_masks_and_frame_counts() -> None:
    client = LuaBridgeClient()
    with pytest.raises(ValueError, match="10-bit mask"):
        await client.set_keys(1024)
    with pytest.raises(ValueError, match="frames"):
        await client.press_keys(1, 0)


@pytest.mark.anyio
@pytest.mark.parametrize("malformed", [None, "frame", "base64", "length"])
async def test_read_battle_ram_checks_frame_and_complete_regions(monkeypatch, malformed) -> None:
    ewram = bytes(range(256)) * 1024
    iwram = bytes(reversed(range(256))) * 128
    result = {
        "frame": 123,
        "ewram_base64": base64.b64encode(ewram).decode("ascii"),
        "iwram_base64": base64.b64encode(iwram).decode("ascii"),
    }
    if malformed == "frame":
        result["frame"] = True
    elif malformed == "base64":
        result["ewram_base64"] = "!" + result["ewram_base64"][1:]
    elif malformed == "length":
        result["iwram_base64"] = base64.b64encode(iwram[:-1]).decode("ascii")

    requests, _ = mock_connection(monkeypatch, {"id": "$request", "ok": True, "result": result})
    bridge = LuaBridgeClient()
    if malformed is None:
        sample = await bridge.read_battle_ram()
        assert sample.frame == 123
        assert sample.ranges == (ewram, iwram)
    else:
        with pytest.raises(BridgeError, match="battle RAM"):
            await bridge.read_battle_ram()
    assert [request["operation"] for request in requests] == ["read_battle_ram"]


@pytest.mark.anyio
async def test_read_memory_batch_returns_each_range_from_one_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests, _ = mock_connection(
        monkeypatch,
        {
            "id": "$request",
            "ok": True,
            "result": {
                "ranges": [
                    {"address": 0x02000000, "bytes": [1, 2]},
                    {"address": 0x03000000, "bytes": [3]},
                ]
            },
        },
    )

    result = await LuaBridgeClient().read_memory_batch([(0x02000000, 2), (0x03000000, 1)])

    assert result == [b"\x01\x02", b"\x03"]
    assert requests[0]["operation"] == "read_memory_batch"


@pytest.mark.anyio
async def test_read_memory_batch_rejects_invalid_ranges() -> None:
    client = LuaBridgeClient()
    for ranges in (
        [],
        [(True, 1)],
        [(0, 4097)],
        [(0xFFFFFFFF, 2)],
        [(0, 4096), (1, 1)],
        [(0, 0)] * 65,
    ):
        with pytest.raises(ValueError):
            await client.read_memory_batch(ranges)


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["save_state", "load_state"])
async def test_state_operations_return_the_frame(
    monkeypatch: pytest.MonkeyPatch, operation: str, tmp_path: Path
) -> None:
    requests, _ = mock_connection(
        monkeypatch, {"id": "$request", "ok": True, "result": {"frame": 456}}
    )
    client = LuaBridgeClient()

    result = await getattr(client, operation)(tmp_path / "checkpoint.ss0")

    assert result == 456
    assert requests[0]["operation"] == operation
    assert requests[0]["filename"] == str(tmp_path / "checkpoint.ss0")


@pytest.mark.anyio
async def test_save_state_buffer_decodes_binary_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    state = b"state\x00buffer\xff"
    requests, _ = mock_connection(
        monkeypatch,
        {
            "id": "$request",
            "ok": True,
            "result": {"state_base64": base64.b64encode(state).decode("ascii"), "frame": 456},
        },
    )

    assert await LuaBridgeClient().save_state_buffer() == state
    assert requests[0]["operation"] == "save_state_buffer"


@pytest.mark.anyio
async def test_load_state_buffer_encodes_binary_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    state = b"state\x00buffer\xff"
    requests, _ = mock_connection(
        monkeypatch, {"id": "$request", "ok": True, "result": {"frame": 456}}
    )

    assert await LuaBridgeClient().load_state_buffer(state) == 456
    assert requests[0]["operation"] == "load_state_buffer"
    assert requests[0]["state_base64"] == base64.b64encode(state).decode("ascii")


@pytest.mark.anyio
async def test_load_state_buffer_rejects_empty_and_oversized_data() -> None:
    client = LuaBridgeClient()
    for state in (b"", b"x" * (3 * 1024 * 1024 + 1)):
        with pytest.raises(ValueError, match="state"):
            await client.load_state_buffer(state)


@pytest.mark.anyio
async def test_save_state_buffer_rejects_invalid_base64(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_connection(
        monkeypatch,
        {"id": "$request", "ok": True, "result": {"state_base64": "%%%"}},
    )

    with pytest.raises(BridgeError, match="invalid state buffer"):
        await LuaBridgeClient().save_state_buffer()


@pytest.mark.anyio
async def test_reset_returns_the_new_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    requests, _ = mock_connection(
        monkeypatch, {"id": "$request", "ok": True, "result": {"frame": 0}}
    )

    assert await LuaBridgeClient().reset() == 0
    assert requests[0]["operation"] == "reset"


@pytest.mark.anyio
async def test_client_rejects_response_for_another_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_connection(monkeypatch, {"id": 999, "ok": True, "result": {}})
    with pytest.raises(BridgeError, match="ID did not match"):
        await LuaBridgeClient().connect()


@pytest.mark.anyio
async def test_client_rejects_oversized_request_before_connecting() -> None:
    client = LuaBridgeClient(max_message_bytes=32)

    with pytest.raises(BridgeError, match="request exceeds"):
        await client.request("operation", value="x" * 100)


@pytest.mark.anyio
async def test_screenshot_returns_png_bytes_from_bridge_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    png = b"\x89PNG\r\n\x1a\nimage"
    encoded_png = base64.b64encode(png).decode("ascii")

    class Reader:
        async def readline(self) -> bytes:
            return self.data

    reader = Reader()

    class Writer:
        def write(self, payload: bytes) -> None:
            request = json.loads(payload)
            reader.data = (
                json.dumps(
                    {
                        "id": request["id"],
                        "ok": True,
                        "result": {"png_base64": encoded_png},
                    }
                ).encode()
                + b"\n"
            )

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    async def open_connection(host: str, port: int, **kwargs: object) -> tuple[Reader, Writer]:
        return reader, Writer()

    monkeypatch.setattr(asyncio, "open_connection", open_connection)
    client = LuaBridgeClient()
    assert await client.screenshot() == png

    destination = tmp_path / "capture.png"
    assert await client.save_screenshot(destination) == destination
    assert destination.read_bytes() == png
