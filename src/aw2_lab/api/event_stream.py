"""SSE framing only; state publication, replay, and access checks are shared services."""

from collections.abc import AsyncIterator

from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from aw2_lab.api_contract import ApiLimits
from aw2_lab.authorization import AuthorizationError
from aw2_lab.authorized_match import AuthorizedEventSubscription


class MatchEventResponse(StreamingResponse):
    def __init__(self, subscription: AuthorizedEventSubscription) -> None:
        self._subscription = subscription
        super().__init__(
            self._messages(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    async def _messages(self) -> AsyncIterator[bytes]:
        while True:
            try:
                message = await self._subscription.next(timeout=ApiLimits().heartbeat_seconds)
            except TimeoutError:
                yield b": heartbeat\n\n"
                continue
            except AuthorizationError, StopAsyncIteration:
                return
            event = message.event
            yield (
                f"id: {event.event_id}\nevent: {event.event}\ndata: ".encode()
                + message.data
                + b"\n\n"
            )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._subscription.close()
