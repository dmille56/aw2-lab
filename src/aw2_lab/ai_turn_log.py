"""Read a private Pi event log as it grows and render bounded terminal output."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

LogMode = Literal["summary", "details"]
_MAX_RECORD = 1024 * 1024
_DISPLAY_LIMIT = 1200


def _display(text: str, token: str, limit: int = _DISPLAY_LIMIT) -> str:
    if token:
        text = text.replace(token, "[redacted]")
    clean = "".join(
        " " if char.isspace() else char
        for char in text[: limit + 1]
        if char.isprintable() or char.isspace()
    )
    return clean[:limit] + ("…" if len(text) > limit else "")


def render_pi_event(line: bytes, mode: LogMode, *, token: str = "") -> Iterator[str]:
    """Use final message blocks instead of repeated streaming deltas."""
    try:
        event = json.loads(line)
    except ValueError, RecursionError:
        return
    if not isinstance(event, dict):
        return
    kind = event.get("type")
    if kind in ("tool_execution_start", "tool_execution_end"):
        name = event.get("toolName")
        if not isinstance(name, str):
            return
        label = _display(name.removeprefix("mcp__aw2__").replace("_", " "), token, 100)
        if kind == "tool_execution_start":
            yield f"Calling {label}"
            if mode == "details" and "args" in event:
                yield "  Arguments: " + _display(
                    json.dumps(event["args"], ensure_ascii=False), token
                )
            return
        result = event.get("result")
        structured = result.get("structuredContent") if isinstance(result, dict) else None
        # Pi wraps the MCP response in its own tool result.
        body = (
            structured.get("structuredContent", structured)
            if isinstance(structured, dict)
            else None
        )
        error = event.get("isError") is True or (
            isinstance(structured, dict) and structured.get("isError") is True
        )
        status = body.get("status") if isinstance(body, dict) else None
        suffix = (
            f" ({_display(status.replace('_', ' '), token, 60)})" if isinstance(status, str) else ""
        )
        yield f"{label.capitalize()} {'failed' if error else 'returned'}{suffix}"
        if mode == "details" and result is not None:
            detail = (
                body if body is not None else (structured if structured is not None else result)
            )
            yield "  Result: " + _display(json.dumps(detail, ensure_ascii=False), token)
    elif mode == "details" and kind == "message_end":
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "thinking":
                    thinking = block.get("thinking")
                    if isinstance(thinking, str) and thinking.strip():
                        yield "Thinking: " + _display(thinking, token)


async def _follow(
    path: Path, offset: int, ended: asyncio.Event, mode: LogMode, prefix: str, token: str
) -> None:
    try:
        with path.open("rb") as stream:
            stream.seek(offset)
            discarding = False
            while True:
                start = stream.tell()
                line = stream.readline(_MAX_RECORD + 1)
                if not line:
                    if ended.is_set():
                        return
                    await asyncio.sleep(0.1)
                    continue
                complete = line.endswith(b"\n")
                if discarding or len(line) > _MAX_RECORD:
                    discarding = not complete
                elif complete or ended.is_set():
                    for item in render_pi_event(line, mode, token=token):
                        print(f"{prefix} {item}", flush=True)
                else:
                    stream.seek(start)
                    await asyncio.sleep(0.1)
                    continue
                # A large backlog must not delay the launcher or match API.
                await asyncio.sleep(0)
    except OSError:
        print(f"{prefix} Live log unavailable. Private log: {path}", flush=True)


@asynccontextmanager
async def follow_ai_log(
    path: Path, *, offset: int, mode: LogMode | None, prefix: str, token: str
) -> AsyncIterator[None]:
    if mode is None:
        yield
        return
    ended = asyncio.Event()
    task = asyncio.create_task(_follow(path, offset, ended, mode, prefix, token))
    try:
        yield
    finally:
        ended.set()
        await task
