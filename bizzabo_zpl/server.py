"""Server lifecycle, separate from the protocol handling in printer.py.

The command line wants signals to shut this down; a UI wants a button. Neither
belongs in the class itself, so PrintServer only offers start and stop.
"""

import asyncio
import logging
import signal
import sys

from bizzabo_zpl import events, reporting
from bizzabo_zpl.printer import Printer, get_ip

_logger = logging.getLogger("bizzabo-zpl")


class PrintServer:
    def __init__(self, printer: Printer, host: str = "0.0.0.0") -> None:
        self.printer = printer
        self.host = host
        self._server: asyncio.Server | None = None
        self.address = ""

    @property
    def is_running(self) -> bool:
        return self._server is not None

    @property
    def bus(self) -> events.EventBus:
        return self.printer.bus

    async def start(self) -> str:
        """Bind and begin serving, returning the address.

        Raises OSError if the port is unavailable, which callers are expected to
        report rather than treat as fatal.
        """
        if self._server is not None:
            return self.address

        self._server = await asyncio.start_server(
            self.printer.handle_connection, self.host, self.printer.port
        )
        # Port 0 means "any free port", so read back what was actually bound.
        bound = self._server.sockets[0].getsockname()[1] if self._server.sockets else 0
        self.printer.port = bound or self.printer.port
        self.address = f"{get_ip()}:{self.printer.port}"
        self.bus.publish(events.ServerStarted(self.address))
        return self.address

    async def stop(self) -> None:
        if self._server is None:
            return
        server, self._server = self._server, None
        server.close()
        try:
            await server.wait_closed()
        except Exception:
            pass
        self.address = ""
        self.bus.publish(events.ServerStopped())

    async def serve_forever(self) -> None:
        """Serve until cancelled. Assumes start() has already been called."""
        if self._server is None:
            raise RuntimeError("server has not been started")
        try:
            await self._server.serve_forever()
        except asyncio.CancelledError:
            pass


def install_shutdown_handlers(callback) -> None:
    """Ask the loop to call *callback* on termination signals.

    add_signal_handler is Unix-only, and SIGTERM does not exist on Windows at
    all, so this degrades to whatever the platform supports instead of raising.
    """
    loop = asyncio.get_running_loop()
    handled = []
    for name in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, callback)
        except (NotImplementedError, RuntimeError, ValueError):
            # Windows: fall back to the default KeyboardInterrupt behaviour.
            continue
        handled.append(name)

    if not handled and sys.platform == "win32":
        _logger.debug("Signal handlers unavailable, relying on KeyboardInterrupt")


async def run_server(printer: Printer, open_labels: bool = True) -> None:
    """Run the server from the terminal until interrupted.

    Nothing is logged unless somebody is subscribed to the bus, so the reporter
    is started — and confirmed subscribed — before the server can publish
    anything.
    """
    server = PrintServer(printer)
    ready = asyncio.Event()
    reporter = asyncio.ensure_future(
        reporting.report(printer.bus, open_labels=open_labels, ready=ready)
    )
    await ready.wait()

    try:
        await server.start()
    except OSError as exc:
        _logger.error(f"Could not listen on port {printer.port}: {exc}")
        reporter.cancel()
        return

    serving = asyncio.ensure_future(server.serve_forever())
    install_shutdown_handlers(serving.cancel)

    try:
        await serving
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        _logger.error(f"Unhandled exception running bizzabo-zpl: {exc}")
    finally:
        await server.stop()
        reporter.cancel()
        _logger.info("Shutting down bizzabo-zpl")
