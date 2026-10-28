"""Append-only command lifecycle journal for restart reconciliation."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import Field, ValidationError, model_validator

from aw2_lab.match_contract import (
    CommandStatus,
    ContractModel,
    ErrorBody,
    ErrorCode,
    Revision,
)


class JournalEvent(StrEnum):
    ACCEPTED = "accepted"
    RUNNING = "running"
    TERMINAL = "terminal"


class CommandJournalEntry(ContractModel):
    """One redacted command lifecycle event; credentials are never journaled."""

    entry_schema_version: Literal[1] = 1
    event: JournalEvent
    recorded_at: datetime
    command_id: UUID
    request_id: UUID
    match_id: UUID
    checkpoint_id: UUID | None = None
    operation_name: str = Field(min_length=1)
    payload_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload: dict[str, Any]
    accepted_revision: Revision
    expected_revision: Revision | None
    status: CommandStatus
    resulting_revision: Revision | None = None
    error: ErrorBody | None = None

    @model_validator(mode="after")
    def validate_event_status(self) -> CommandJournalEntry:
        if self.event is JournalEvent.ACCEPTED and self.status is not CommandStatus.QUEUED:
            raise ValueError("Accepted journal entries must have queued status")
        if self.event is JournalEvent.RUNNING and self.status is not CommandStatus.RUNNING:
            raise ValueError("Running journal entries must have running status")
        if self.event is JournalEvent.TERMINAL and self.status in {
            CommandStatus.QUEUED,
            CommandStatus.RUNNING,
        }:
            raise ValueError("Terminal journal entries require terminal status")
        if self.checkpoint_id is not None and self.event is not JournalEvent.TERMINAL:
            raise ValueError("Only terminal journal entries may reference a committed checkpoint")
        return self


class CommandJournal(Protocol):
    async def append(self, entry: CommandJournalEntry) -> None: ...


@dataclass(frozen=True, slots=True)
class JournalReadResult:
    entries: tuple[CommandJournalEntry, ...]
    diagnostics: tuple[ErrorBody, ...] = ()


class CommandJournalError(OSError):
    """Structured journal corruption or storage failure with a safe public diagnostic."""

    def __init__(self, body: ErrorBody) -> None:
        super().__init__(body.message)
        self.body = body


class JsonlCommandJournal:
    """Persist each command event as a flushed JSON line at a trusted local path."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()

    async def append(self, entry: CommandJournalEntry) -> None:
        line = (entry.model_dump_json() + "\n").encode("utf-8")
        async with self._lock:
            try:
                await asyncio.to_thread(self._append_sync, line)
            except OSError as error:
                raise CommandJournalError(_storage_error("append journal", error)) from error

    async def read_entries(self) -> JournalReadResult:
        """Read valid entries and report/recover an incomplete final JSONL record."""
        async with self._lock:
            try:
                return await asyncio.to_thread(self._read_sync)
            except CommandJournalError:
                raise
            except OSError as error:
                raise CommandJournalError(_storage_error("read journal", error)) from error

    def _append_sync(self, line: bytes) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            remaining = memoryview(line)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError("Command journal write made no progress")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _read_sync(self) -> JournalReadResult:
        try:
            data = self.path.read_bytes()
        except FileNotFoundError:
            return JournalReadResult(())

        diagnostics: tuple[ErrorBody, ...] = ()
        if data and not data.endswith(b"\n"):
            last_newline = data.rfind(b"\n")
            valid_end = last_newline + 1
            truncated_bytes = len(data) - valid_end
            try:
                with self.path.open("r+b") as journal_file:
                    journal_file.truncate(valid_end)
                    journal_file.flush()
                    os.fsync(journal_file.fileno())
            except OSError as error:
                raise CommandJournalError(
                    _storage_error("repair truncated journal tail", error)
                ) from error
            diagnostics = (
                ErrorBody(
                    code=ErrorCode.JOURNAL_CORRUPT,
                    message="An incomplete trailing journal record was removed",
                    retryable=False,
                    details={
                        "truncated_bytes": truncated_bytes,
                        "recovery_required": True,
                    },
                ),
            )
            data = data[:valid_end]

        entries: list[CommandJournalEntry] = []
        for line_number, line in enumerate(data.splitlines(), start=1):
            if not line:
                raise CommandJournalError(
                    ErrorBody(
                        code=ErrorCode.JOURNAL_CORRUPT,
                        message="Command journal contains an empty record",
                        retryable=False,
                        details={"line": line_number},
                    )
                )
            try:
                entries.append(CommandJournalEntry.model_validate_json(line))
            except ValidationError as error:
                raise CommandJournalError(
                    ErrorBody(
                        code=ErrorCode.JOURNAL_CORRUPT,
                        message="Command journal contains a malformed record",
                        retryable=False,
                        details={"line": line_number, "cause": type(error).__name__},
                    )
                ) from error
        return JournalReadResult(tuple(entries), diagnostics)


def _storage_error(operation: str, error: OSError) -> ErrorBody:
    details: dict[str, str | int | bool | None] = {
        "operation": operation,
        "cause": type(error).__name__,
    }
    if error.errno is not None:
        details["errno"] = error.errno
    return ErrorBody(
        code=ErrorCode.STORAGE_UNAVAILABLE,
        message="Command journal storage is unavailable",
        retryable=True,
        details=details,
    )


def new_journal_entry(
    *,
    event: JournalEvent,
    command_id: UUID,
    request_id: UUID,
    match_id: UUID,
    checkpoint_id: UUID | None = None,
    operation_name: str,
    payload_fingerprint: str,
    payload: dict[str, Any],
    accepted_revision: int,
    expected_revision: int | None,
    status: CommandStatus,
    resulting_revision: int | None = None,
    error: ErrorBody | None = None,
) -> CommandJournalEntry:
    return CommandJournalEntry(
        event=event,
        recorded_at=datetime.now(UTC),
        command_id=command_id,
        request_id=request_id,
        match_id=match_id,
        checkpoint_id=checkpoint_id,
        operation_name=operation_name,
        payload_fingerprint=payload_fingerprint,
        payload=payload,
        accepted_revision=accepted_revision,
        expected_revision=expected_revision,
        status=status,
        resulting_revision=resulting_revision,
        error=error,
    )
