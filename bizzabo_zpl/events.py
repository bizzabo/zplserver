"""Events published by the print server.

The server does not know how its output is presented. It publishes events and
whatever is driving it — the command line, the web interface, both at once —
subscribes and decides what to do with them.
"""

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field

# Dropping events is better than letting a slow subscriber apply backpressure to
# the printer, so subscriber queues are bounded.
QUEUE_SIZE = 2048


@dataclass(frozen=True)
class ServerStarted:
    address: str


@dataclass(frozen=True)
class ServerStopped:
    pass


@dataclass(frozen=True)
class ConnectionOpened:
    connection: int
    peer: str


@dataclass(frozen=True)
class ConnectionClosed:
    connection: int
    reason: str = ""


@dataclass(frozen=True)
class ControlHandled:
    connection: int
    request: str
    response: str


@dataclass(frozen=True)
class ImmediateReceived:
    connection: int
    payload: str
    commands: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LabelReceived:
    connection: int
    zpl: str
    commands: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LabelRendered:
    connection: int
    zpl: str
    png: bytes
    commands: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RenderFailed:
    connection: int
    zpl: str
    reason: str


@dataclass(frozen=True)
class StreamDiscarded:
    connection: int
    length: int
    reason: str


class EventBus:
    """Fan-out of events to any number of independent subscribers."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []
        self.dropped = 0

    def publish(self, event) -> None:
        """Publish without blocking, so callers never need to await."""
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                self.dropped += 1

    @contextmanager
    def subscribe(self, size: int = QUEUE_SIZE):
        queue: asyncio.Queue = asyncio.Queue(maxsize=size)
        self._subscribers.append(queue)
        try:
            yield queue
        finally:
            self._subscribers.remove(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
