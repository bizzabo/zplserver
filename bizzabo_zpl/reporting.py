"""Turning events into log lines.

Shared by the command line and the web interface so that both describe what the
printer did in the same words. The only difference is that the command line also
opens each rendered label in an image viewer.
"""

import asyncio
import logging

from bizzabo_zpl import events
from bizzabo_zpl.render import open_image

_logger = logging.getLogger("bizzabo-zpl")


def describe(event) -> tuple[int, str] | None:
    """Render *event* as a (level, message) pair, or None to say nothing."""
    match event:
        case events.ServerStarted(address=address):
            return logging.INFO, f"bizzabo-zpl running on {address}"
        case events.ServerStopped():
            return logging.INFO, "bizzabo-zpl stopped"
        case events.ConnectionOpened(connection=number, peer=peer):
            return logging.DEBUG, f"[Connection {number}: open from {peer}]"
        case events.ConnectionClosed(connection=number, reason=reason):
            detail = f": {reason}" if reason else ""
            return logging.DEBUG, f"[Connection {number}: close{detail}]"
        case events.ControlHandled(request=request, response=response):
            return logging.INFO, f"Command: {request!r} -> {response!r}"
        case events.ImmediateReceived(payload=payload):
            return logging.INFO, f"Immediate command: {payload!r}"
        case events.LabelReceived(zpl=zpl):
            return logging.INFO, f"Received a label ({len(zpl)} bytes)"
        case events.LabelRendered(png=png):
            return logging.INFO, f"Rendered a label ({len(png)} bytes)"
        case events.RenderFailed(reason=reason):
            return logging.ERROR, f"Label could not be rendered: {reason}"
        case events.StreamDiscarded(connection=number, length=length, reason=reason):
            return (
                logging.WARNING,
                f"Discarding {length} bytes from connection {number} ({reason})",
            )
    return None


def log_event(event) -> None:
    described = describe(event)
    if described is None:
        return
    level, message = described
    _logger.log(level, message)

    # The decoded commands are only interesting when asked for.
    commands = getattr(event, "commands", None)
    if commands and _logger.isEnabledFor(logging.DEBUG):
        for command in commands:
            _logger.debug(command)


async def report(
    bus: events.EventBus,
    open_labels: bool = True,
    ready: asyncio.Event | None = None,
) -> None:
    """Log every event until cancelled, optionally opening rendered labels.

    Pass *ready* and await it before starting the server. Subscribing happens
    inside this coroutine, so a caller that starts the server first can publish
    into a bus nobody is listening to yet and lose the opening events.
    """
    with bus.subscribe() as queue:
        if ready is not None:
            ready.set()
        while True:
            event = await queue.get()
            log_event(event)
            if open_labels and isinstance(event, events.LabelRendered):
                await asyncio.to_thread(open_image, event.png)
