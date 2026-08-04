"""Shared fixtures.

Nothing in this suite is allowed to reach the network. The renderer is always
replaced, and `bizzabo_zpl.printer` imports `render_zpl` into its own namespace, so
that is the name which has to be patched — patching `bizzabo_zpl.render.render_zpl`
alone would leave the printer calling the real thing.
"""

import asyncio
import logging

import pytest

from bizzabo_zpl import render as render_module
from bizzabo_zpl import reporting
from bizzabo_zpl.printer import DPI, Printer
from bizzabo_zpl.render import RenderError
from bizzabo_zpl.server import PrintServer

# Captured before anything patches it, for the few tests that need to exercise
# the real function's error handling.
REAL_RENDER_ZPL = render_module.render_zpl

# A real, minimal 1x1 PNG, so tests can assert on bytes that are actually an image.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c6360000002000154a24f5f0000000049454e44ae426082"
)

LABEL = "^XA^FO50,50^FDHi^FS^XZ"
OTHER_LABEL = "^XA^FO10,10^FDBye^FS^XZ"
# The fake renderer refuses anything containing this.
POISON = "BOOM"


async def fake_render(zpl, width=4, height=3, index=0, dpmm=12):
    """Stand in for the renderer. Awaitable, like the real one."""
    if POISON in zpl:
        raise RenderError("HTTP 404: no labels")
    return PNG


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Make it impossible for a test to render over the network by accident."""
    monkeypatch.setattr("bizzabo_zpl.printer.render_zpl", fake_render)
    monkeypatch.setattr("bizzabo_zpl.render.render_zpl", fake_render)


@pytest.fixture(autouse=True)
def quiet_logging():
    """Keep the printer's log output from cluttering test output."""
    logger = logging.getLogger("bizzabo-zpl")
    previous = logger.level
    logger.setLevel(logging.CRITICAL)
    yield logger
    logger.setLevel(previous)


@pytest.fixture
def printer():
    # Port 0 asks the OS for a free port, so tests never collide.
    return Printer(label_width=4, label_height=3, dpi=DPI.DPI_300, port=0)


@pytest.fixture
async def running(printer):
    """A started PrintServer whose events are being drained."""
    server = PrintServer(printer, host="127.0.0.1")
    reporter = asyncio.ensure_future(reporting.report(printer.bus, open_labels=False))
    await server.start()
    try:
        yield server
    finally:
        reporter.cancel()
        await server.stop()


@pytest.fixture
async def collected(printer):
    """Every event the printer publishes, in order.

    Async on purpose: subscribing needs the running loop, and a sync fixture has
    no reliable access to it.
    """
    received: list = []

    async def drain():
        with printer.bus.subscribe() as queue:
            while True:
                received.append(await queue.get())

    task = asyncio.ensure_future(drain())
    # Let the subscription register before the test publishes anything.
    await asyncio.sleep(0)
    try:
        yield received
    finally:
        task.cancel()


async def send(port: int, payload: bytes, read_reply: bool = False) -> bytes:
    """Connect, write *payload*, optionally read one line, and disconnect."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(payload)
    await writer.drain()
    reply = b""
    if read_reply:
        reply = await asyncio.wait_for(reader.readline(), timeout=5)
    writer.close()
    try:
        await writer.wait_closed()
    except (ConnectionResetError, BrokenPipeError):
        pass
    return reply


async def settle(predicate, timeout: float = 5.0) -> bool:
    """Wait for *predicate* rather than sleeping a guessed interval."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return predicate()
