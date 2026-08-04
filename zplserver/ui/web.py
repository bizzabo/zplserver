"""A web interface for zplserver.

The printer is already a network server, so the interface is served over HTTP on
a second port rather than drawn with a desktop toolkit. That keeps it on the same
event loop as the printer, lets the browser handle image display and downloads,
and means it works over a network or in a container as well as locally.
"""

import asyncio
import json
import logging
import time
import webbrowser
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from aiohttp import web

from zplserver import events, reporting
from zplserver.printer import DPI, Printer
from zplserver.server import PrintServer, install_shutdown_handlers

_logger = logging.getLogger("zplserver")

STATIC = Path(__file__).parent / "static"
MAX_LABELS = 200
MAX_LOGS = 2000
KEEPALIVE_SECONDS = 20


@dataclass
class LabelRecord:
    id: int
    at: float
    connection: int
    zpl: str
    png: bytes
    commands: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "id": self.id,
            "at": self.at,
            "connection": self.connection,
            "bytes": len(self.png),
            "zpl_bytes": len(self.zpl),
            "commands": len(self.commands),
        }

    def detail(self) -> dict:
        return {**self.summary(), "zpl": self.zpl, "decoded": self.commands}


class State:
    """Everything the interface shows, and the fan-out to connected browsers."""

    def __init__(self, server: PrintServer) -> None:
        self.server = server
        self.labels: deque[LabelRecord] = deque(maxlen=MAX_LABELS)
        self.logs: deque[dict] = deque(maxlen=MAX_LOGS)
        self.clients: list[asyncio.Queue] = []
        self._next_id = 1
        self.loop: asyncio.AbstractEventLoop | None = None
        self.closing = False

    # -- fan-out to browsers ------------------------------------------------

    def add_client(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_LOGS)
        self.clients.append(queue)
        return queue

    def remove_client(self, queue: asyncio.Queue) -> None:
        if queue in self.clients:
            self.clients.remove(queue)

    def begin_shutdown(self) -> None:
        """Release the event streams.

        Each one is parked on its queue for up to the keepalive interval, and
        aiohttp waits for open handlers before finishing cleanup. Without a nudge
        that wait is the shutdown time.
        """
        self.closing = True
        self.broadcast({"type": "closing"})

    def broadcast(self, message: dict) -> None:
        for queue in list(self.clients):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                pass

    # -- state changes -----------------------------------------------------

    def add_log(self, level: str, message: str, at: float) -> None:
        entry = {"level": level, "message": message, "at": at}
        self.logs.append(entry)
        self.broadcast({"type": "log", **entry})

    def add_label(self, event: events.LabelRendered) -> None:
        record = LabelRecord(
            id=self._next_id,
            at=time.time(),
            connection=event.connection,
            zpl=event.zpl,
            png=event.png,
            commands=event.commands,
        )
        self._next_id += 1
        evicted = len(self.labels) == self.labels.maxlen
        self.labels.append(record)
        if evicted:
            self.broadcast({"type": "evicted"})
        self.broadcast({"type": "label", "label": record.summary()})

    def find(self, label_id: int) -> LabelRecord | None:
        return next((label for label in self.labels if label.id == label_id), None)

    def dismiss(self, label_id: int) -> bool:
        record = self.find(label_id)
        if record is None:
            return False
        self.labels.remove(record)
        self.broadcast({"type": "dismissed", "id": label_id})
        return True

    def clear(self) -> int:
        count = len(self.labels)
        self.labels.clear()
        self.broadcast({"type": "cleared"})
        return count

    def status(self) -> dict:
        printer = self.server.printer
        return {
            "running": self.server.is_running,
            "address": self.server.address,
            "settings": {
                "width": printer.label_width,
                "height": printer.label_height,
                "dpi": printer.dpi.value,
                "port": printer.port,
            },
        }

    def broadcast_status(self) -> None:
        self.broadcast({"type": "status", "status": self.status()})


class StateLogHandler(logging.Handler):
    """Feed log records into the interface from whichever thread emits them."""

    def __init__(self, state: State) -> None:
        super().__init__()
        self.state = state

    def emit(self, record: logging.LogRecord) -> None:
        if self.state.loop is None:
            return
        try:
            message = self.format(record)
        except Exception:  # pragma: no cover - formatting must never crash us
            return
        try:
            self.state.loop.call_soon_threadsafe(
                self.state.add_log, record.levelname, message, record.created
            )
        except RuntimeError:
            # Loop already closed while shutting down.
            pass


async def collect_labels(state: State) -> None:
    """Keep the label gallery in step with what the printer renders."""
    with state.server.bus.subscribe() as queue:
        while True:
            event = await queue.get()
            if isinstance(event, events.LabelRendered):
                state.add_label(event)
            elif isinstance(event, (events.ServerStarted, events.ServerStopped)):
                state.broadcast_status()


def json_response(payload) -> web.Response:
    return web.json_response(payload, dumps=lambda value: json.dumps(value, default=str))


def build_app(state: State) -> web.Application:
    app = web.Application()

    async def release_streams(_: web.Application) -> None:
        state.begin_shutdown()

    app.on_shutdown.append(release_streams)

    async def index(request: web.Request) -> web.StreamResponse:
        return web.FileResponse(STATIC / "index.html")

    async def get_state(request: web.Request) -> web.Response:
        return json_response(
            {
                **state.status(),
                "labels": [label.summary() for label in state.labels],
                "logs": list(state.logs),
            }
        )

    async def stream(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
        await response.prepare(request)
        queue = state.add_client()
        try:
            while not state.closing:
                try:
                    message = await asyncio.wait_for(
                        queue.get(), timeout=KEEPALIVE_SECONDS
                    )
                except asyncio.TimeoutError:
                    await response.write(b": keepalive\n\n")
                    continue
                if message.get("type") == "closing":
                    break
                data = json.dumps(message, default=str)
                await response.write(f"data: {data}\n\n".encode())
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            state.remove_client(queue)
        return response

    async def label_png(request: web.Request) -> web.StreamResponse:
        record = state.find(int(request.match_info["label_id"]))
        if record is None:
            raise web.HTTPNotFound()
        download = request.query.get("download")
        headers = {"Cache-Control": "no-store"}
        if download:
            name = f"label-{record.id}.png"
            headers["Content-Disposition"] = f'attachment; filename="{name}"'
        return web.Response(body=record.png, content_type="image/png", headers=headers)

    async def label_detail(request: web.Request) -> web.Response:
        record = state.find(int(request.match_info["label_id"]))
        if record is None:
            raise web.HTTPNotFound()
        return json_response(record.detail())

    async def dismiss(request: web.Request) -> web.Response:
        found = state.dismiss(int(request.match_info["label_id"]))
        if not found:
            raise web.HTTPNotFound()
        return json_response({"ok": True})

    async def clear(request: web.Request) -> web.Response:
        return json_response({"ok": True, "cleared": state.clear()})

    async def start_server(request: web.Request) -> web.Response:
        try:
            address = await state.server.start()
        except OSError as exc:
            _logger.error(
                f"Could not listen on port {state.server.printer.port}: {exc}"
            )
            return json_response({"ok": False, "error": str(exc)})
        state.broadcast_status()
        return json_response({"ok": True, "address": address})

    async def stop_server(request: web.Request) -> web.Response:
        await state.server.stop()
        state.broadcast_status()
        return json_response({"ok": True})

    async def update_settings(request: web.Request) -> web.Response:
        body = await request.json()
        printer = state.server.printer
        was_running = state.server.is_running
        try:
            if "width" in body:
                printer.label_width = int(body["width"])
            if "height" in body:
                printer.label_height = int(body["height"])
            if "dpi" in body:
                printer.dpi = DPI(str(body["dpi"]))
                printer.vars["head.resolution.in_dpi"] = printer.dpi.value
            if "port" in body:
                port = int(body["port"])
                if port != printer.port:
                    if was_running:
                        await state.server.stop()
                    printer.port = port
                    if was_running:
                        await state.server.start()
        except (ValueError, KeyError) as exc:
            return json_response({"ok": False, "error": str(exc)})

        _logger.info("Settings updated")
        state.broadcast_status()
        return json_response({"ok": True, **state.status()})

    app.router.add_get("/", index)
    app.router.add_get("/api/state", get_state)
    app.router.add_get("/api/events", stream)
    app.router.add_get("/api/labels/{label_id}", label_detail)
    app.router.add_get("/labels/{label_id}.png", label_png)
    app.router.add_post("/api/labels/{label_id}/dismiss", dismiss)
    app.router.add_post("/api/labels/clear", clear)
    app.router.add_post("/api/server/start", start_server)
    app.router.add_post("/api/server/stop", stop_server)
    app.router.add_post("/api/settings", update_settings)
    return app


async def run_ui(
    printer: Printer,
    ui_port: int = 8080,
    host: str = "127.0.0.1",
    open_browser: bool = True,
) -> None:
    """Serve the interface, and the printer alongside it, until interrupted."""
    server = PrintServer(printer)
    state = State(server)
    state.loop = asyncio.get_running_loop()

    handler = StateLogHandler(state)
    handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(handler)

    tasks = [
        asyncio.ensure_future(reporting.report(printer.bus, open_labels=False)),
        asyncio.ensure_future(collect_labels(state)),
    ]

    runner = web.AppRunner(build_app(state), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host, ui_port)
    try:
        await site.start()
    except OSError as exc:
        _logger.error(f"Could not serve the interface on port {ui_port}: {exc}")
        for task in tasks:
            task.cancel()
        await runner.cleanup()
        _logger.removeHandler(handler)
        return

    url = f"http://{host}:{ui_port}"
    _logger.info(f"Web interface on {url}")

    try:
        await server.start()
    except OSError as exc:
        _logger.error(f"Could not listen on port {printer.port}: {exc}")
    state.broadcast_status()

    if open_browser:
        webbrowser.open(url)

    stopped = asyncio.Event()
    install_shutdown_handlers(stopped.set)
    try:
        await stopped.wait()
    except asyncio.CancelledError:
        pass
    finally:
        _logger.info("Shutting down zplserver")
        for task in tasks:
            task.cancel()
        await server.stop()
        await runner.cleanup()
        _logger.removeHandler(handler)
