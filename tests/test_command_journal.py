"""Journal crash tails, corruption, and durable-write failure boundaries."""

import errno
from uuid import uuid4

import pytest
from test_match_controller import run_async_test

from aw2_lab.command_journal import (
    CommandJournalError,
    JournalEvent,
    JsonlCommandJournal,
    new_journal_entry,
)
from aw2_lab.match_contract import CommandStatus, ErrorCode
from aw2_lab.match_controller import MatchController, MatchControllerError


def entry():
    return new_journal_entry(
        event=JournalEvent.ACCEPTED,
        command_id=uuid4(),
        request_id=uuid4(),
        match_id=uuid4(),
        operation_name="test",
        payload_fingerprint="0" * 64,
        payload={},
        accepted_revision=1,
        expected_revision=1,
        status=CommandStatus.QUEUED,
    )


@run_async_test
async def test_incomplete_tail_is_repaired_once_without_discarding_prior_records(tmp_path):
    journal = JsonlCommandJournal(tmp_path / "commands.jsonl")
    accepted = entry()
    await journal.append(accepted)
    valid = journal.path.read_bytes()
    journal.path.write_bytes(valid + b'{"event":"running"')
    repaired = await journal.read_entries()
    assert repaired.entries == (accepted,)
    assert repaired.diagnostics[0].code is ErrorCode.JOURNAL_CORRUPT
    assert repaired.diagnostics[0].details["recovery_required"] is True
    assert journal.path.read_bytes() == valid
    assert (await journal.read_entries()).diagnostics == ()


@pytest.mark.parametrize("corrupt", [b"not-json\n", b"{}\n", b"\n"])
@run_async_test
async def test_complete_malformed_records_are_not_silently_repaired(tmp_path, corrupt):
    journal = JsonlCommandJournal(tmp_path / "commands.jsonl")
    await journal.append(entry())
    data = journal.path.read_bytes() + corrupt
    journal.path.write_bytes(data)
    with pytest.raises(CommandJournalError) as caught:
        await journal.read_entries()
    assert caught.value.body.code is ErrorCode.JOURNAL_CORRUPT
    assert caught.value.body.details["line"] == 2
    assert journal.path.read_bytes() == data
    controller = MatchController(journal=journal)
    await controller.start()
    try:
        assert not controller.queue_accepting
    finally:
        await controller.stop()


@run_async_test
async def test_failed_acceptance_write_never_executes_and_stops_new_acceptance(
    tmp_path, monkeypatch
):
    journal = JsonlCommandJournal(tmp_path / "commands.jsonl")
    controller = MatchController(journal=journal)
    await controller.start()
    match = await controller.create_match()
    called = False

    async def forbidden():
        nonlocal called
        called = True
        raise AssertionError("An unjournaled command must not execute")

    def fail(_line):
        raise OSError(errno.ENOSPC, "private disk diagnostic")

    monkeypatch.setattr(journal, "_append_sync", fail)
    try:
        with pytest.raises(MatchControllerError) as caught:
            await controller.submit_serialized_mutation(
                match_id=match.match_id,
                request_id=uuid4(),
                operation_name="test_failure",
                payload={},
                expected_revision=0,
                mutates_emulator=False,
                handler=forbidden,
            )
        assert caught.value.body.code is ErrorCode.RECOVERY_REQUIRED
        assert not controller.queue_accepting
        assert not called
        with pytest.raises(MatchControllerError):
            await controller.submit_serialized_mutation(
                match_id=match.match_id,
                request_id=uuid4(),
                operation_name="test_failure",
                payload={},
                expected_revision=0,
                mutates_emulator=False,
                handler=forbidden,
            )
        assert not called
    finally:
        await controller.stop()


@run_async_test
async def test_journal_io_errors_do_not_echo_private_paths(tmp_path, monkeypatch):
    journal = JsonlCommandJournal(tmp_path / "commands.jsonl")

    def fail():
        raise OSError(errno.EACCES, "secret credential and /private/server/path")

    monkeypatch.setattr(journal, "_read_sync", fail)
    with pytest.raises(CommandJournalError) as caught:
        await journal.read_entries()
    assert caught.value.body.code is ErrorCode.STORAGE_UNAVAILABLE
    assert "secret" not in caught.value.body.model_dump_json()
    assert "/private" not in caught.value.body.model_dump_json()
