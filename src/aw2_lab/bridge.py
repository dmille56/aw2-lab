"""Async client for the local mGBA Lua bridge."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import tempfile
from itertools import count
from pathlib import Path
from typing import Any

_MAX_STATE_BYTES = 3 * 1024 * 1024


class BridgeError(ConnectionError):
    """Raised when the Lua bridge is unavailable or rejects a request."""


class LuaBridgeClient:
    """Send one newline-delimited JSON request at a time to the Lua bridge."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 43128,
        timeout: float = 5.0,
        max_message_bytes: int = 4718592,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.max_message_bytes = max_message_bytes
        self._ids = count(1)
        self._lock = asyncio.Lock()

    async def request(
        self,
        operation: str,
        *,
        timeout: float | None = None,
        **parameters: Any,
    ) -> dict[str, Any]:
        """Send a request and return its result, raising BridgeError on failure."""
        request_id = next(self._ids)
        request = {"id": request_id, "version": 1, "operation": operation, **parameters}
        payload = json.dumps(request, separators=(",", ":")).encode("utf-8") + b"\n"
        if len(payload) > self.max_message_bytes:
            raise BridgeError("Bridge request exceeds the configured message limit")

        async with self._lock:
            writer: asyncio.StreamWriter | None = None
            try:
                async with asyncio.timeout(self.timeout if timeout is None else timeout):
                    reader, writer = await asyncio.open_connection(
                        self.host, self.port, limit=self.max_message_bytes + 1
                    )
                    writer.write(payload)
                    await writer.drain()
                    response_line = await reader.readline()
            except (OSError, TimeoutError) as error:
                if writer is not None:
                    writer.close()
                raise BridgeError(
                    f"Could not complete Lua bridge request ({type(error).__name__}): {error}"
                ) from error
            else:
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass

        if not response_line:
            raise BridgeError("Lua bridge disconnected without a response")
        if len(response_line) > self.max_message_bytes or not response_line.endswith(b"\n"):
            raise BridgeError("Lua bridge response is oversized or not newline terminated")
        try:
            response = json.loads(response_line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BridgeError("Lua bridge returned invalid JSON") from error
        if response.get("id") != request_id:
            raise BridgeError("Lua bridge response ID did not match the request")
        if not response.get("ok"):
            bridge_error = response.get("error", {})
            raise BridgeError(
                f"{bridge_error.get('code', 'bridge_error')}: {bridge_error.get('message', '')}"
            )
        result = response.get("result")
        if not isinstance(result, dict):
            raise BridgeError("Lua bridge returned a malformed result")
        return result

    async def connect(self) -> dict[str, Any]:
        """Return protocol and capability information from the bridge."""
        return await self.request("connect")

    async def read_memory_batch(self, ranges: list[tuple[int, int]]) -> list[bytes]:
        """Read up to 64 address/length ranges at one paused frame boundary."""
        if not 1 <= len(ranges) <= 64:
            raise ValueError("ranges must contain between 1 and 64 entries")
        total = 0
        encoded_ranges: list[dict[str, int]] = []
        for address, length in ranges:
            if (
                isinstance(address, bool)
                or not isinstance(address, int)
                or not 0 <= address <= 0xFFFFFFFF
            ):
                raise ValueError("addresses must be unsigned 32-bit integers")
            if isinstance(length, bool) or not isinstance(length, int) or not 0 <= length <= 4096:
                raise ValueError("range lengths must be integers from 0 to 4096")
            if address + length > 0x100000000:
                raise ValueError("memory range exceeds the 32-bit address space")
            total += length
            encoded_ranges.append({"address": address, "length": length})
        if total > 4096:
            raise ValueError("combined memory read exceeds 4096 bytes")
        result = await self.request("read_memory_batch", ranges=encoded_ranges)
        returned = result.get("ranges")
        if not isinstance(returned, list) or len(returned) != len(ranges):
            raise BridgeError("Lua bridge returned an invalid batched memory read")
        decoded: list[bytes] = []
        for requested, item in zip(ranges, returned, strict=True):
            if not isinstance(item, dict) or item.get("address") != requested[0]:
                raise BridgeError("Lua bridge returned an invalid batched memory range")
            values = item.get("bytes")
            if (
                not isinstance(values, list)
                or len(values) != requested[1]
                or any(
                    isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255
                    for value in values
                )
            ):
                raise BridgeError("Lua bridge returned invalid bytes in a batched memory read")
            decoded.append(bytes(values))
        return decoded

    @staticmethod
    def _validate_state_path(path: str | Path) -> str:
        value = str(path)
        if not value or len(value) > 4096:
            raise ValueError("state path must contain between 1 and 4096 characters")
        return value

    async def save_state(self, path: str | Path) -> int:
        """Save emulator state, including save RAM, and return its frame."""
        result = await self.request("save_state", filename=self._validate_state_path(path))
        frame = result.get("frame")
        if isinstance(frame, bool) or not isinstance(frame, int):
            raise BridgeError("Lua bridge returned an invalid saved-state frame")
        return frame

    async def load_state(self, path: str | Path) -> int:
        """Restore emulator state, including save RAM, and return its frame."""
        result = await self.request("load_state", filename=self._validate_state_path(path))
        frame = result.get("frame")
        if isinstance(frame, bool) or not isinstance(frame, int):
            raise BridgeError("Lua bridge returned an invalid restored-state frame")
        return frame

    async def save_state_buffer(self) -> bytes:
        """Save emulator state, including save RAM, and return it as bytes."""
        result = await self.request("save_state_buffer")
        try:
            encoded = result["state_base64"]
            if not isinstance(encoded, str):
                raise TypeError("state_base64 must be a string")
            state = base64.b64decode(encoded, validate=True)
            if not state or len(state) > _MAX_STATE_BYTES:
                raise ValueError("state buffer is empty or exceeds the size limit")
        except (KeyError, TypeError, binascii.Error, ValueError) as error:
            raise BridgeError(f"Lua bridge returned an invalid state buffer: {error}") from error
        return state

    async def load_state_buffer(self, state: bytes) -> int:
        """Restore emulator state from bytes and return the restored frame."""
        if not isinstance(state, bytes) or not state:
            raise ValueError("state must be a non-empty bytes object")
        if len(state) > _MAX_STATE_BYTES:
            raise ValueError("state buffer exceeds the 3 MiB size limit")
        encoded = base64.b64encode(state).decode("ascii")
        result = await self.request("load_state_buffer", state_base64=encoded)
        frame = result.get("frame")
        if isinstance(frame, bool) or not isinstance(frame, int):
            raise BridgeError("Lua bridge returned an invalid restored-state frame")
        return frame

    async def reset(self) -> int:
        """Reset the emulated system, release all keys, and return its frame."""
        result = await self.request("reset")
        frame = result.get("frame")
        if isinstance(frame, bool) or not isinstance(frame, int):
            raise BridgeError("Lua bridge returned an invalid reset frame")
        return frame

    async def set_keys(self, keys: int) -> int:
        """Set the active GBA key mask; pass zero to release every button."""
        self._validate_key_mask(keys)
        result = await self.request("set_keys", keys=keys)
        actual = result.get("keys")
        if isinstance(actual, bool) or not isinstance(actual, int) or actual != keys:
            raise BridgeError(f"Lua bridge did not apply key mask {keys}: {actual!r}")
        return actual

    async def press_keys(self, keys: int, frames: int) -> int:
        """Hold a GBA key mask for exactly ``frames`` frames, then release all keys."""
        self._validate_key_mask(keys)
        if isinstance(frames, bool) or not isinstance(frames, int) or not 1 <= frames <= 600:
            raise ValueError("frames must be an integer from 1 to 600")
        result = await self.request(
            "press_keys",
            keys=keys,
            frames=frames,
            timeout=self.timeout + frames / 60,
        )
        try:
            start_frame = result["start_frame"]
            end_frame = result["frame"]
            reported_frames = result["frames_advanced"]
            if any(
                isinstance(value, bool) or not isinstance(value, int)
                for value in (start_frame, end_frame, reported_frames)
            ):
                raise TypeError("frame values must be integers")
            actual_frames = (int(end_frame) - int(start_frame)) % (1 << 32)
            if reported_frames != frames or actual_frames != frames:
                raise ValueError(f"requested {frames} frames but bridge reported {actual_frames}")
            if result.get("keys") != keys or result.get("released") is not True:
                raise ValueError("bridge did not confirm the requested keys and final release")
        except (KeyError, TypeError, ValueError) as error:
            raise BridgeError(f"Lua bridge returned an invalid key press: {error}") from error
        return int(end_frame)

    @staticmethod
    def _validate_key_mask(keys: int) -> None:
        if isinstance(keys, bool) or not isinstance(keys, int) or not 0 <= keys <= 1023:
            raise ValueError("keys must be an integer 10-bit mask")

    async def advance_frames(self, frames: int) -> int:
        """Advance exactly ``frames`` frames and return the ending frame number."""
        if isinstance(frames, bool) or not isinstance(frames, int) or not 0 <= frames <= 600:
            raise ValueError("frames must be an integer from 0 to 600")
        result = await self.request(
            "advance_frames",
            frames=frames,
            timeout=self.timeout + frames / 60,
        )
        try:
            start_frame = result["start_frame"]
            end_frame = result["frame"]
            reported_frames = result["frames_advanced"]
            if (
                isinstance(start_frame, bool)
                or not isinstance(start_frame, int)
                or isinstance(end_frame, bool)
                or not isinstance(end_frame, int)
                or isinstance(reported_frames, bool)
                or not isinstance(reported_frames, int)
            ):
                raise TypeError("frame values must be integers")
            actual_frames = (end_frame - start_frame) % (1 << 32)
            if reported_frames != frames or actual_frames != frames:
                raise ValueError(f"requested {frames} frames but bridge reported {actual_frames}")
        except (KeyError, TypeError, ValueError) as error:
            raise BridgeError(f"Lua bridge returned an invalid frame advance: {error}") from error
        return end_frame

    async def screenshot(self) -> bytes:
        """Capture the current emulator display and return its PNG bytes."""
        with tempfile.TemporaryDirectory(prefix="aw2-lab-screenshot-") as directory:
            path = Path(directory) / "screenshot.png"
            result = await self.request("screenshot", filename=str(path))
            try:
                encoded = result["png_base64"]
                if not isinstance(encoded, str):
                    raise TypeError("png_base64 must be a string")
                image = base64.b64decode(encoded, validate=True)
            except (KeyError, TypeError, binascii.Error, ValueError) as error:
                raise BridgeError(f"Lua bridge returned an invalid screenshot: {error}") from error
            if not image.startswith(b"\x89PNG\r\n\x1a\n"):
                raise BridgeError("Lua bridge screenshot is not a PNG image")
            return image

    async def save_screenshot(self, path: str | Path) -> Path:
        """Capture the current display and save the PNG to a local file."""
        destination = Path(path)
        destination.write_bytes(await self.screenshot())
        return destination
