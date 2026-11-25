"""Read a private Pi event log as it grows and render bounded terminal output."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any, Literal

LogMode = Literal["summary", "details"]
_MAX_RECORD = 1024 * 1024
_DISPLAY_LIMIT = 1200
_PLAYER_COLORS = {1: 91, 2: 94, 3: 92, 4: 93}


def color_ai_log_prefix(prefix: str, player_slot: int) -> str:
    """Color the label only when stdout supports terminal styling."""
    color = _PLAYER_COLORS.get(player_slot)
    if (
        color is None
        or not sys.stdout.isatty()
        or "NO_COLOR" in os.environ
        or os.environ.get("TERM") == "dumb"
    ):
        return prefix
    return f"\x1b[{color}m{prefix}\x1b[0m"


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
    event = _decode_event(line)
    if event is not None:
        yield from _render_event(event, mode, token)


def _decode_event(line: bytes) -> dict[str, Any] | None:
    try:
        event = json.loads(line)
    except ValueError, RecursionError:
        return None
    return event if isinstance(event, dict) else None


def _render_event(event: dict[str, Any], mode: LogMode, token: str) -> Iterator[str]:
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
        if (
            status is None
            and isinstance(body, dict)
            and isinstance(command := body.get("command"), dict)
        ):
            status = command.get("status")
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


@dataclass
class TurnTiming:
    tools: float = 0
    thinking: float = 0


@contextmanager
def time_ai_turn(mode: LogMode | None, prefix: str) -> Iterator[TurnTiming | None]:
    if mode is None:
        yield None
        return
    started = monotonic()
    timing = TurnTiming()
    try:
        yield timing
    finally:
        elapsed = monotonic() - started
        print(
            f"{prefix} Timing: total {elapsed:.2f}s, "
            f"tools {timing.tools:.2f}s, thinking {timing.thinking:.2f}s",
            flush=True,
        )


class _AttemptLog:
    def __init__(self, mode: LogMode, token: str, timing: TurnTiming) -> None:
        self.mode = mode
        self.token = token
        self.timing = timing
        self.tools: defaultdict[str, deque[float]] = defaultdict(deque)
        self.message_start: float | None = None
        self.message_end: float | None = None
        self.first_tool_start: float | None = None
        self.thinking_lines: list[str] = []

    def finish_message(self) -> Iterator[str]:
        end = self.first_tool_start if self.first_tool_start is not None else self.message_end
        if self.message_start is not None and end is not None:
            duration = end - self.message_start
            self.timing.thinking += duration
            if self.mode == "details":
                if self.thinking_lines:
                    for line in self.thinking_lines:
                        yield f"{line} [{duration:.2f}s]"
                else:
                    yield f"Thinking: [{duration:.2f}s]"
        self.message_start = self.message_end = self.first_tool_start = None
        self.thinking_lines.clear()

    def render(self, line: bytes) -> Iterator[str]:
        event = _decode_event(line)
        if event is None:
            return
        kind = event.get("type")
        now = monotonic()
        message = event.get("message")
        if isinstance(message, dict) and message.get("role") == "assistant":
            if kind == "message_start":
                yield from self.finish_message()
                self.message_start = now
                return
            if kind == "message_end" and self.message_start is not None:
                self.message_end = now
                self.thinking_lines = list(_render_event(event, self.mode, self.token))
                content = message.get("content")
                has_tool = isinstance(content, list) and any(
                    isinstance(block, dict) and block.get("type") == "toolCall" for block in content
                )
                # Pi can publish the final message before it starts executing its tools.
                if self.first_tool_start is not None or not has_tool:
                    yield from self.finish_message()
                return
        name = event.get("toolName")
        duration = None
        if isinstance(name, str):
            if kind == "tool_execution_start":
                if self.message_start is not None and self.first_tool_start is None:
                    self.first_tool_start = now
                    if self.message_end is not None:
                        yield from self.finish_message()
                self.tools[name].append(now)
            elif kind == "tool_execution_end" and (starts := self.tools.get(name)):
                duration = now - starts.popleft()
                if not starts:
                    del self.tools[name]
                self.timing.tools += duration
        for index, item in enumerate(_render_event(event, self.mode, self.token)):
            yield f"{item} [{duration:.2f}s]" if index == 0 and duration is not None else item


async def _follow(
    path: Path, offset: int, ended: asyncio.Event, prefix: str, attempt: _AttemptLog
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
                        for item in attempt.finish_message():
                            print(f"{prefix} {item}", flush=True)
                        return
                    await asyncio.sleep(0.1)
                    continue
                complete = line.endswith(b"\n")
                if discarding or len(line) > _MAX_RECORD:
                    discarding = not complete
                elif complete or ended.is_set():
                    for item in attempt.render(line):
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
    path: Path,
    *,
    offset: int,
    mode: LogMode | None,
    prefix: str,
    token: str,
    timing: TurnTiming | None = None,
) -> AsyncIterator[None]:
    if mode is None:
        yield
        return
    ended = asyncio.Event()
    attempt = _AttemptLog(mode, token, timing if timing is not None else TurnTiming())
    task = asyncio.create_task(_follow(path, offset, ended, prefix, attempt))
    try:
        yield
    finally:
        ended.set()
        await task
