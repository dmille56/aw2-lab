"""Append-only command lifecycle journal for restart reconciliation."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import Field, model_validator

from aw2_lab.match_contract import CommandStatus, ContractModel, ErrorBody, Revision


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
        return self


class CommandJournal(Protocol):
    async def append(self, entry: CommandJournalEntry) -> None: ...


class CommandJournalError(OSError):
    """Raised when an entry could not be durably appended."""


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
                detail = error.strerror or "I/O error"
                raise CommandJournalError(f"Could not append command journal: {detail}") from error

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


def new_journal_entry(
    *,
    event: JournalEvent,
    command_id: UUID,
    request_id: UUID,
    match_id: UUID,
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
        operation_name=operation_name,
        payload_fingerprint=payload_fingerprint,
        payload=payload,
        accepted_revision=accepted_revision,
        expected_revision=expected_revision,
        status=status,
        resulting_revision=resulting_revision,
        error=error,
    )
