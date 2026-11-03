"""Transport-independent, bounded match events; all operations run on the controller loop."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import Field

from aw2_lab.api_contract import ApiLimits, StateResponse
from aw2_lab.match_contract import CommandResult, ContractModel


class SnapshotEvent(ContractModel):
    event: Literal["snapshot"] = "snapshot"
    match_id: UUID
    event_id: str
    payload: StateResponse
    resync: bool


class MatchUpdatedEvent(ContractModel):
    event: Literal["match.updated"] = "match.updated"
    match_id: UUID
    event_id: str
    payload: StateResponse


class CommandUpdatedEvent(ContractModel):
    event: Literal["command.updated"] = "command.updated"
    match_id: UUID
    event_id: str
    payload: CommandResult


MatchEvent = Annotated[
    SnapshotEvent | MatchUpdatedEvent | CommandUpdatedEvent, Field(discriminator="event")
]


@dataclass(frozen=True)
class EventMessage:
    """Serialize once so every subscriber gets identical, immutable bytes."""

    event: MatchEvent
    data: bytes

    @classmethod
    def encode(cls, event: MatchEvent) -> EventMessage:
        return cls(event, event.model_dump_json().encode("utf-8"))


class EventSubscription:
    def __init__(self, *, max_count: int, max_bytes: int) -> None:
        self._max_count = max_count
        self._max_bytes = max_bytes
        self._pending: deque[EventMessage] = deque()
        self._bytes = 0
        self._ready = asyncio.Event()
        self._ending = False
        self._remove: Callable[[], None] = lambda: None

    def push(self, message: EventMessage) -> None:
        if self._ending:
            return
        if (
            len(self._pending) >= self._max_count
            or self._bytes + len(message.data) > self._max_bytes
        ):
            self.close()
            return
        self._pending.append(message)
        self._bytes += len(message.data)
        self._ready.set()

    def finish(self) -> None:
        """Drain already published events, then end."""
        self._ending = True
        self._remove()
        self._ready.set()

    def close(self) -> None:
        """Drop pending data on revocation, disconnect, overflow, or shutdown."""
        self._pending.clear()
        self._bytes = 0
        self.finish()

    async def next(self) -> EventMessage:
        while True:
            if self._pending:
                message = self._pending.popleft()
                self._bytes -= len(message.data)
                return message
            if self._ending:
                raise StopAsyncIteration
            self._ready.clear()
            await self._ready.wait()


@dataclass
class _Channel:
    cursor: str
    anchor: str
    history: deque[EventMessage] = field(default_factory=deque)
    history_bytes: int = 0
    subscribers: set[EventSubscription] = field(default_factory=set)
    state: StateResponse | None = None


class MatchEventPublisher:
    def __init__(
        self,
        *,
        replay_count: int = ApiLimits().event_replay_count,
        replay_bytes: int = ApiLimits().event_replay_bytes,
        subscriber_count: int = ApiLimits().subscriber_event_count,
        subscriber_bytes: int = ApiLimits().subscriber_bytes,
    ) -> None:
        if min(replay_count, replay_bytes, subscriber_count, subscriber_bytes) < 1:
            raise ValueError("Event limits must be positive")
        self._run = uuid4()
        self._sequence = 0
        self._channels: dict[UUID, _Channel] = {}
        self._replay_count = replay_count
        self._replay_bytes = replay_bytes
        self._subscriber_count = subscriber_count
        self._subscriber_bytes = subscriber_bytes

    def _channel(self, match_id: UUID) -> _Channel:
        initial = f"{self._run}:0"
        return self._channels.setdefault(match_id, _Channel(initial, initial))

    def _id(self) -> str:
        self._sequence += 1
        return f"{self._run}:{self._sequence}"

    def state_changed(self, state: StateResponse) -> None:
        channel = self._channel(state.summary.match_id)
        if channel.state == state:
            return
        channel.state = state
        self._publish(
            MatchUpdatedEvent(match_id=state.summary.match_id, event_id=self._id(), payload=state)
        )

    def command_changed(self, result: CommandResult) -> None:
        self._publish(
            CommandUpdatedEvent(match_id=result.match_id, event_id=self._id(), payload=result)
        )

    def _publish(self, event: MatchUpdatedEvent | CommandUpdatedEvent) -> None:
        channel = self._channel(event.match_id)
        message = EventMessage.encode(event)
        channel.cursor = event.event_id
        channel.history.append(message)
        channel.history_bytes += len(message.data)
        while (
            len(channel.history) > self._replay_count or channel.history_bytes > self._replay_bytes
        ):
            removed = channel.history.popleft()
            channel.history_bytes -= len(removed.data)
            channel.anchor = removed.event.event_id
        for subscriber in tuple(channel.subscribers):
            subscriber.push(message)

    def subscribe(self, state: StateResponse, *, cursor: str | None = None) -> EventSubscription:
        """Called synchronously with state capture under the controller's publication lock."""
        channel = self._channel(state.summary.match_id)
        subscriber = EventSubscription(
            max_count=self._subscriber_count, max_bytes=self._subscriber_bytes
        )
        subscriber._remove = lambda: channel.subscribers.discard(subscriber)
        channel.subscribers.add(subscriber)
        replay: list[EventMessage] | None = None
        if cursor == channel.anchor:
            replay = list(channel.history)
        elif cursor == channel.cursor:
            replay = []
        elif cursor is not None:
            for index, message in enumerate(channel.history):
                if message.event.event_id == cursor:
                    replay = list(channel.history)[index + 1 :]
                    break
        closed = state.summary.lifecycle.value == "closed"
        if replay is not None and (
            len(replay) > self._subscriber_count
            or sum(len(message.data) for message in replay) > self._subscriber_bytes
        ):
            replay = None
        if cursor is None or replay is None or closed:
            subscriber.push(
                EventMessage.encode(
                    SnapshotEvent(
                        match_id=state.summary.match_id,
                        event_id=channel.cursor,
                        payload=state,
                        resync=cursor is not None,
                    )
                )
            )
        else:
            for message in replay:
                subscriber.push(message)
        if closed:
            subscriber.finish()
        return subscriber

    def finish_match(self, match_id: UUID) -> None:
        for subscriber in tuple(self._channel(match_id).subscribers):
            subscriber.finish()

    def close_match(self, match_id: UUID) -> None:
        for subscriber in tuple(self._channel(match_id).subscribers):
            subscriber.close()

    def shutdown(self) -> None:
        for match_id in self._channels:
            self.close_match(match_id)
