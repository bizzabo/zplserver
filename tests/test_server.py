"""The protocol over real sockets, and the server lifecycle."""

import asyncio
import logging
import signal

import pytest

from zplserver import events, reporting
from zplserver.printer import DPI, Printer
from zplserver.render import RenderError
from zplserver.server import PrintServer, install_shutdown_handlers, run_server

from .conftest import (
    LABEL,
    OTHER_LABEL,
    PNG,
    POISON,
    REAL_RENDER_ZPL,
    send,
    settle,
)


def rendered(collected):
    return [e for e in collected if isinstance(e, events.LabelRendered)]


class TestLifecycle:
    async def test_start_binds_a_port(self, printer):
        server = PrintServer(printer, host="127.0.0.1")
        address = await server.start()
        try:
            assert server.is_running
            assert printer.port > 0
            assert address.endswith(str(printer.port))
        finally:
            await server.stop()

    async def test_stop_releases_the_port(self, printer):
        server = PrintServer(printer, host="127.0.0.1")
        await server.start()
        port = printer.port
        await server.stop()
        assert not server.is_running
        with pytest.raises((ConnectionRefusedError, OSError)):
            await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", port), timeout=2
            )

    async def test_start_is_idempotent(self, printer):
        server = PrintServer(printer, host="127.0.0.1")
        first = await server.start()
        try:
            assert await server.start() == first
        finally:
            await server.stop()

    async def test_stop_before_start_is_harmless(self, printer):
        await PrintServer(printer).stop()

    async def test_publishes_start_and_stop(self, printer, collected):
        server = PrintServer(printer, host="127.0.0.1")
        await server.start()
        await server.stop()
        assert await settle(
            lambda: any(isinstance(e, events.ServerStarted) for e in collected)
            and any(isinstance(e, events.ServerStopped) for e in collected)
        )

    async def test_port_in_use_raises_oserror(self, printer):
        blocker = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
        taken = blocker.sockets[0].getsockname()[1]
        try:
            printer.port = taken
            with pytest.raises(OSError):
                await PrintServer(printer, host="127.0.0.1").start()
        finally:
            blocker.close()
            await blocker.wait_closed()

    async def test_cli_reports_a_failed_bind_instead_of_raising(
        self, printer, caplog, monkeypatch
    ):
        """run_server used to let EADDRINUSE escape the entry point.

        The failure is injected rather than staged with a second listener: the
        CLI binds 0.0.0.0 and SO_REUSEADDR means holding 127.0.0.1 does not
        reliably conflict, so a real collision would sometimes succeed and leave
        run_server serving forever.
        """

        async def refuse(*args, **kwargs):
            raise OSError(48, "address already in use")

        monkeypatch.setattr(asyncio, "start_server", refuse)
        with caplog.at_level(logging.ERROR, logger="zplserver"):
            await asyncio.wait_for(run_server(printer), timeout=5)
        assert "Could not listen" in caplog.text

    async def test_serve_forever_requires_a_start(self, printer):
        with pytest.raises(RuntimeError):
            await PrintServer(printer).serve_forever()


class TestShutdownHandlers:
    async def test_installs_what_the_platform_supports(self):
        install_shutdown_handlers(lambda: None)
        loop = asyncio.get_running_loop()
        for name in ("SIGTERM", "SIGINT"):
            sig = getattr(signal, name, None)
            if sig is not None:
                try:
                    loop.remove_signal_handler(sig)
                except (NotImplementedError, RuntimeError):
                    pass

    async def test_survives_a_loop_without_signal_support(self, monkeypatch):
        """add_signal_handler is Unix-only and raises NotImplementedError on
        Windows, which killed the CLI at startup before it ever bound."""
        loop = asyncio.get_running_loop()

        def unsupported(*args, **kwargs):
            raise NotImplementedError

        monkeypatch.setattr(loop, "add_signal_handler", unsupported)
        install_shutdown_handlers(lambda: None)


class TestControlOverTheWire:
    async def test_getvar_is_answered(self, running):
        reply = await send(
            running.printer.port, b'! U1 getvar "appl.name"\r\n', read_reply=True
        )
        assert reply.strip() == b"V74.20.22Z"

    async def test_two_control_commands_in_one_write(self, running):
        reader, writer = await asyncio.open_connection("127.0.0.1", running.printer.port)
        writer.write(
            b'! U1 getvar "appl.name"\r\n! U1 getvar "ezpl.media_type"\r\n'
        )
        await writer.drain()
        assert (await asyncio.wait_for(reader.readline(), 5)).strip() == b"V74.20.22Z"
        assert (await asyncio.wait_for(reader.readline(), 5)).strip() == b"gap/notch"
        writer.close()
        await writer.wait_closed()

    async def test_unterminated_command_is_answered_at_eof(self, running):
        reader, writer = await asyncio.open_connection("127.0.0.1", running.printer.port)
        writer.write(b'! U1 getvar "appl.name"')
        await writer.drain()
        if writer.can_write_eof():
            writer.write_eof()
        assert (await asyncio.wait_for(reader.readline(), 5)).strip() == b"V74.20.22Z"
        writer.close()
        await writer.wait_closed()


class TestLabelsOverTheWire:
    async def test_one_label(self, running, collected):
        await send(running.printer.port, LABEL.encode())
        assert await settle(lambda: len(rendered(collected)) == 1)
        assert rendered(collected)[0].png == PNG
        assert rendered(collected)[0].zpl == LABEL

    async def test_two_labels_in_one_write(self, running, collected):
        await send(running.printer.port, (LABEL + OTHER_LABEL).encode())
        assert await settle(lambda: len(rendered(collected)) == 2)
        assert [e.zpl for e in rendered(collected)] == [LABEL, OTHER_LABEL]

    async def test_label_delivered_one_byte_at_a_time(self, running, collected):
        reader, writer = await asyncio.open_connection("127.0.0.1", running.printer.port)
        for byte in LABEL.encode():
            writer.write(bytes([byte]))
            await writer.drain()
        writer.close()
        await writer.wait_closed()
        assert await settle(lambda: len(rendered(collected)) == 1)
        assert rendered(collected)[0].zpl == LABEL

    async def test_label_larger_than_one_read(self, running, collected):
        big = "^XA^FX" + ("p" * 5000) + "^FS^FDx^FS^XZ"
        await send(running.printer.port, big.encode())
        assert await settle(lambda: len(rendered(collected)) == 1)
        assert rendered(collected)[0].zpl == big

    async def test_control_and_label_on_one_connection(self, running, collected):
        reader, writer = await asyncio.open_connection("127.0.0.1", running.printer.port)
        writer.write(b'! U1 getvar "appl.name"\r\n' + LABEL.encode())
        await writer.drain()
        assert (await asyncio.wait_for(reader.readline(), 5)).strip() == b"V74.20.22Z"
        writer.close()
        await writer.wait_closed()
        assert await settle(lambda: len(rendered(collected)) == 1)

    async def test_junk_then_a_label(self, running, collected):
        await send(running.printer.port, b"\x00\x00nonsense" + LABEL.encode())
        assert await settle(lambda: len(rendered(collected)) == 1)

    async def test_unterminated_label_is_discarded(self, running, collected):
        await send(running.printer.port, b"^XA^FDnever finished")
        assert await settle(
            lambda: any(isinstance(e, events.StreamDiscarded) for e in collected)
        )
        assert rendered(collected) == []

    async def test_decoded_commands_accompany_the_label(self, running, collected):
        await send(running.printer.port, LABEL.encode())
        assert await settle(lambda: len(rendered(collected)) == 1)
        decoded = rendered(collected)[0].commands
        assert len(decoded) == 5
        assert any("^FD" in line for line in decoded)

    async def test_multibyte_character_split_across_reads(self, running, collected):
        payload = "^XA^FDMünchen^FS^XZ".encode()
        cut = payload.index(b"\xbc")  # inside the two-byte "ü"
        reader, writer = await asyncio.open_connection("127.0.0.1", running.printer.port)
        writer.write(payload[:cut])
        await writer.drain()
        await asyncio.sleep(0.05)
        writer.write(payload[cut:])
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        assert await settle(lambda: len(rendered(collected)) == 1)
        assert "München" in rendered(collected)[0].zpl


class TestFailureHandling:
    async def test_render_failure_is_published_not_raised(self, running, collected):
        await send(running.printer.port, f"^XA^FD{POISON}^FS^XZ".encode())
        assert await settle(
            lambda: any(isinstance(e, events.RenderFailed) for e in collected)
        )
        assert rendered(collected) == []

    async def test_server_still_works_after_a_render_failure(self, running, collected):
        await send(running.printer.port, f"^XA^FD{POISON}^FS^XZ".encode())
        await settle(lambda: any(isinstance(e, events.RenderFailed) for e in collected))
        reply = await send(
            running.printer.port, b'! U1 getvar "appl.name"\r\n', read_reply=True
        )
        assert reply.strip() == b"V74.20.22Z"

    async def test_rendering_does_not_block_other_clients(self, printer):
        """urllib blocks, so rendering on the event loop stalled every client."""
        release = asyncio.Event()
        loop = asyncio.get_running_loop()

        def slow_render(zpl, width=4, height=3, index=0, dpmm=12):
            # Block this worker thread until the test says otherwise.
            asyncio.run_coroutine_threadsafe(_wait(), loop).result(timeout=10)
            return PNG

        async def _wait():
            await release.wait()

        import zplserver.printer as printer_module

        original = printer_module.render_zpl
        printer_module.render_zpl = slow_render
        server = PrintServer(printer, host="127.0.0.1")
        reporter = asyncio.ensure_future(
            reporting.report(printer.bus, open_labels=False)
        )
        await server.start()
        try:
            printing = asyncio.ensure_future(send(printer.port, LABEL.encode()))
            await asyncio.sleep(0.1)
            reply = await asyncio.wait_for(
                send(printer.port, b'! U1 getvar "appl.name"\r\n', read_reply=True),
                timeout=3,
            )
            assert reply.strip() == b"V74.20.22Z"
            release.set()
            await asyncio.wait_for(printing, timeout=5)
        finally:
            printer_module.render_zpl = original
            release.set()
            reporter.cancel()
            await server.stop()

    async def test_many_clients_at_once(self, running, collected):
        await asyncio.gather(
            *(send(running.printer.port, LABEL.encode()) for _ in range(10))
        )
        assert await settle(lambda: len(rendered(collected)) == 10)

    async def test_connection_numbers_are_distinct(self, running, collected):
        await send(running.printer.port, LABEL.encode())
        await send(running.printer.port, LABEL.encode())
        assert await settle(lambda: len(rendered(collected)) == 2)
        opened = [e for e in collected if isinstance(e, events.ConnectionOpened)]
        assert len({e.connection for e in opened}) == len(opened)


class TestEventBus:
    async def test_multiple_subscribers_all_receive(self):
        bus = events.EventBus()
        with bus.subscribe() as first, bus.subscribe() as second:
            bus.publish(events.ServerStopped())
            assert isinstance(await first.get(), events.ServerStopped)
            assert isinstance(await second.get(), events.ServerStopped)

    async def test_unsubscribing_removes_the_queue(self):
        bus = events.EventBus()
        with bus.subscribe():
            assert bus.subscriber_count == 1
        assert bus.subscriber_count == 0

    async def test_publish_without_subscribers_is_harmless(self):
        events.EventBus().publish(events.ServerStopped())

    async def test_a_full_subscriber_is_counted_not_blocking(self):
        bus = events.EventBus()
        with bus.subscribe(size=1):
            bus.publish(events.ServerStopped())
            bus.publish(events.ServerStopped())
        assert bus.dropped == 1


class TestReporting:
    def test_every_event_is_describable(self):
        samples = [
            events.ServerStarted("127.0.0.1:9100"),
            events.ServerStopped(),
            events.ConnectionOpened(1, "127.0.0.1:1234"),
            events.ConnectionClosed(1, ""),
            events.ControlHandled(1, "getvar", "x"),
            events.ImmediateReceived(1, "~HS"),
            events.LabelReceived(1, LABEL),
            events.LabelRendered(1, LABEL, PNG),
            events.RenderFailed(1, LABEL, "boom"),
            events.StreamDiscarded(1, 12, "incomplete"),
        ]
        for event in samples:
            described = reporting.describe(event)
            assert described is not None, event
            level, message = described
            assert isinstance(level, int) and message

    def test_unknown_events_are_ignored(self):
        assert reporting.describe(object()) is None

    def test_failures_are_reported_at_error_level(self):
        level, message = reporting.describe(events.RenderFailed(1, LABEL, "boom"))
        assert level == logging.ERROR
        assert "boom" in message

    async def test_report_opens_rendered_labels_when_asked(self, monkeypatch):
        opened = []
        monkeypatch.setattr("zplserver.reporting.open_image", opened.append)
        bus = events.EventBus()
        task = asyncio.ensure_future(reporting.report(bus, open_labels=True))
        await asyncio.sleep(0.05)
        bus.publish(events.LabelRendered(1, LABEL, PNG))
        assert await settle(lambda: opened == [PNG])
        task.cancel()

    async def test_report_leaves_labels_alone_when_not_asked(self, monkeypatch):
        opened = []
        monkeypatch.setattr("zplserver.reporting.open_image", opened.append)
        bus = events.EventBus()
        task = asyncio.ensure_future(reporting.report(bus, open_labels=False))
        await asyncio.sleep(0.05)
        bus.publish(events.LabelRendered(1, LABEL, PNG))
        await asyncio.sleep(0.1)
        assert opened == []
        task.cancel()


class TestRenderErrors:
    def test_http_failure_becomes_a_render_error(self, monkeypatch):
        import io
        import urllib.error

        from zplserver import render

        def boom(*args, **kwargs):
            raise urllib.error.HTTPError(
                "url", 404, "Not Found", {}, io.BytesIO(b"ERROR: no labels")
            )

        monkeypatch.setattr(render.urllib.request, "urlopen", boom)
        with pytest.raises(RenderError, match="404") as caught:
            REAL_RENDER_ZPL("^XA^XZ")
        # The service's own explanation is worth surfacing.
        assert "no labels" in str(caught.value)

    def test_network_failure_becomes_a_render_error(self, monkeypatch):
        from zplserver import render

        def boom(*args, **kwargs):
            raise OSError("no route to host")

        monkeypatch.setattr(render.urllib.request, "urlopen", boom)
        with pytest.raises(RenderError, match="no route"):
            REAL_RENDER_ZPL("^XA^XZ")

    def test_url_carries_the_configured_geometry(self, monkeypatch):
        from zplserver import render

        seen = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return PNG

        def capture(url, data=None):
            seen["url"] = url
            seen["data"] = data
            return Response()

        monkeypatch.setattr(render.urllib.request, "urlopen", capture)
        REAL_RENDER_ZPL("^XA^XZ", width=4, height=6, dpmm=8)
        assert "8dpmm" in seen["url"]
        assert "4x6" in seen["url"]
        assert seen["data"] == b"^XA^XZ"
