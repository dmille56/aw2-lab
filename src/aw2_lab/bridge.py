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

    async def request(self, operation: str, **parameters: Any) -> dict[str, Any]:
        """Send a request and return its result, raising BridgeError on failure."""
        request_id = next(self._ids)
        request = {"id": request_id, "version": 1, "operation": operation, **parameters}
        payload = json.dumps(request, separators=(",", ":")).encode("utf-8") + b"\n"
        if len(payload) > self.max_message_bytes:
            raise BridgeError("Bridge request exceeds the configured message limit")

        async with self._lock:
            try:
                async with asyncio.timeout(self.timeout):
                    reader, writer = await asyncio.open_connection(self.host, self.port)
                    writer.write(payload)
                    await writer.drain()
                    response_line = await reader.readline()
                    writer.close()
                    await writer.wait_closed()
            except (OSError, TimeoutError) as error:
                raise BridgeError(f"Could not complete Lua bridge request: {error}") from error

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
